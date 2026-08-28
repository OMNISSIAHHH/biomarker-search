"""Resolves a biomarker abbreviation to its full spelled-out name automatically, via two
fallback sources tried in order:

1. UMLS (lookup_umls_expansion) — a real, curated medical terminology database aggregating many
   source vocabularies (SNOMED CT, LOINC, MeSH, etc.). Unverified (nobody has manually confirmed
   the match), but it's a database lookup, not a generated guess.

2. Tavily search + local-LLM crosscheck (lookup_search_ai_expansion) — for whatever UMLS doesn't
   cover (including, right now, the entire wait while a UMLS license is pending approval). A
   plain local-LLM alternative (asking a model to recall the term from its own training) was
   tried and removed earlier: qwen3:4b confidently had no idea "AMA-M2" meant Anti-Mitochondrial
   Antibody, M2 subtype. A plain Wikipedia-lookup alternative was tested live and rejected too —
   it resolves longer/specific abbreviations fine (AChR, AQP4, Dsg1) but returns something
   actively wrong for short/ambiguous ones (AMA -> "Ama", a Japanese/Korean word; AMA-M2 ->
   "Amaterasu"; GADA -> no page at all) — the same "confidently wrong" failure mode.

   This tier is different in kind, not just a repeat: search Tavily for the term first, then ask
   the local model to extract the full name FROM the retrieved search results, not from its own
   memorized recall. That directly targets why the pure-recall approach failed on AMA-M2 — the
   model simply never learned that specific abbreviation — by giving it real, current context to
   read instead of asking it to guess. A grounding-verification guard (below) then checks the
   model's answer actually traces back to the provided snippets, not to its own recall regardless
   of what it was given.

   Still tagged 'ai-suggested', not 'umls' — grounding makes this meaningfully more reliable than
   the old approach, but it's not a curated database lookup, so it keeps the same "verify
   manually" caution the tag already carried.
"""
import re
import time

import httpx

from indexer.matching import STRICT_ANTIBODY_WORDS, anti_requirement_mode, split_expansion_tokens

UMLS_SEARCH_BASE = "https://uts-ws.nlm.nih.gov/rest/search/current"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

UNKNOWN_RE = re.compile(r"^UNKNOWN\b", re.IGNORECASE)
STOPWORDS = {"the", "a", "an", "of", "and", "or", "in", "for", "to", "with", "is", "are"}

# Confirmed live: llama3.2:3b takes the crosscheck prompt's "Line 1: ...", "Line 2: ..." format
# description too literally and echoes the labels themselves into its answer (e.g. responding
# "Line 1: Antimitochondrial Antibody, IgG, M2" instead of just the name) — polluting the
# search with literal tokens like "Line"/"1:" that no real FDA document contains, silently
# breaking the search even though the underlying extraction was actually correct. Stripped
# defensively rather than relied on prompt wording alone, since prompt-following varies enough
# across models that the parsing needs to tolerate it regardless (the whole lesson of this
# project's local-LLM experiments so far).
LINE_PREFIX_RE = re.compile(r"^(?:line\s*\d+\s*[:)]|\d+[.)])\s*", re.IGNORECASE)
# Matches a line-2 placeholder for "no synonyms" so it isn't treated as a literal synonym —
# also confirmed live: "Line 2:  (none specified)" from the same response.
NO_ANSWER_RE = re.compile(r"^\(?\s*(?:none(?:\s+specified)?|n/?a)\s*\)?$", re.IGNORECASE)

# Confirmed live: llama3.2:3b listed "IgG" as a "synonym" for dsDNA — an antibody *class*
# marker, not an alternate name for the analyte. See matching.py's identical BARE_ISOTYPE_RE
# for why a bare isotype word can never safely stand as its own match branch.
BARE_ISOTYPE_RE = re.compile(r"^Ig[AGME][1-4]?$", re.IGNORECASE)

# Confirmed live: UMLS resolved "ama-m2" to "Mitochondria M2 Ab.IgG:ACnc:Pt:Ser:Qn" — a LOINC
# code's own structured "Fully Specified Name" (Component:Property:Time:System:Scale[:Method]),
# one of many source vocabularies UMLS' Metathesaurus aggregates alongside SNOMED CT/MeSH/etc.
# Used verbatim as a search phrase, this obviously never appears anywhere in FDA's plain-English
# device text — an ordinary biomarker name never contains even one colon, let alone several.
# Skipped in favor of the next usable result instead (same UMLS search can return other, cleaner
# vocabulary hits for the same term); falls through to the Tavily/local-LLM tier only if truly
# none of the returned concepts have an ordinary name.
LOINC_CODE_NAME_RE = re.compile(r"^[^:]+(?::[^:]+){2,}$")


def _looks_like_loinc_code_name(name: str) -> bool:
    return bool(LOINC_CODE_NAME_RE.match(name))


