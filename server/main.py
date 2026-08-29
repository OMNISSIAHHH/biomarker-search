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
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from indexer import crawl as crawl_module
from indexer.db import DB_PATH, app_base_dir, connect
from indexer.ldt_crosscheck import crosscheck_ldt_candidates
from indexer.lookup import compute_and_cache_result, resolve_and_cache_expansion, try_cached_result
from indexer.matching import expansion_key
from indexer.scope import ADVISORY_COMMITTEES
from indexer.trace import TraceSink

# Loads the .env next to the running app (the exe's own folder when frozen, the repo root
# otherwise — see app_base_dir) rather than relying on the current working directory, which a
# double-clicked exe can't be relied on to set correctly. A no-op if no .env is present there;
# real env vars set another way still work fine without one.
load_dotenv(app_base_dir() / ".env")

app = FastAPI(title="Biomarker Search Local Index")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local-only tool served from file:// or a local static server
    allow_methods=["GET", "POST"],  # POST needed for /crawl/start and /crawl/cancel below
    allow_headers=["*"],
)

AI_CONFIG = {
    "umls_api_key": os.environ.get("UMLS_API_KEY"),
    "tavily_api_key": os.environ.get("TAVILY_API_KEY"),
    "local_llm_url": os.environ.get("LOCAL_LLM_URL"),
    "local_llm_model": os.environ.get("LOCAL_LLM_MODEL"),
}
OPENFDA_API_KEY = os.environ.get("OPENFDA_API_KEY")


# Confirmed live: a UMLS key pasted into the browser's own Settings panel had no effect at all
# whenever the local index server was configured (the default workflow, not a fallback) — every
# call goes through this process, which only ever looked at its own UMLS_API_KEY env var. The
# browser key is only used by the pure-client-side fallback pipeline, which the local-index path
# short-circuits before ever reaching it, so the two settings looked interchangeable but weren't.
# Each endpoint below now accepts an optional umls_api_key query param (sent by the browser's
# Settings key, when set) and prefers it over the .env value for that one request — same
# per-request-overrides-env precedence api_key already has for OPENFDA_API_KEY just above.
def _ai_config_for_request(umls_api_key: str | None) -> dict:
    return {**AI_CONFIG, "umls_api_key": umls_api_key or AI_CONFIG["umls_api_key"]}


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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# Registered BEFORE the plain /biomarker/{term} route below, deliberately — both use a `:path`
# converter so `term` itself can contain a literal "/" (see its own comment), and Starlette tries
# routes in registration order. If the plain route (no fixed suffix to anchor against) were tried
# first, its greedy `.*` would swallow a trailing "/stream" as part of `term` for every streaming
# request, matching there instead and never reaching this one at all — confirmed live, this exact
# thing happened before this route was moved above it. Regex backtracking still correctly strips
# the literal "/stream" suffix here and leaves everything before it as `term`, including any "/"
# inside the term itself.
@app.get("/biomarker/{term:path}/stream")
async def biomarker_stream(term: str, api_key: str | None = None, umls_api_key: str | None = None,
                            refresh: bool = False):
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
                        conn, client, term, _ai_config_for_request(umls_api_key), api_key or OPENFDA_API_KEY,
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


@app.get("/biomarker/{term:path}")
async def biomarker(term: str, api_key: str | None = None, umls_api_key: str | None = None,
                     refresh: bool = False):
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
                conn, client, term, _ai_config_for_request(umls_api_key),
                api_key or OPENFDA_API_KEY, force_refresh=refresh
            )
    finally:
        conn.close()


@app.get("/expansion/{term:path}")
async def expansion(term: str, umls_api_key: str | None = None, refresh: bool = False):
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
                conn, client, term, key, _ai_config_for_request(umls_api_key),
                force_refresh=refresh, trace=trace,
            )
        conn.commit()
        return {"term": term, "expansion": resolved_expansion, "source": source, "trace": trace}
    finally:
        conn.close()


class LdtCandidateIn(BaseModel):
    id: int
    name: str


class LdtCrosscheckRequest(BaseModel):
    term: str
    candidates: list[LdtCandidateIn]


@app.post("/ldt-crosscheck")
async def ldt_crosscheck(body: LdtCrosscheckRequest):
    """AI cross-check for LDT search results already fetched and text-matched by the browser
    across whichever sources it searched (NY State, ARUP, LabCorp, Quest) — see
    indexer/ldt_crosscheck.py for why this exists and how it's prompted. Uses the same local LLM
    already configured for the FDA-side AI-suggested expansion tier (LOCAL_LLM_URL/
    LOCAL_LLM_MODEL in .env); returns {} (every candidate left unconfirmed) if that isn't set up,
    same graceful-degradation posture as every other optional AI tier in this tool.
    """
    trace: list[dict] = []
    async with httpx.AsyncClient() as client:
        results = await crosscheck_ldt_candidates(
            client, body.term, [c.model_dump() for c in body.candidates],
            AI_CONFIG.get("local_llm_url"), AI_CONFIG.get("local_llm_model"), trace=trace,
        )
    return {"results": {str(k): v for k, v in results.items()}, "trace": trace}


