"""Local API server over the pre-built SQLite index (see indexer/). Serves
/biomarker/{term} in a shape close to what fetchBiomarker() already returns in
FDA510kBiomarkerSearch.html, plus inferredMatches (predicate-chain/panel-candidate)
and gudidMatches, precomputed by the indexer rather than fetched live, so the
frontend's change is additive rather than a rewrite. Run from the repo root:
`uvicorn server.main:app --reload`.
"""
import json
import sqlite3

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from indexer.crawl import load_dictionary
from indexer.db import DB_PATH
from indexer.matching import expansion_key

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


@app.get("/health")
def health():
    return {"status": "ok" if DB_PATH.exists() else "no-index", "db_path": str(DB_PATH)}


@app.get("/biomarker/{term}")
def biomarker(term: str):
    if not DB_PATH.exists():
        return {"error": "Index not built yet. Run `python -m indexer.crawl` first."}

    key = expansion_key(term)
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
