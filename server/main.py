"""Local API server over index.sqlite3 (see indexer/). Serves /biomarker/{term} in the shape
fetchBiomarker() returns in FDA510kBiomarkerSearch.html.

Every term is resolved on demand and cached — there is no dictionary/biomarker list anywhere.
indexer/lookup.py's compute_and_cache_result does the actual work: a repeat search for an
already-searched term is a pure local SQLite read; a first-time search resolves the term's full
name/synonyms via UMLS, falling back to a Tavily-search-grounded local-LLM crosscheck if UMLS
isn't configured or doesn't know the term (configured below via environment variables, since this
process has no access to the browser's Settings/localStorage), runs the tiered match pipeline,
and caches the result for next time. Only predicate-chain ("inferred via predicate") results
depend on the separate, biomarker-agnostic scope+PDF crawl (`python -m indexer.crawl`) having
already been run — confirmed results work immediately either way.

Run from the repo root: `uvicorn server.main:app --reload`. Configure via the .env file at the
repo root, or plain environment variables — either way: UMLS_API_KEY for UMLS lookup, or
TAVILY_API_KEY + LOCAL_LLM_URL + LOCAL_LLM_MODEL for the Tavily+local-LLM crosscheck fallback
(see indexer/ai_expansion.py for why this is grounded in search results rather than the model's
own recall). Both can be set together — UMLS is tried first, Tavily+local-LLM is the fallback
for whatever UMLS doesn't cover. Without either, searches still work for anything the exact/
broad/antigen-only/fused-anti/wordform tiers can find on their own — just without an alternate
name to fall back on.
"""
import asyncio
import json
import os
import sqlite3

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from indexer.db import DB_PATH, app_base_dir, connect
from indexer.lookup import compute_and_cache_result, resolve_and_cache_expansion, try_cached_result
from indexer.matching import expansion_key

# Loads the .env next to the running app (the exe's own folder when frozen, the repo root
# otherwise — see app_base_dir) rather than relying on the current working directory, which a
# double-clicked exe can't be relied on to set correctly. A no-op if no .env is present there;
# real env vars set another way still work fine without one.
load_dotenv(app_base_dir() / ".env")

app = FastAPI(title="Biomarker Search Local Index")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local-only tool served from file:// or a local static server
    allow_methods=["GET"],
    allow_headers=["*"],
)

AI_CONFIG = {
    "umls_api_key": os.environ.get("UMLS_API_KEY"),
    "tavily_api_key": os.environ.get("TAVILY_API_KEY"),
    "local_llm_url": os.environ.get("LOCAL_LLM_URL"),
    "local_llm_model": os.environ.get("LOCAL_LLM_MODEL"),
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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/biomarker/{term}/stream")
async def biomarker_stream(term: str, api_key: str | None = None, refresh: bool = False):
    """Same result as GET /biomarker/{term}, but delivered as Server-Sent Events: each trace
    entry streams the instant it's actually recorded (including mid-way through a real Tavily
    search or a 10-25s local-LLM call), not just once the whole pipeline finishes — this is what
    lets the browser's search-process log update live instead of appearing all at once after a
    potentially long wait. The frontend's EventSource consumes this via
    fetchFromLocalIndexStreaming() in FDA510kBiomarkerSearch.html.

    Each message is `data: {json}\\n\\n` with one of:
      {"type": "trace", "entry": {...}}   — one stage, as it happens
      {"type": "result", "result": {...}} — the same shape GET /biomarker/{term} returns, once
      {"type": "error", "message": "..."} — the pipeline raised; the stream ends either way
    """
    async def event_source():
        conn = get_conn()
        queue: asyncio.Queue = asyncio.Queue()

        def on_trace_entry(entry: dict) -> None:
            queue.put_nowait({"type": "trace", "entry": entry})

        async def worker() -> None:
            try:
                if not refresh:
                    cached = try_cached_result(conn, term)
                    if cached is not None:
                        for entry in cached["trace"]:
                            queue.put_nowait({"type": "trace", "entry": entry})
                        queue.put_nowait({"type": "result", "result": cached})
                        return
                async with httpx.AsyncClient() as client:
                    result = await compute_and_cache_result(
                        conn, client, term, AI_CONFIG, api_key or OPENFDA_API_KEY,
                        force_refresh=refresh, on_trace_entry=on_trace_entry,
                    )
                queue.put_nowait({"type": "result", "result": result})
            except Exception as e:  # noqa: BLE001 — reported to the client, not raised past SSE
                queue.put_nowait({"type": "error", "message": str(e)})
            finally:
                queue.put_nowait(None)  # sentinel: nothing else is coming

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse(item)
        finally:
            await task
            conn.close()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/expansion/{term}")
async def expansion(term: str, refresh: bool = False):
    """Resolves (or returns the cached) full-name/synonym expansion for a term, without running
    the FDA tier queries or predicate propagation /biomarker/{term} also does — for callers that
    only need the resolved name itself (the LDT search tab, see FDA510kBiomarkerSearch.html's
    fetchExpansionForLdt) and shouldn't pay for openFDA work + cache writes they don't need just
    to read one cached string.
    """
    conn = get_conn()
    try:
        key = expansion_key(term)
        trace: list[dict] = []
        async with httpx.AsyncClient() as client:
            resolved_expansion, source = await resolve_and_cache_expansion(
                conn, client, term, key, AI_CONFIG, force_refresh=refresh, trace=trace,
            )
        conn.commit()
        return {"term": term, "expansion": resolved_expansion, "source": source, "trace": trace}
    finally:
        conn.close()