class CrawlState:
    """Process-lifetime singleton tracking the one predicate crawl this server can run at a
    time. Not persisted to the DB — acceptable since this server is a single long-running local
    process (the packaged exe or `uvicorn --reload`), not a multi-instance deployment; a restart
    losing the in-memory event log is fine because GET /crawl/status also reads real row counts
    from the DB, so "no events remembered" is never confused with "never crawled."
    """

    def __init__(self) -> None:
        self.status = "idle"  # "idle" | "running" | "done" | "error" | "cancelled"
        self.task: asyncio.Task | None = None
        self.events: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []
        self.last_started_at: str | None = None
        self.last_finished_at: str | None = None
        self.last_error: str | None = None

    def broadcast(self, entry: dict) -> None:
        # Accumulate (so a stream that attaches later can replay everything that already
        # happened) and fan out to every currently-attached live listener.
        self.events.append(entry)
        for q in self.subscribers:
            q.put_nowait(entry)


_crawl_state = CrawlState()


@app.post("/crawl/start")
async def crawl_start(committees: str | None = None, api_key: str | None = None):
    """Kicks off indexer/crawl.py's device+PDF crawl as a background task and returns
    immediately — this can take hours for the full scope, so it's never awaited inline in a
    request. Progress streams live via GET /crawl/stream; GET /crawl/status gives a cheap
    snapshot. 409s rather than silently no-op-ing if one is already running: two crawls writing
    to the same index.sqlite3 at once adds no value and only adds write contention.
    """
    if _crawl_state.status == "running":
        return JSONResponse({"error": "A crawl is already running."}, status_code=409)

    committee_list = [c.strip() for c in committees.split(",") if c.strip()] if committees else ADVISORY_COMMITTEES
    _crawl_state.status = "running"
    _crawl_state.events = []
    _crawl_state.last_started_at = datetime.now(timezone.utc).isoformat()
    _crawl_state.last_error = None

    sink = TraceSink(on_entry=_crawl_state.broadcast)

    async def worker() -> None:
        try:
            await crawl_module.run(committee_list, api_key or OPENFDA_API_KEY, sink=sink)
            _crawl_state.status = "done"
        except asyncio.CancelledError:
            _crawl_state.status = "cancelled"
            sink.append({"type": "cancelled"})
            raise
        except Exception as e:  # noqa: BLE001 — reported via status/events, not raised further
            _crawl_state.status = "error"
            _crawl_state.last_error = str(e)
        finally:
            _crawl_state.last_finished_at = datetime.now(timezone.utc).isoformat()

    _crawl_state.task = asyncio.create_task(worker())
    return {"status": "started", "committees": committee_list}


@app.get("/crawl/stream")
async def crawl_stream():
    """SSE stream of crawl progress. Subscribing (before draining the replay snapshot, so
    nothing broadcast in that instant is missed) then replaying the cumulative event log so far
    is what lets a browser tab that opens this *after* a crawl already started — or reconnects
    after a reload — immediately see the full history instead of an empty log that only fills in
    from that point forward.
    """
    async def event_source():
        queue: asyncio.Queue = asyncio.Queue()
        _crawl_state.subscribers.append(queue)
        for entry in list(_crawl_state.events):
            queue.put_nowait(entry)
        try:
            while True:
                entry = await queue.get()
                yield _sse(entry)
                if entry.get("type") in ("done", "error", "cancelled"):
                    break
        finally:
            _crawl_state.subscribers.remove(queue)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/crawl/cancel")
async def crawl_cancel():
    if _crawl_state.status != "running" or _crawl_state.task is None:
        return JSONResponse({"error": "No crawl is running."}, status_code=409)
    _crawl_state.task.cancel()
    return {"status": "cancelling"}


@app.get("/crawl/status")
def crawl_status():
    conn = get_conn()
    try:
        device_count = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
        pdf_count = conn.execute("SELECT COUNT(*) c FROM pdf_text").fetchone()["c"]
    finally:
        conn.close()
    return {
        "status": _crawl_state.status,
        "last_started_at": _crawl_state.last_started_at,
        "last_finished_at": _crawl_state.last_finished_at,
        "last_error": _crawl_state.last_error,
        "devices_indexed": device_count,
        "pdfs_fetched": pdf_count,
    }
