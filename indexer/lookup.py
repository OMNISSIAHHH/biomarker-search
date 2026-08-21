"""The on-demand, cached per-term biomarker lookup pipeline — replaces what used to be a batch
crawl over dictionary.json's fixed key list (crawl_confirmed_matches + crawl_gudid_matches +
the per-key predicate-propagation loop). There is no file anywhere enumerating "which biomarkers
this tool knows about": whatever term is asked for gets its expansion resolved by AI, is run
through the tiered match pipeline, and is cached — so a repeat search for the same term is a
pure local read, while a first-time search for any term (whether one of hundreds pasted into the
browser tool at once, or typed one at a time) works immediately, no pre-crawl required.

Only the predicate-chain ("inferred via predicate") tier depends on the separate, biomarker-
agnostic scope+PDF crawl (indexer/crawl.py) having already been run — if it hasn't,
propagate_predicate_matches simply finds nothing yet (harmless no-op), same degraded-but-safe
posture the confirmed/GUDID tiers already have when the AI itself has nothing to offer.
"""
import json
from datetime import datetime, timezone

from indexer import ai_expansion, db, gudid
from indexer.matching import expansion_key, fetch_biomarker_matches
from indexer.openfda import DEVICE_510K, run_query
from indexer.predicate_graph import propagate_predicate_matches


def _record_from_row(row) -> dict:
    return json.loads(row["raw_json"])


def read_biomarker_result(conn, key: str, term: str, expansion: dict | None) -> dict:
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
    gudid_rows = conn.execute(
        """SELECT d.raw_json
           FROM biomarker_matches bm JOIN devices d ON d.k_number = bm.k_number
           WHERE bm.biomarker_key = ? AND bm.match_mode = 'gudid'""",
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
        # Plain record objects, not wrapped like inferredMatches — matches the shape the browser
        # tool's own gudidMatches already uses (buildRecordRows expects raw records).
        "gudidMatches": [_record_from_row(r) for r in gudid_rows],
    }


#  Only the 'expansion' match_mode (matching.py's tier tag for "nothing else matched, only the
# resolved name/synonyms did") gets relabeled — every other tier (exact/broad/antigen-only/
# fused-anti/wordform) never touches an expansion at all, so its tag already accurately
# describes how the match was found.
EXPANSION_SOURCE_MATCH_MODE = {"local-llm": "ai-suggested", "umls": "umls"}


async def _resolve_and_cache_expansion(conn, client, term: str, key: str, ai_config: dict,
                                        force_refresh: bool) -> tuple[dict | None, str]:
    if not force_refresh:
        cached = db.get_expansion_cache_entry(conn, key)
        if cached is not None:
            return cached  # (expansion, source) — including (None, "none") if already-tried-and-failed

    expansion, source = await ai_expansion.resolve_expansion(
        client, term,
        ai_config.get("local_llm_url"), ai_config.get("local_llm_model"), ai_config.get("umls_api_key"),
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
    return read_biomarker_result(conn, key, term, expansion)


async def compute_and_cache_result(conn, client, term: str, ai_config: dict,
                                    api_key: str | None = None, force_refresh: bool = False) -> dict:
    """The network-needing path: resolve (or re-resolve) the term's expansion, run the tiered
    match + GUDID + predicate-propagation pipeline, cache everything, and return the result.
    """
    key = expansion_key(term)
    expansion, source = await _resolve_and_cache_expansion(conn, client, term, key, ai_config, force_refresh)

    db.clear_matches_for_biomarker(conn, key)
    result = await fetch_biomarker_matches(client, DEVICE_510K, term, expansion, api_key)
    match_mode = result["match_mode"]
    if match_mode == "expansion":
        match_mode = EXPANSION_SOURCE_MATCH_MODE.get(source, match_mode)
    for r in result["records"]:
        db.upsert_device(conn, r, source="510k")
        db.insert_match(conn, r["k_number"], key, match_mode, "confirmed")

    found = await gudid.fetch_gudid_k_numbers(client, expansion, api_key)
    if found:
        already = {r["k_number"] for r in result["records"]}
        new_k_numbers = [k for k in found if k not in already]
        if new_k_numbers:
            k_expr = "(" + " OR ".join(f'k_number:"{k}"' for k in new_k_numbers) + ")"
            gudid_result = await run_query(client, DEVICE_510K, k_expr, api_key)
            for r in gudid_result["records"]:
                db.upsert_device(conn, r, source="510k")
                db.insert_match(conn, r["k_number"], key, "gudid", "inferred")

    propagate_predicate_matches(conn, key)  # local join over already-crawled predicates/devices,
                                             # no network call — safe to run synchronously here
    db.mark_searched(conn, key, datetime.now(timezone.utc).isoformat())
    conn.commit()

    return read_biomarker_result(conn, key, term, expansion)
