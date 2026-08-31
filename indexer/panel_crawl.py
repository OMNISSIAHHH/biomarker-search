"""Incremental, per-search alternative to indexer/crawl.py's full batch crawl, for exactly one
purpose: finding bundled multi-antigen panels whose device_name never mentions the antigen being
searched (confirmed live: K123261's device_name is "ANTI-NRNP/SM", but its real Measurand also
covers Jo-1, Centromere, Scl-70, SS-A, SS-B, and Ribosomal-P — invisible to every text-matching
tier, which only ever reads device_name/statement_or_summary/openfda.device_name).

Two things made the full crawl impractical as a prerequisite for this: it processes 31,000+
devices across every in-scope committee whether or not any of them are ever searched, and — the
two observations that motivated this module specifically — (1) most registrations never mention
a biomarker name at all (nothing to text-match against in the first place), and (2) the ones that
do are usually bundled panels covering several biomarkers under one registration, so a single
device found this way is disproportionately valuable versus one found by ordinary text matching.

This crawls two orders of magnitude less: only the advisory committee(s) a term's own confirmed
matches already belong to (no committee signal, no crawl — see indexer/lookup.py's caller), only
the devices in that committee whose device_name itself looks panel-shaped (PANEL_LIKELY_KEYWORDS
in indexer/db.py — confirmed live against a real sample, ~10% of a committee, not all of it), and
only a bounded number of PDFs per search (MAX_NEW_PDF_CRAWLS_PER_SEARCH). Coverage grows with
usage: a committee's device list and PDF text are both cached forever once fetched (same
devices/pdf_text tables the full crawl already writes to), so the first search touching a fresh
committee pays the discovery cost and every later one — searching a *different* antigen the same
panel happens to also cover — reuses it for free.
"""
import asyncio
from datetime import datetime, timezone

import httpx

from indexer import db, pdf_extract
from indexer.openfda import DEVICE_510K, PAGE_LIMIT, OpenFdaError, fetch_with_retry
from indexer.trace import TraceSink

# Bounds how many openFDA device-list pages (100 devices each) get fetched for one committee in
# one search — keeps a search that happens to be the first ever to touch a fresh committee from
# stalling for as long as indexer/crawl.py's own full scope-population step would. A committee
# too large to finish in one pass just resumes (via committee_scope.next_skip) on the next search
# that still finds no panel candidates for its own term — same "grows with usage" reasoning as
# the PDF-crawl cap below, just for device-list discovery instead.
MAX_DEVICE_PAGES_PER_COMMITTEE_PER_CALL = 5

# Bounds how many new PDF fetches happen in one search — each is a real network fetch + PDF parse
# (see indexer/pdf_extract.py), the genuinely expensive step. 15 keeps this in the same rough
# latency ballpark as the existing Tavily/UMLS AI-crosscheck escalation (indexer/lookup.py's
# compute_and_cache_result), which real searches already tolerate.
MAX_NEW_PDF_CRAWLS_PER_SEARCH = 15
PDF_FETCH_CONCURRENCY = 5


async def ensure_committee_devices_populated(client: httpx.AsyncClient, conn, committee: str,
                                              api_key: str | None = None,
                                              trace: TraceSink | None = None) -> None:
    """Fetches up to MAX_DEVICE_PAGES_PER_COMMITTEE_PER_CALL pages of this committee's device
    list into the `devices` table (same upsert_device() indexer/crawl.py's populate_scope_devices
    uses) — a no-op if this committee was already fully populated by an earlier search. Resumable:
    picks up from committee_scope.next_skip rather than re-fetching devices already stored.

    Paginates directly via fetch_with_retry rather than openfda.run_query — run_query always
    starts its own internal `skip` at 0, so calling it with an ever-larger max_records would
    silently re-fetch every earlier page on every call instead of resuming, defeating the whole
    point of tracking next_skip.
    """
    scope = db.get_committee_scope(conn, committee)
    if scope and scope["fully_populated"]:
        return
    skip = scope["next_skip"] if scope else 0
    total = None
    for _ in range(MAX_DEVICE_PAGES_PER_COMMITTEE_PER_CALL):
        params = {"search": f'advisory_committee:"{committee}"', "limit": PAGE_LIMIT, "skip": skip}
        if api_key:
            params["api_key"] = api_key
        res = await fetch_with_retry(client, DEVICE_510K, params)
        if res.status_code == 404:
            total = 0
            break
        if res.status_code >= 400:
            # Same "intermittent upstream hiccup" posture openfda.fetch_all_in_scope already
            # documents for the full crawl — stop this call, next_skip stays where it is, a later
            # search retries from the same spot rather than losing progress or crashing the search.
            break
        data = res.json()
        records = data.get("results", [])
        total = data.get("meta", {}).get("results", {}).get("total", 0)
        if not records:
            break
        for r in records:
            db.upsert_device(conn, r, source="510k")
        skip += len(records)
        # Committed after EACH page, not once after every page — confirmed live this is load-
        # bearing, not cosmetic: with a single commit at the end, this function's write
        # transaction stayed open across up to 5 sequential openFDA round-trips (a real "database
        # is locked" reported by a concurrent search, exceeding the 5s busy_timeout in
        # indexer/db.py's connect()). A concurrent writer only ever has to wait for one page's
        # worth of upserts now, not the whole loop, and a cancelled/killed process loses at most
        # one page instead of up to five.
        conn.commit()
        if skip >= total:
            break
    fully_populated = total is not None and skip >= total
    db.upsert_committee_scope(conn, committee, skip, fully_populated, datetime.now(timezone.utc).isoformat())
    conn.commit()
    if trace is not None:
        trace.append({
            "stage": "panel-crawl:scope", "outcome": "hit" if fully_populated else "partial",
            "detail": f"{committee}: {skip}/{total if total is not None else '?'} devices populated"
                       f"{' (complete)' if fully_populated else ' (will resume later)'}",
            "elapsedMs": None,
        })


