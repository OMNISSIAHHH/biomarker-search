"""Local API server over index.sqlite3 (see indexer/). Serves /biomarker/{term} in the shape
fetchBiomarker() returns in FDA510kBiomarkerSearch.html.

Every term is resolved on demand and cached — there is no dictionary/biomarker list anywhere.
indexer/lookup.py's get_biomarker_result does the actual work: a repeat search for an
already-searched term is a pure local SQLite read; a first-time search resolves the term's full
name/synonyms via AI (local LLM or UMLS, configured below via environment variables, since this
process has no access to the browser's Settings/localStorage), runs the tiered match pipeline,
and caches the result for next time. Only predicate-chain ("inferred via predicate") results
depend on the separate, biomarker-agnostic scope+PDF crawl (`python -m indexer.crawl`) having
already been run — confirmed and GUDID results work immediately either way.

Run from the repo root: `uvicorn server.main:app --reload`. Configure the AI engine via
environment variables, e.g.:
  LOCAL_LLM_URL=http://localhost:11434 LOCAL_LLM_MODEL=qwen3:4b uvicorn server.main:app --reload
or UMLS_API_KEY=... uvicorn server.main:app --reload
"""
import os
import sqlite3

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from indexer.db import DB_PATH, connect
from indexer.lookup import compute_and_cache_result, try_cached_result

app = FastAPI(title="Biomarker Search Local Index")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local-only tool served from file:// or a local static server
    allow_methods=["GET"],
    allow_headers=["*"],
)

AI_CONFIG = {
    "local_llm_url": os.environ.get("LOCAL_LLM_URL"),
    "local_llm_model": os.environ.get("LOCAL_LLM_MODEL"),
    "umls_api_key": os.environ.get("UMLS_API_KEY"),
}
OPENFDA_API_KEY = os.environ.get("OPENFDA_API_KEY")


def get_conn() -> sqlite3.Connection:
    # Read-write, not read-only: a cache miss populates the index on the spot rather than only
    # ever reading a pre-built one.
    return connect(DB_PATH)


@app.get("/health")
def health():
    # Always "ok" once this endpoint is reachable at all: /biomarker/{term} no longer requires
    # a pre-built index (it creates index.sqlite3 lazily on first use, per indexer/lookup.py),
    # so a missing file on a fresh setup isn't actually a reason to distrust this server — the
    # old "no-index" status was a leftover from the previous crawl-first design and, left in
    # place, made the browser tool wrongly skip this server on every fresh setup with no prior
    # searches yet.
    return {"status": "ok", "db_path": str(DB_PATH)}


@app.get("/biomarker/{term}")
async def biomarker(term: str, api_key: str | None = None, refresh: bool = False):
    conn = get_conn()
    try:
        # Checked before constructing an httpx.AsyncClient at all — a cache hit should be a
        # pure local read, and on some machines just instantiating a client costs real
        # wall-clock time, which would otherwise quietly defeat the point of caching.
        if not refresh:
            cached = try_cached_result(conn, term)
            if cached is not None:
                return cached
        async with httpx.AsyncClient() as client:
            return await compute_and_cache_result(
                conn, client, term, AI_CONFIG, api_key or OPENFDA_API_KEY, force_refresh=refresh
            )
    finally:
        conn.close()
