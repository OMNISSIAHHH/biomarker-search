"""Python port of the browser tool's UMLS abbreviation lookup (lookupUmlsExpansion in
FDA510kBiomarkerSearch.html), promoted here from a last-resort fallback (used only for terms
missing a dictionary entry) to the indexer's only expansion mechanism, now that dictionary.json
is gone. UMLS is a real, curated medical terminology database aggregating many source
vocabularies (SNOMED CT, LOINC, MeSH, etc.) — resolving an abbreviation this way is unverified
(nobody has manually confirmed the match is right, unlike every old ABBREVIATION_EXPANSIONS
entry), but it's a database lookup, not a generated guess.

A local-LLM (Ollama) alternative was tried and removed: a small general-purpose model correctly
following its own uncertainty instructions still doesn't reliably know niche lab/serology
abbreviations (confirmed live: qwen3:4b had no idea "AMA-M2" meant Anti-Mitochondrial Antibody,
M2 subtype), on top of needing local install/model management and being slow on CPU. UMLS covers
the same "resolve an abbreviation not in any curated list" need without either problem.
"""
import httpx

UMLS_SEARCH_BASE = "https://uts-ws.nlm.nih.gov/rest/search/current"


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


async def resolve_expansion(client: httpx.AsyncClient, term: str,
                             umls_api_key: str | None) -> tuple[dict | None, str]:
    """Returns (expansion, source) where source is 'umls' | 'none' — the caller persists source
    alongside the expansion in expansion_cache so a genuinely-unresolvable term doesn't get
    re-asked of UMLS on every single search.
    """
    if umls_api_key:
        expansion = await lookup_umls_expansion(client, term, umls_api_key)
        if expansion:
            return expansion, "umls"
    return None, "none"
