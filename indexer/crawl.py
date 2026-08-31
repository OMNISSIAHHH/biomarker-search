"""Refreshes the foundational, biomarker-agnostic device+PDF corpus the predicate-chain tier
depends on. This has nothing to do with any specific biomarker — it crawls every device in the
bounded advisory-committee scope regardless of which biomarkers anyone will ever search for, so
it's run periodically (independent of what's being searched), not per-term.

  1. Populate the full scope device list: every 510k device in ADVISORY_COMMITTEES — this is
     the point of the predicate crawl, to reach devices text search misses entirely.
  2. PDF crawl: fetch + parse (Measurand + predicate table) every scope device not already
     cached. The expensive step; skips anything already in pdf_text from a prior run.

Actual biomarker lookups (confirmed-match tiers, predicate-chain propagation) happen lazily and
per-term through indexer/lookup.py, called by the local server on each /biomarker/{term} request
— there is no dictionary/biomarker list here or anywhere else; whatever's searched gets resolved
(and cached) on the spot. Run this crawl once before searching if you want predicate-chain
("inferred via predicate") results available immediately; confirmed results work without it,
resolved live on first search either way.

Usage: python -m indexer.crawl [--api-key KEY] [--committees IM,CH]
--api-key defaults to OPENFDA_API_KEY from the .env file at the repo root, or the environment,
if set.
"""
import argparse
import asyncio
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

from indexer import db, pdf_extract
from indexer.openfda import DEVICE_510K, fetch_all_in_scope
from indexer.scope import ADVISORY_COMMITTEES
from indexer.trace import TraceSink

load_dotenv()  # loads a .env file in the repo root if present; a no-op otherwise


async def populate_scope_devices(client: httpx.AsyncClient, conn, committees: list[str],
                                  api_key: str | None = None, sink: TraceSink | None = None) -> None:
    """Every 510k device in the bounded advisory-committee scope, not just the ones already
    found by text matching — the predicate graph's whole value is reaching devices that text
    search misses entirely, so it needs the full population to crawl PDFs for, not a subset.
    """
    sink = sink if sink is not None else TraceSink()
    records = await fetch_all_in_scope(client, DEVICE_510K, "advisory_committee", committees, api_key)
    for r in records:
        db.upsert_device(conn, r, source="510k")
    conn.commit()
    sink.append({"type": "scope_done", "total": len(records), "committees": committees})


async def crawl_pdfs_in_scope(client: httpx.AsyncClient, conn, committees: list[str],
                               concurrency: int = 5, sink: TraceSink | None = None) -> None:
    sink = sink if sink is not None else TraceSink()
    placeholders = ",".join("?" * len(committees))
    rows = conn.execute(
        f"SELECT k_number FROM devices WHERE advisory_committee IN ({placeholders}) AND source = '510k'",
        committees,
    ).fetchall()
    to_fetch = [r["k_number"] for r in rows if not db.already_fetched(conn, r["k_number"])]
    sink.append({"type": "pdf_scope", "to_fetch": len(to_fetch), "already_cached": len(rows) - len(to_fetch)})

    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(k_number: str) -> None:
        async with sem:
            fetched_at = datetime.now(timezone.utc).isoformat()
            try:
                pdf_bytes, source_url = await pdf_extract.fetch_decision_pdf(client, k_number)
            except pdf_extract.PdfFetchError as e:
                db.upsert_pdf_text(conn, k_number, fetched_at, None, None, None, None, str(e))
                conn.commit()
                return
            try:
                extracted = pdf_extract.extract_pdf(pdf_bytes)
            except Exception as e:  # malformed/unparseable PDF — record and move on
                db.upsert_pdf_text(conn, k_number, fetched_at, source_url, None, None, None, f"parse error: {e}")
                conn.commit()
                return
            db.upsert_pdf_text(
                conn, k_number, fetched_at, source_url, extracted.full_text,
                extracted.measurand_label, extracted.measurand_value, None,
            )
            db.insert_predicates(conn, k_number, extracted.predicates)
            # Committed here, per device, not once per 50-device batch — confirmed live this is
            # load-bearing: a single commit per batch kept this crawl's write transaction open
            # across up to 50 sequential/concurrent network fetches at a time, comfortably
            # exceeding the 5s busy_timeout indexer/db.py's connect() relies on to let an
            # ordinary search's own write share the database with a running crawl — a concurrent
            # search raised "database is locked" as a result. No coroutine can interleave between
            # these writes and this commit (no `await` in between), so this is still atomic per
            # device despite running inside asyncio.gather's concurrency.
            conn.commit()

    # A cancelled asyncio.Task (see server/main.py's POST /crawl/cancel) unwinds at whatever
    # await this loop is currently sitting on — inside asyncio.gather, that's each fetch_one's
    # semaphore acquire or httpx call. fetch_one now commits its own writes as it finishes, so at
    # most the one PDF in flight at cancellation time is lost, not a whole batch.
    for i in range(0, len(to_fetch), 50):
        batch = to_fetch[i:i + 50]
        await asyncio.gather(*(fetch_one(k) for k in batch))
        sink.append({"type": "pdf_batch", "fetched": min(i + 50, len(to_fetch)), "of": len(to_fetch)})


