"""Local API server over the pre-built SQLite index (see indexer/). Serves
/biomarker/{term} in a shape close to what fetchBiomarker() already returns in
FDA510kBiomarkerSearch.html, plus inferredMatches (predicate-chain/panel-candidate)
and gudidMatches, precomputed by the indexer rather than fetched live, so the
frontend's change is additive rather than a rewrite. Run from the repo root:
`uvicorn server.main:app --reload`.

indexer/crawl.py only ever loops over dictionary.json's own keys, so a term outside
that list has zero rows in biomarker_matches not because it was searched and came up
empty, but because it was never searched at all — trusting that as a genuine "no
matches" would silently turn every non-dictionary biomarker into a false negative the
moment someone sets a local index URL (this tool's default workflow). So /biomarker
falls back to a live tiered query (indexer.matching.fetch_biomarker_matches, the same
logic the crawl itself uses, plus a live GUDID cross-check) for any term whose key
isn't already a dictionary entry, instead of answering from the index for it.
"""
import json
import sqlite3

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from indexer import gudid
from indexer.crawl import load_dictionary
from indexer.db import DB_PATH
from indexer.matching import expansion_key, fetch_biomarker_matches
from indexer.openfda import DEVICE_510K, run_query

app = FastAPI(title="Biomarker Search Local Index")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local-only tool served from file:// or a local static server
    allow_methods=["GET"],
    allow_headers=["*"],
)

DICTIONARY = load_dictionary()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def record_from_row(row: sqlite3.Row) -> dict:
    return json.loads(row["raw_json"])


async def _fetch_live(term: str, api_key: str | None) -> dict:
    """Live fallback for a term the crawl never indexed: same tiered text-match logic as
    the offline crawl, plus a live GUDID cross-check. No predicate-chain inference here —
    that needs the full PDF crawl (steps 3-5 in indexer/crawl.py), which isn't something a
    single on-the-fly query can reasonably reproduce.
    """
    async with httpx.AsyncClient() as client:
        result = await fetch_biomarker_matches(client, DEVICE_510K, term, DICTIONARY, api_key)

        gudid_records: list[dict] = []
        found = await gudid.fetch_gudid_k_numbers(client, term, result.get("expansion"), api_key)
        if found:
            already = {r["k_number"] for r in result["records"]}
            new_k_numbers = [k for k in found if k not in already]
            if new_k_numbers:
                k_expr = "(" + " OR ".join(f'k_number:"{k}"' for k in new_k_numbers) + ")"
                gudid_result = await run_query(client, DEVICE_510K, k_expr, api_key)
                gudid_records = gudid_result["records"]

    return {
        "term": term,
        "total": result["total"],
        "records": result["records"],
        "matchMode": result["match_mode"],
        "expansion": result.get("expansion"),
        "panelCandidates": result.get("panel_candidates", []),
        "inferredMatches": [],
        "gudidMatches": gudid_records,
    }


@app.get("/health")
def health():
    return {"status": "ok" if DB_PATH.exists() else "no-index", "db_path": str(DB_PATH)}


@app.get("/biomarker/{term}")
async def biomarker(term: str, api_key: str | None = None):
    if not DB_PATH.exists():
        return {"error": "Index not built yet. Run `python -m indexer.crawl` first."}

    key = expansion_key(term)

    if key not in DICTIONARY:
        return await _fetch_live(term, api_key)

    expansion = DICTIONARY.get(key)

    conn = get_conn()
    try:
        confirmed_rows = conn.execute(
            """SELECT bm.match_mode, d.raw_json
               FROM biomarker_matches bm JOIN devices d ON d.k_number = bm.k_number
               WHERE bm.biomarker_key = ? AND bm.confidence = 'confirmed'""",
            (key,),
        ).fetchall()
        panel_rows = conn.execute(
            """SELECT d.raw_json
               FROM biomarker_matches bm JOIN devices d ON d.k_number = bm.k_number
               WHERE bm.biomarker_key = ? AND bm.match_mode = 'panel-candidate'""",
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
    finally:
        conn.close()

    records = [record_from_row(r) for r in confirmed_rows]
    match_mode = confirmed_rows[0]["match_mode"] if confirmed_rows else "exact"

    return {
        "term": term,
        "total": len(records),
        "records": records,
        "matchMode": match_mode,
        "expansion": expansion,
        "panelCandidates": [record_from_row(r) for r in panel_rows],
        "inferredMatches": [
            {"device": record_from_row(r), "viaKNumber": r["via_k_number"], "reason": "predicate"}
            for r in predicate_rows
        ],
        # Plain record objects, not wrapped like inferredMatches — matches the shape the live
        # JS tool's own gudidMatches already uses (buildRecordRows expects raw records).
        "gudidMatches": [record_from_row(r) for r in gudid_rows],
    }
