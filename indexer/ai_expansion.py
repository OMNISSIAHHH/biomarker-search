"""Python port of the browser tool's local-LLM/UMLS abbreviation lookup
(lookupLocalLlmExpansion/lookupUmlsExpansion in FDA510kBiomarkerSearch.html), promoted here from
a last-resort fallback (used only for terms missing a dictionary entry) to the indexer's only
expansion mechanism, now that dictionary.json is gone. Synonym count widened from "up to 3"
(a last-resort posture) to "up to 6", since this is now the primary source of alternate search
phrasing for every term, not an occasional bonus tier.

Same trust posture as the browser tool: an expansion resolved this way is unverified — nobody
has manually confirmed it against real openFDA data the way every old ABBREVIATION_EXPANSIONS
entry was — and a local LLM in particular can generate a plausible-sounding wrong answer with
the same confidence as a right one. Local LLM is tried first when configured (the engine a user
chose specifically to skip UMLS's licensing wait); UMLS is the fallback.
"""
import re

import httpx

UMLS_SEARCH_BASE = "https://uts-ws.nlm.nih.gov/rest/search/current"
UNKNOWN_RE = re.compile(r"^UNKNOWN\b", re.IGNORECASE)
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)

# Hybrid-reasoning models (Qwen3, DeepSeek-R1, QwQ, etc.) generate a long internal chain-of-
# thought before their final answer by default — confirmed directly against qwen3:4b, which
# took well over 20s just to decide how to say "hello" in one word. That reasoning phase, not
# model/network failure, is what was silently timing out and getting cached as "AI found
# nothing" here. `think: False` asks Ollama to skip it for models that support the option; the
# THINK_BLOCK_RE strip below is a defensive fallback for any model/version that emits a
# <think>...</think> block in `response` regardless. Timeout is raised well past the old 20s to
# leave real margin for slow CPU inference even with reasoning disabled.
LOCAL_LLM_TIMEOUT = 90.0


async def lookup_umls_expansion(client: httpx.AsyncClient, term: str,
                                 umls_api_key: str | None) -> dict | None:
    if not umls_api_key:
        return None
    for search_type in ("exact", "words"):
        try:
            params = {"string": term, "apiKey": umls_api_key, "searchType": search_type, "pageSize": "5"}
            res = await client.get(UMLS_SEARCH_BASE, params=params, timeout=20.0)
            if res.status_code != 200:
                continue  # bad/unapproved key, rate limit, etc. — treat as no match, not a hard error
            body = res.json()
            results = (body.get("result") or {}).get("results") or []
            hit = next((r for r in results if r.get("ui") and r["ui"] != "NONE" and r.get("name")), None)
            if hit:
                return {"full": hit["name"]}
        except httpx.HTTPError:
            continue  # fall through to the next searchType, then to the caller's own handling
    return None


def local_llm_prompt(term: str) -> str:
    return (
        "You are looking up laboratory/medical terminology as used in FDA medical device documentation.\n"
        f'For the abbreviation or shorthand term "{term}", respond with ONLY the following and nothing '
        "else — no explanation, no extra commentary:\n"
        "Line 1: its full spelled-out scientific/medical name\n"
        "Line 2 (optional, only if you know one or more): up to 6 common alternate names or synonyms, "
        "comma-separated\n"
        "If you do not know this specific term with real confidence, respond with exactly this and "
        "nothing else: UNKNOWN"
    )


async def lookup_local_llm_expansion(client: httpx.AsyncClient, term: str, base_url: str | None,
                                      model: str | None) -> dict | None:
    if not base_url or not model:
        return None
    try:
        res = await client.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": local_llm_prompt(term), "stream": False, "think": False},
            timeout=LOCAL_LLM_TIMEOUT,
        )
        if res.status_code != 200:
            return None
        data = res.json()
        text = THINK_BLOCK_RE.sub("", data.get("response") or "").strip()
        if not text or UNKNOWN_RE.match(text):
            return None
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            return None
        full = lines[0]
        if not full or len(full) > 200:  # sanity bound — a real name isn't a paragraph
            return None
        synonyms = [s.strip() for s in lines[1].split(",") if s.strip()] if len(lines) > 1 else []
        return {"full": full, "search": "/".join([full, *synonyms])} if synonyms else {"full": full}
    except httpx.HTTPError:
        return None  # model not pulled, server down, timeout — never fail the whole search over this


async def resolve_expansion(client: httpx.AsyncClient, term: str, local_llm_url: str | None,
                             local_llm_model: str | None, umls_api_key: str | None) -> tuple[dict | None, str]:
    """Returns (expansion, source) where source is 'local-llm' | 'umls' | 'none' — the caller
    persists source alongside the expansion in expansion_cache so a genuinely-unresolvable term
    doesn't get re-asked of the AI on every single search.
    """
    if local_llm_url and local_llm_model:
        expansion = await lookup_local_llm_expansion(client, term, local_llm_url, local_llm_model)
        if expansion:
            return expansion, "local-llm"
    if umls_api_key:
        expansion = await lookup_umls_expansion(client, term, umls_api_key)
        if expansion:
            return expansion, "umls"
    return None, "none"