async def run(committees: list[str], api_key: str | None = None, sink: TraceSink | None = None) -> None:
    sink = sink if sink is not None else TraceSink()
    conn = db.connect()
    try:
        async with httpx.AsyncClient() as client:
            sink.append({"type": "step", "detail": "Step 1/2: populating full scope device list..."})
            await populate_scope_devices(client, conn, committees, api_key, sink=sink)

            sink.append({"type": "step", "detail": "Step 2/2: PDF crawl (Measurand + predicates) for devices in scope..."})
            await crawl_pdfs_in_scope(client, conn, committees, sink=sink)
    except Exception as e:
        sink.append({"type": "error", "message": str(e)})
        raise
    finally:
        conn.close()
    sink.append({"type": "done", "detail": "Done. Biomarker lookups themselves happen on demand via the local "
                                            "server (indexer/lookup.py) — nothing biomarker-specific to run here."})


# CLI progress wording kept byte-for-byte identical to what this script has always printed —
# this is a refactor of *how* progress is reported (through a TraceSink, so server/main.py's
# UI-triggered crawl can stream the same events live over SSE), not a change to CLI behavior.
def _print_progress(entry: dict) -> None:
    t = entry.get("type")
    if t == "step":
        print(entry["detail"])
    elif t == "scope_done":
        print(f"  {entry['total']} devices in scope ({', '.join(entry['committees'])})")
    elif t == "pdf_scope":
        print(f"  {entry['to_fetch']} devices to fetch (of {entry['to_fetch'] + entry['already_cached']} in scope, rest already cached)")
    elif t == "pdf_batch":
        print(f"  fetched {entry['fetched']}/{entry['of']}")
    elif t == "done":
        print(entry["detail"])
    elif t == "error":
        print(f"Crawl failed: {entry['message']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl and index FDA 510(k) data for the biomarker search tool.")
    parser.add_argument(
        "--api-key", default=os.environ.get("OPENFDA_API_KEY"),
        help="openFDA API key (optional, raises rate limits). Defaults to OPENFDA_API_KEY from "
             "the environment or a .env file.",
    )
    parser.add_argument(
        "--committees", default=",".join(ADVISORY_COMMITTEES),
        help=f"Comma-separated advisory committee codes to crawl (default: {','.join(ADVISORY_COMMITTEES)}).",
    )
    args = parser.parse_args()
    committees = [c.strip() for c in args.committees.split(",") if c.strip()]
    sink = TraceSink(on_entry=_print_progress)
    asyncio.run(run(committees, args.api_key, sink=sink))


if __name__ == "__main__":
    main()