async def _crawl_one_pdf(client: httpx.AsyncClient, conn, k_number: str, sem: asyncio.Semaphore) -> bool:
    """Returns whether a real PDF was actually fetched (not whether a Measurand was found in it —
    plenty of legitimately-fetched decision summaries have no Measurand section at all, that's
    not a failure). Used only to make the trace honestly distinguish "crawled N, M actually
    succeeded" from a blanket "done" — confirmed live this matters: a 15-for-15 fetch failure
    (accessdata.fda.gov rate-limiting the caller's own IP after enough rapid requests) would
    otherwise have reported the exact same "hit" outcome as 15 real successes.
    """
    async with sem:
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            pdf_bytes, source_url = await pdf_extract.fetch_decision_pdf(client, k_number)
        except pdf_extract.PdfFetchError as e:
            db.upsert_pdf_text(conn, k_number, fetched_at, None, None, None, None, str(e))
            conn.commit()
            return False
        try:
            extracted = pdf_extract.extract_pdf(pdf_bytes)
        except Exception as e:  # malformed/unparseable PDF — record and move on
            db.upsert_pdf_text(conn, k_number, fetched_at, source_url, None, None, None, f"parse error: {e}")
            conn.commit()
            return False
        db.upsert_pdf_text(
            conn, k_number, fetched_at, source_url, extracted.full_text,
            extracted.measurand_label, extracted.measurand_value, None,
        )
        db.insert_predicates(conn, k_number, extracted.predicates)
        # Committed here, per PDF, not once after every PDF in the batch — confirmed live this is
        # load-bearing: a single commit after asyncio.gather() kept this function's write
        # transaction open across the ENTIRE batch's worth of network fetches (up to
        # MAX_NEW_PDF_CRAWLS_PER_SEARCH), comfortably exceeding the 5s busy_timeout
        # indexer/db.py's connect() relies on — a concurrent search's own write (e.g.
        # db.mark_searched) raised "database is locked" as a result. No coroutine can interleave
        # between these writes and this commit (no `await` in between), so this is still atomic
        # per PDF despite running inside asyncio.gather's concurrency.
        conn.commit()
        return True


async def crawl_panel_candidates_incremental(client: httpx.AsyncClient, conn, committees: list[str],
                                              api_key: str | None = None,
                                              trace: TraceSink | None = None) -> int:
    """Called from indexer/lookup.py only when a term's own confirmed matches already identify
    which committee(s) to look in AND the pure-local panel-candidate check (db.find_panel_
    candidates) already came back empty — never on a cache hit, and never guessing a committee
    with no signal for it. Returns how many new PDFs were actually crawled this call (0 means
    either everything panel-shaped in scope is already crawled, this committee has nothing
    matching the panel-naming heuristic, or a transient openFDA failure interrupted device-list
    discovery — all three legitimate degraded-but-safe outcomes, never an exception the caller
    has to handle: this is an optional enrichment on top of an already-complete search, the same
    "never break the real result over this" posture propagate_predicate_matches and
    db.find_panel_candidates already have. PDF-fetch failures are already caught per-device inside
    _crawl_one_pdf; this specifically guards the device-list pagination step, which calls
    openfda.fetch_with_retry directly and — confirmed live — does raise OpenFdaError on exhausted
    retries rather than returning an error value the way run_query's own callers get to check.
    """
    if not committees:
        return 0
    try:
        for committee in committees:
            await ensure_committee_devices_populated(client, conn, committee, api_key, trace=trace)
    except OpenFdaError as e:
        if trace is not None:
            trace.append({"stage": "panel-crawl:scope", "outcome": "error", "detail": str(e), "elapsedMs": None})
        return 0

    candidates = db.find_panel_likely_uncrawled(conn, committees, limit=MAX_NEW_PDF_CRAWLS_PER_SEARCH)
    if not candidates:
        if trace is not None:
            trace.append({"stage": "panel-crawl:pdfs", "outcome": "skipped",
                           "detail": "no not-yet-crawled panel-shaped devices in scope", "elapsedMs": None})
        return 0

    t0 = asyncio.get_event_loop().time()
    sem = asyncio.Semaphore(PDF_FETCH_CONCURRENCY)
    # Each _crawl_one_pdf call commits its own writes as it finishes (see its own comment) —
    # nothing left to commit out here.
    results = await asyncio.gather(*(_crawl_one_pdf(client, conn, c["k_number"], sem) for c in candidates))
    succeeded = sum(1 for ok in results if ok)
    if trace is not None:
        elapsed_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
        trace.append({
            "stage": "panel-crawl:pdfs", "outcome": "hit" if succeeded else "error",
            "detail": f"attempted {len(candidates)} panel-shaped device PDF(s), {succeeded} fetched "
                      f"successfully: {', '.join(c['k_number'] for c in candidates)}",
            "elapsedMs": elapsed_ms,
        })
    return len(candidates)
