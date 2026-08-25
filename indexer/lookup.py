"""The on-demand, cached per-term biomarker lookup pipeline — replaces what used to be a batch
crawl over dictionary.json's fixed key list (crawl_confirmed_matches + the per-key predicate-
propagation loop). There is no file anywhere enumerating "which biomarkers this tool knows
about": whatever term is asked for gets its expansion resolved via UMLS or, failing that, a
Tavily-search-grounded AI crosscheck (see indexer/ai_expansion.py), is run through the tiered
match pipeline, and is cached — so a repeat search for the same term is a pure local read, while
a first-time search for any term (whether one of hundreds pasted into the browser tool at once,
or typed one at a time) works immediately, no pre-crawl required.

Only the predicate-chain ("inferred via predicate") tier depends on the separate, biomarker-
agnostic scope+PDF crawl (indexer/crawl.py) having already been run — if it hasn't,
propagate_predicate_matches simply finds nothing yet (harmless no-op), same degraded-but-safe
posture the confirmed tier already has when neither expansion source has anything to offer.

510(k) only — this tool doesn't cross-check against GUDID/UDI device-registration data.
"""
import json
from datetime import datetime, timezone
from typing import Callable

from indexer import ai_expansion, db
from indexer.matching import expansion_key, fetch_biomarker_matches
from indexer.openfda import DEVICE_510K
from indexer.predicate_graph import propagate_predicate_matches
from indexer.trace import TraceSink


def _record_from_row(row) -> dict:
    return json.loads(row["raw_json"])


def read_biomarker_result(conn, key: str, term: str, expansion: dict | None,
                           trace: list[dict] | None = None) -> dict:
    """Pure local read of whatever's already in the index for this key — no network calls."""
    confirmed_rows = conn.execute(
        """SELECT bm.match_mode, d.raw_json
           FROM biomarker_matches bm JOIN devices d ON d.k_number = bm.k_number
           WHERE bm.biomarker_key = ? AND bm.confidence = 'confirmed'""",
        (key,),
    ).fetchall()
    predicate_rows = conn.execute(
        """SELECT bm.via_k_number, d.raw_json
           FROM biomarker_matches bm JOIN devices d ON d.k_number = bm.k_number
           WHERE bm.biomarker_key = ? AND bm.match_mode = 'predicate'""",
        (key,),
    ).fetchall()

    records = [_record_from_row(r) for r in confirmed_rows]
    match_mode = confirmed_rows[0]["match_mode"] if confirmed_rows else "exact"

    return {
        "term": term,
        "total": len(records),
        "records": records,
        "matchMode": match_mode,
        "expansion": expansion,
        "panelCandidates": [],
        "inferredMatches": [
            {"device": _record_from_row(r), "viaKNumber": r["via_k_number"], "reason": "predicate"}
            for r in predicate_rows
        ],
        "trace": trace or [],
    }


EXPANSION_SOURCE_MATCH_MODE = {"umls": "umls", "search-ai": "ai-suggested"}


async def resolve_and_cache_expansion(conn, client, term: str, key: str, ai_config: dict,
                                       force_refresh: bool,
                                       trace: list[dict] | None = None) -> tuple[dict | None, str]:
    if not force_refresh:
        cached = db.get_expansion_cache_entry(conn, key)
        if cached is not None:
            expansion, source = cached
            if trace is not None:
                trace.append({"stage": "expansion:cache", "outcome": "hit",
                               "detail": f"cached, source={source}", "elapsedMs": 0})
            return expansion, source  # (expansion, source) — including (None, "none") if already-tried-and-failed

    expansion, source = await ai_expansion.resolve_expansion(
        client, term, ai_config.get("umls_api_key"),
        ai_config.get("tavily_api_key"), ai_config.get("local_llm_url"), ai_config.get("local_llm_model"),
        trace=trace,
    )
    db.upsert_expansion_cache(conn, key, expansion, source, datetime.now(timezone.utc).isoformat())
    return expansion, source


def try_cached_result(conn, term: str) -> dict | None:
    """Pure local check, no client/network involved — lets the caller (server/main.py) avoid
    constructing an httpx.AsyncClient at all for a cache hit, which matters in practice: on some
    machines just instantiating one costs real wall-clock time (TLS/proxy setup), which would
    otherwise silently defeat the whole point of caching for a repeat search.
    """
    key = expansion_key(term)
    if not db.already_searched(conn, key):
        return None
    cached = db.get_expansion_cache_entry(conn, key)
    expansion = cached[0] if cached else None
    # No live tiers re-run for a cache hit, so there's no fresh trace to show — a single honest
    # marker beats either an empty array or (worse) silently reusing a stale trace from whenever
    # this term was last actually computed.
    trace = [{"stage": "cache", "outcome": "hit",
              "detail": "Loaded from the local index — already resolved by an earlier search",
              "elapsedMs": 0}]
    return read_biomarker_result(conn, key, term, expansion, trace)


async def compute_and_cache_result(conn, client, term: str, ai_config: dict,
                                    api_key: str | None = None, force_refresh: bool = False,
                                    on_trace_entry: Callable[[dict], None] | None = None) -> dict:
    """The network-needing path: resolve (or re-resolve) the term's expansion, run the tiered
    match + predicate-propagation pipeline, cache everything, and return the result.

    `on_trace_entry`, if given, is called the instant each trace entry is recorded (not just once
    everything finishes) — this is what lets server/main.py's GET /biomarker/{term}/stream stream
    each stage live over SSE as it actually happens, rather than only after the whole pipeline
    (including any real Tavily/Ollama round-trip) completes.
    """
    key = expansion_key(term)
    trace = TraceSink(on_trace_entry)
    expansion, source = await resolve_and_cache_expansion(
        conn, client, term, key, ai_config, force_refresh, trace=trace,
    )

    db.clear_matches_for_biomarker(conn, key)
    result = await fetch_biomarker_matches(client, DEVICE_510K, term, expansion, api_key, trace=trace)
    # matching.py's 'expansion' tier tag means "nothing else matched, only the resolved name/
    # synonyms did" — relabeled per the source that actually resolved it, so the tag correctly
    # conveys whether this was an unverified database lookup ('umls') or a search-grounded AI
    # extraction ('search-ai' -> 'ai-suggested', kept more cautious since it's generated, not
    # looked up). Every other tier already describes itself accurately.
    if result["match_mode"] == "expansion":
        match_mode = EXPANSION_SOURCE_MATCH_MODE.get(source, "umls")
    else:
        match_mode = result["match_mode"]
    for r in result["records"]:
        db.upsert_device(conn, r, source="510k")
        db.insert_match(conn, r["k_number"], key, match_mode, "confirmed")

    # local join over already-crawled predicates/devices, no network call — safe to run
    # synchronously here
    propagate_predicate_matches(conn, key, trace=trace)
    db.mark_searched(conn, key, datetime.now(timezone.utc).isoformat())
    conn.commit()

    return read_biomarker_result(conn, key, term, expansion, trace.entries)