def _clean_extracted_line(line: str) -> str:
    return LINE_PREFIX_RE.sub("", line).strip()


def _trace(trace: list[dict] | None, stage: str, outcome: str, detail: str,
           elapsed_ms: int | None = None) -> None:
    """Appends one entry to the caller's trace list, if it wants one — a no-op when trace is
    None, so every existing caller that doesn't care about search-process visibility is
    unaffected. See FDA510kBiomarkerSearch.html's own trace entries for the browser-side
    equivalent (same stage names, used for the "search process" log panel).
    """
    if trace is not None:
        trace.append({"stage": stage, "outcome": outcome, "detail": detail, "elapsedMs": elapsed_ms})

# Hybrid-reasoning models (Qwen3, DeepSeek-R1, QwQ, etc.) generate a long internal chain-of-
# thought before their final answer by default — confirmed directly against qwen3:4b, which took
# well over 20s just to decide how to say "hello" in one word. `think: False` asks Ollama to skip
# it for models that support the option; splitting on "</think>" (below) is a defensive fallback
# for any model/version that still emits one — Ollama's chat template injects the opening tag
# itself before generation starts, so it never appears in `response`, meaning a balanced-pair
# regex silently fails to strip anything. Timeout is raised well past a plain 20s for real margin
# on slow CPU inference even with reasoning disabled.
LOCAL_LLM_TIMEOUT = 90.0


async def lookup_umls_expansion(client: httpx.AsyncClient, term: str, umls_api_key: str | None,
                                 trace: list[dict] | None = None) -> dict | None:
    if not umls_api_key:
        _trace(trace, "expansion:umls", "skipped", "no UMLS key configured")
        return None
    for search_type in ("exact", "words"):
        t0 = time.monotonic()
        try:
            params = {"string": term, "apiKey": umls_api_key, "searchType": search_type, "pageSize": "5"}
            res = await client.get(UMLS_SEARCH_BASE, params=params, timeout=20.0)
            elapsed = int((time.monotonic() - t0) * 1000)
            if res.status_code != 200:
                _trace(trace, "expansion:umls", "error",
                       f"searchType={search_type}: HTTP {res.status_code}", elapsed)
                continue  # bad/unapproved key, rate limit, etc. — treat as no match, not a hard error
            body = res.json()
            results = (body.get("result") or {}).get("results") or []
            usable = [r for r in results if r.get("ui") and r["ui"] != "NONE" and r.get("name")]
            clean = [r for r in usable if not _looks_like_loinc_code_name(r["name"])]
            # UMLS ranks by textual relevance, not clinical category — confirmed live, "Anti-HPV"
            # ranked "Human Papilloma Virus Vaccine" (a Pharmacologic Substance) above "Human
            # papillomavirus antibody" (the actual antibody-assay concept), because both match the
            # search string about equally well. When the term itself signals an antibody test (an
            # explicit "Anti-" prefix or an implied Ig-class suffix — see anti_requirement_mode),
            # prefer a candidate whose own name says so too, same "unambiguous antibody wording"
            # words already trusted elsewhere (matching.py's cross-field antibody clause) — a term
            # with no antibody-worded UMLS concept at all still falls through to the first clean
            # result exactly as before, so this can't regress an already-working lookup.
            hit = None
            if anti_requirement_mode(term) != "none":
                hit = next((r for r in clean if any(w in r["name"].lower() for w in STRICT_ANTIBODY_WORDS)), None)
            if not hit:
                hit = next(iter(clean), None)
            if hit:
                _trace(trace, "expansion:umls", "hit",
                       f"matched via searchType={search_type}: {hit['name']}", elapsed)
                return {"full": hit["name"]}
            skipped_loinc = any(_looks_like_loinc_code_name(r["name"]) for r in usable)
            _trace(trace, "expansion:umls", "miss",
                   f"searchType={search_type}: 0 usable results"
                   + (" (skipped LOINC-coded name(s) with no plain-name alternative)" if skipped_loinc else ""),
                   elapsed)
        except httpx.HTTPError as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            _trace(trace, "expansion:umls", "error", f"searchType={search_type}: {e}", elapsed)
            continue  # fall through to the next searchType, then to the caller's own handling
    return None


