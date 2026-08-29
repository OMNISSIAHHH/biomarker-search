"""AI cross-check for LDT search results, across whichever data sources (NY State, ARUP,
LabCorp, Quest) the browser already searched and text-matched.

Each source's own search casts a wide net (see FDA510kBiomarkerSearch.html's
textMatchesQueryWords), so a candidate can pass the "every significant word appears somewhere"
filter while still being, on a human read, a different test than the one searched for (shared
vocabulary, not a shared analyte). This asks the same local LLM already used for the FDA-side
AI-suggested expansion tier (see indexer/ai_expansion.py) to read each candidate's actual test
name and judge whether it's genuinely a test for the searched term — a second, semantic pass on
top of the first, purely lexical one.

Explicitly a confidence signal, not a filter: the browser still shows every text-matched
candidate either way, just labeled "AI confirmed" / "AI: uncertain" — same "unverified, worth a
manual look" posture already established for UMLS-resolved/AI-suggested FDA matches, not a hard
gate that could silently hide a real result behind a model's mistake.

Batches every candidate across every source into ONE prompt/inference call per term, not one
call per candidate — confirmed elsewhere in this project that a single local-LLM call already
costs ~15-25s (see ai_expansion.py's LOCAL_LLM_TIMEOUT comment), so a per-candidate call would
make a multi-source LDT search take minutes.
"""
import re
import time

import httpx

LDT_CROSSCHECK_LINE_RE = re.compile(r"^\s*(\d+)\s*:\s*(YES|NO)\b", re.IGNORECASE)
# Same generous bound as ai_expansion.py's local-LLM calls — a batched prompt with many
# candidates is a longer read than the single-name extraction prompt, so this needs at least as
# much headroom, not less.
LOCAL_LLM_TIMEOUT = 120.0


def _trace(trace: list[dict] | None, stage: str, outcome: str, detail: str,
           elapsed_ms: int | None = None) -> None:
    if trace is not None:
        trace.append({"stage": stage, "outcome": outcome, "detail": detail, "elapsedMs": elapsed_ms})


def _ldt_crosscheck_prompt(term: str, candidates: list[dict]) -> str:
    lines = [
        "You are verifying laboratory test search results for a biomarker search tool.",
        f'Search term (the biomarker/analyte being searched for): "{term}"',
        "",
        "Below is a numbered list of test names found by a text search across several different",
        "lab test catalogs. A text search can match on shared words without the test actually",
        "being for the same analyte (e.g. a panel that only mentions the term in passing, or a",
        "different marker with a similar name). For each numbered item, decide: is this test",
        f'genuinely a test FOR "{term}" itself (YES), or does it just share some words with it',
        "while actually testing for something meaningfully different (NO)?",
        "",
    ]
    for c in candidates:
        lines.append(f'{c["id"]}: "{c["name"]}"')
    lines += [
        "",
        f"There are {len(candidates)} numbered items above. Reply with EXACTLY {len(candidates)}",
        "lines, one per item, in the same order, in this exact format and nothing else — no",
        "explanation, no header, no blank lines:",
        "<number>: YES",
        "<number>: NO",
    ]
    return "\n".join(lines)


async def crosscheck_ldt_candidates(client: httpx.AsyncClient, term: str, candidates: list[dict],
                                     local_llm_url: str | None, local_llm_model: str | None,
                                     trace: list[dict] | None = None) -> dict[int, bool]:
    """`candidates` is [{"id": int, "name": str}, ...] — the caller (server/main.py) assigns ids
    and extracts each source's own display-name field before calling this. Returns {id: True/
    False} for whatever the model actually judged; an id missing from the result (parse failure,
    the model skipped/miscounted a line) is left for the caller to treat as "not confirmed" —
    same fail-open-to-unverified posture as everywhere else in this pipeline, never a hard error.
    """
    if not local_llm_url or not local_llm_model or not candidates:
        _trace(trace, "ldt-crosscheck", "skipped",
               "no local LLM configured" if not (local_llm_url and local_llm_model) else "no candidates to check")
        return {}
    t0 = time.monotonic()
    try:
        res = await client.post(
            f"{local_llm_url}/api/generate",
            # Confirmed live: without pinning temperature, an identical request could come back
            # "0: NO, 1: YES" one call and "0: YES, 1: NO" the next, for the same obviously-
            # correct/incorrect pair (Glutamic Acid Decarboxylase Antibody vs. Hepatitis B
            # Surface Antigen, searching "GADA") — pure sampling noise on a classification task
            # that should be near-deterministic. temperature: 0 (greedy decoding) doesn't
            # eliminate every inconsistency a 3B model can have on genuinely borderline cases,
            # but removes the noise on the clear-cut ones.
            json={"model": local_llm_model, "prompt": _ldt_crosscheck_prompt(term, candidates),
                  "stream": False, "think": False, "options": {"temperature": 0}},
            timeout=LOCAL_LLM_TIMEOUT,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        if res.status_code != 200:
            _trace(trace, "ldt-crosscheck", "error", f"HTTP {res.status_code} from local LLM", elapsed)
            return {}
        raw = (res.json().get("response") or "").split("</think>", 1)[-1]
        results: dict[int, bool] = {}
        for line in raw.splitlines():
            m = LDT_CROSSCHECK_LINE_RE.match(line)
            if m:
                results[int(m.group(1))] = m.group(2).upper() == "YES"
        _trace(trace, "ldt-crosscheck", "hit",
               f"{len(results)}/{len(candidates)} candidate(s) judged", elapsed)
        return results
    except httpx.HTTPError as e:
        _trace(trace, "ldt-crosscheck", "error", str(e), int((time.monotonic() - t0) * 1000))
        return {}  # model not pulled, server down, timeout — never fail the whole search over this