async def tavily_search(client: httpx.AsyncClient, term: str, tavily_api_key: str | None,
                         trace: list[dict] | None = None) -> dict | None:
    if not tavily_api_key:
        _trace(trace, "expansion:tavily", "skipped", "no Tavily key configured")
        return None
    t0 = time.monotonic()
    try:
        # Confirmed live: a bare-term search for "GADA" surfaces "Gada (mace)" — an unrelated
        # Hindi/Sanskrit word for a weapon — as its top result; "GADA biomarker full name"
        # returns correctly on-topic results (Glutamate decarboxylase autoantibodies, Type 1
        # diabetes) — "full name" steers toward pages that actually spell out the term, rather
        # than just mentioning "biomarker" in passing. The grounding-verification guard below
        # only checks that the model's answer traces back to whatever got retrieved — it can't
        # fix a search that retrieved the wrong domain's content in the first place, so the
        # domain hint has to go in the query itself.
        res = await client.post(
            TAVILY_SEARCH_URL,
            headers={"Authorization": f"Bearer {tavily_api_key}"},
            json={"query": f"{term} biomarker full name", "search_depth": "basic", "max_results": 5,
                  "include_answer": True},
            timeout=20.0,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        if res.status_code != 200:
            _trace(trace, "expansion:tavily", "error", f"HTTP {res.status_code}", elapsed)
            return None
        data = res.json()
        if not data.get("results") and not data.get("answer"):
            _trace(trace, "expansion:tavily", "miss", "no results or summary answer returned", elapsed)
            return None
        n = len(data.get("results") or [])
        detail = f"{n} result(s) retrieved" + (", plus a summary answer" if data.get("answer") else "")
        _trace(trace, "expansion:tavily", "hit", detail, elapsed)
        return data
    except httpx.HTTPError as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        _trace(trace, "expansion:tavily", "error", str(e), elapsed)
        return None


def crosscheck_prompt(term: str, tavily_response: dict) -> str:
    lines = [
        "You are extracting laboratory/medical terminology from web search results.",
        f'Term to identify: "{term}"',
        "",
        "Search results:",
    ]
    answer = tavily_response.get("answer")
    if answer:
        lines.append(f"Summary: {answer}")
    for r in (tavily_response.get("results") or [])[:4]:
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()[:300]
        if title or content:
            lines.append(f"- {title}: {content}")
    lines += [
        "",
        f'Based ONLY on the search results above, what is "{term}"\'s full spelled-out',
        "scientific/medical name? Reply with exactly two lines and nothing else — no labels, "
        "no explanation, no extra commentary, no words like \"Line 1\" or \"Line 2\":",
        "- First line: the literal expansion of the term itself — what specific molecule, "
        "protein, or antigen it targets, spelled out (e.g. an abbreviated protein name spelled "
        "out in full). This is what a manufacturer's own test-kit paperwork actually calls the "
        "thing being measured, NOT a disease name, syndrome, or historical eponym the antibody "
        "is associated with — even a well-established one (e.g. for an antibody named after the "
        "protein it targets, name the protein, not the disease it's a marker for; a "
        "disease-associated name belongs on the second line instead, only if it's a name "
        "genuinely used interchangeably for this exact same substance elsewhere)",
        "- Second line (only include this line if you know at least one): up to 4 common "
        "alternate names or synonyms — other ways of naming the EXACT SAME substance/test as "
        "the first line, not a different-but-related one. Search results about a biomarker "
        "often mention OTHER biomarkers it's commonly tested alongside (e.g. as part of the "
        "same panel) — do not list any of those; only include a name if it refers to precisely "
        "what the first line names, comma-separated",
        "If the search results above do not clearly indicate a specific medical/laboratory "
        "meaning, reply with exactly one word and nothing else: UNKNOWN",
    ]
    return "\n".join(lines)


def _significant_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def _grounded_in_snippets(full_name: str, tavily_response: dict) -> bool:
    """Rejects an extracted name unless at least one of its significant words actually appears
    somewhere in the retrieved snippets/answer — checks the model's answer traces back to the
    provided evidence rather than to its own recall regardless of what it was given, the specific
    failure mode this whole tier exists to design against.
    """
    haystack = " ".join(
        [tavily_response.get("answer") or ""]
        + [r.get("title") or "" for r in (tavily_response.get("results") or [])]
        + [r.get("content") or "" for r in (tavily_response.get("results") or [])]
    ).lower()
    return any(w in haystack for w in _significant_words(full_name))


async def lookup_search_ai_expansion(client: httpx.AsyncClient, term: str, tavily_api_key: str | None,
                                      local_llm_url: str | None, local_llm_model: str | None,
                                      trace: list[dict] | None = None) -> dict | None:
    if not (tavily_api_key and local_llm_url and local_llm_model):
        _trace(trace, "expansion:local-llm", "skipped",
               "Tavily key and/or local LLM URL/model not fully configured")
        return None

    tavily_response = await tavily_search(client, term, tavily_api_key, trace)
    if not tavily_response:
        return None  # tavily_search already recorded why

    t0 = time.monotonic()
    try:
        res = await client.post(
            f"{local_llm_url}/api/generate",
            json={"model": local_llm_model, "prompt": crosscheck_prompt(term, tavily_response),
                  "stream": False, "think": False},
            timeout=LOCAL_LLM_TIMEOUT,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        if res.status_code != 200:
            _trace(trace, "expansion:local-llm", "error", f"HTTP {res.status_code} from local LLM", elapsed)
            return None
        data = res.json()
        raw = (data.get("response") or "").split("</think>", 1)[-1].strip()
        if not raw or UNKNOWN_RE.match(raw):
            _trace(trace, "expansion:local-llm", "miss", "model replied UNKNOWN or gave an empty response", elapsed)
            return None
        lines = [_clean_extracted_line(line) for line in raw.split("\n") if line.strip()]
        lines = [line for line in lines if line]  # drop any that became empty after cleaning
        if not lines:
            _trace(trace, "expansion:local-llm", "miss", "response was unparseable after cleaning", elapsed)
            return None
        full = lines[0]
        if not full or len(full) > 200:  # sanity bound — a real name isn't a paragraph
            _trace(trace, "expansion:local-llm", "miss",
                   "extracted line failed sanity check (empty or too long)", elapsed)
            return None
        if not _grounded_in_snippets(full, tavily_response):
            _trace(trace, "expansion:local-llm", "miss",
                   f"rejected: '{full}' not grounded in retrieved snippets", elapsed)
            return None
        synonyms = (
            [s.strip() for s in lines[1].split(",") if s.strip()]
            if len(lines) > 1 and not NO_ANSWER_RE.match(lines[1])
            else []
        )
        # Confirmed live, twice: the model listed "IgG" as a "synonym" for dsDNA, and separately
        # a bare "Serum" for ama-m2 (a specimen-type word, not a name for the analyte at all) —
        # both became fully unconstrained match branches once cached (build_expansion_expr),
        # matching hundreds of unrelated devices. Dropped here so neither kind ever even reaches
        # the cache, on top of matching.py's own defense against the same thing regardless of
        # what's already cached: BARE_ISOTYPE_RE for isotype markers, and reusing
        # split_expansion_tokens/EXPANSION_STOPWORDS (the exact same filter build_expansion_expr
        # applies to every group) to drop any synonym that's nothing but generic filler words.
        synonyms = [
            s for s in synonyms
            if not BARE_ISOTYPE_RE.match(s) and split_expansion_tokens(s)
        ]
        detail = f"extracted '{full}'" + (f", synonyms: {', '.join(synonyms)}" if synonyms else "")
        _trace(trace, "expansion:local-llm", "hit", detail, elapsed)
        return {"full": full, "search": "/".join([full, *synonyms])} if synonyms else {"full": full}
    except httpx.HTTPError as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        _trace(trace, "expansion:local-llm", "error", str(e), elapsed)
        return None  # model not pulled, server down, timeout — never fail the whole search over this


async def resolve_expansion(client: httpx.AsyncClient, term: str, umls_api_key: str | None,
                             tavily_api_key: str | None = None, local_llm_url: str | None = None,
                             local_llm_model: str | None = None,
                             trace: list[dict] | None = None) -> tuple[dict | None, str]:
    """Returns (expansion, source) where source is 'umls' | 'search-ai' | 'none' — the caller
    persists source alongside the expansion in expansion_cache so a genuinely-unresolvable term
    doesn't get re-asked of either source on every single search.

    Confirmed live (a real UMLS key): a UMLS hit used to short-circuit here, skipping the AI
    crosscheck entirely — but UMLS returns exactly ONE candidate name, no alternates, unlike the
    AI crosscheck's 2-4 phrasings. For "ama-m2 igG", UMLS's one name ("Mitochondrial M2 IgG
    Antibody Measurement") didn't match FDA's actual device-naming convention, and with no
    fallback, the whole expansion tier failed outright — even though the very same term,
    searched with no UMLS key configured, succeeds via one of the AI's several candidate
    phrasings. Both are now tried and merged into one combined candidate pool whenever both are
    configured, so a UMLS hit adds a candidate rather than replacing the AI path's redundancy.
    This does mean a UMLS-configured search always also pays the Tavily/local-LLM latency (the
    same ~10-30s already documented for the AI-only path) rather than skipping it on a UMLS hit —
    a deliberate correctness-over-speed tradeoff, not an oversight.
    """
    umls_expansion = await lookup_umls_expansion(client, term, umls_api_key, trace)
    ai_expansion = await lookup_search_ai_expansion(client, term, tavily_api_key, local_llm_url,
                                                     local_llm_model, trace)
    if umls_expansion and ai_expansion:
        merged_search = "/".join([
            umls_expansion.get("search") or umls_expansion["full"],
            ai_expansion.get("search") or ai_expansion["full"],
        ])
        return {"full": umls_expansion["full"], "search": merged_search}, "umls"
    if umls_expansion:
        return umls_expansion, "umls"
    if ai_expansion:
        return ai_expansion, "search-ai"
    return None, "none"
