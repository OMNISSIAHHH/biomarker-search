"""Python port of the tiered text-matching pipeline in FDA510kBiomarkerSearch.html
(buildExactExpr / buildBroadExpr / buildAntigenExpr / buildFusedAntiExpr /
buildExpansionExpr / buildPanelExpr and their shared helpers). Kept in lockstep
with the JS so the indexer's "confirmed" matches agree with what the live tool
finds for the same term. See FDA510kBiomarkerSearch.html's own comments (search
for these function names) for the reasoning behind each tier — this file
intentionally does not re-derive it, only reproduces the logic.
"""
import re

from indexer.openfda import DEVICE_PMA, run_query

SEARCH_FIELDS = ["device_name", "statement_or_summary", "openfda.device_name"]

GREEK_TO_LATIN = {
    "α": "alpha", "Α": "Alpha", "β": "beta", "Β": "Beta",
    "γ": "gamma", "Γ": "Gamma", "δ": "delta", "Δ": "Delta",
    "κ": "kappa", "Κ": "Kappa", "λ": "lambda", "Λ": "Lambda",
    "μ": "mu", "Μ": "Mu",
}


def to_search_term(term: str) -> str:
    for greek, latin in GREEK_TO_LATIN.items():
        term = term.replace(greek, latin)
    return term


def field_or(build) -> str:
    return "(" + " OR ".join(build(f) for f in SEARCH_FIELDS) + ")"


def build_exact_expr(term: str) -> str:
    return field_or(lambda f: f'{f}:"{term}"')


ANTI_PREFIX_RE = re.compile(r"^anti[-\s]+", re.IGNORECASE)
ANTI_PREFIX_TEST_RE = re.compile(r"^anti[-\s]", re.IGNORECASE)


def strip_anti_prefix(term: str) -> str:
    return ANTI_PREFIX_RE.sub("", term)


def has_anti_prefix(term: str) -> bool:
    return bool(ANTI_PREFIX_TEST_RE.match(term.strip()))


ANTI_SYNONYMS = ["anti", "antibody", "antibodies", "autoantibody", "autoantibodies", "ab"]
STRICT_ANTIBODY_WORDS = ["antibody", "antibodies", "autoantibody", "autoantibodies"]

ISOTYPE_SUFFIX_RE = re.compile(r"\s+Ig[AGME][1-4]?$", re.IGNORECASE)


def strip_isotype_suffix(term: str) -> str:
    return ISOTYPE_SUFFIX_RE.sub("", term)


def has_ig_suffix(term: str) -> bool:
    return bool(ISOTYPE_SUFFIX_RE.search(term))


def anti_requirement_mode(term: str) -> str:
    if has_anti_prefix(term):
        return "explicit"
    if has_ig_suffix(term):
        return "implied"
    return "none"


def _synonym_clause(field: str, words: list[str]) -> str:
    return "(" + " OR ".join(f'{field}:"{w}"' for w in words) + ")"


def cross_field_anti_clause() -> str:
    return "(" + " OR ".join(_synonym_clause(f, ANTI_SYNONYMS) for f in SEARCH_FIELDS) + ")"


def cross_field_strict_antibody_clause() -> str:
    return "(" + " OR ".join(_synonym_clause(f, STRICT_ANTIBODY_WORDS) for f in SEARCH_FIELDS) + ")"


def with_cross_field_anti(main_expr: str, mode: str) -> str:
    if mode == "explicit":
        return f"({main_expr} AND {cross_field_anti_clause()})"
    if mode == "implied":
        return f"({main_expr} AND {cross_field_strict_antibody_clause()})"
    return main_expr


def split_tokens(term: str) -> list[str]:
    return [t for t in re.split(r"[\s/]+", term.strip()) if t]


def token_clause(field: str, tokens: list[str]) -> str:
    return "(" + " AND ".join(f'{field}:"{t}"' for t in tokens) + ")"


def cross_field_tokens_clause(tokens: list[str]) -> str:
    return "(" + " AND ".join(field_or(lambda f, tok=tok: f'{f}:"{tok}"') for tok in tokens) + ")"


def build_broad_expr(term: str) -> str | None:
    mode = anti_requirement_mode(term)
    tokens = split_tokens(strip_anti_prefix(term))
    if not tokens:
        return None
    if mode == "none" and len(tokens) < 2:
        return None
    main_expr = field_or(lambda f: token_clause(f, tokens))
    return with_cross_field_anti(main_expr, mode)


def build_antigen_expr(term: str) -> str | None:
    mode = anti_requirement_mode(term)
    antigen = strip_anti_prefix(strip_isotype_suffix(term)).strip()
    if not antigen:
        return None
    tokens = split_tokens(antigen)
    if len(tokens) > 1:
        main_expr = field_or(lambda f: token_clause(f, tokens))
    else:
        main_expr = build_exact_expr(antigen)
    return with_cross_field_anti(main_expr, mode)


def build_fused_anti_expr(term: str) -> str | None:
    if anti_requirement_mode(term) == "none":
        return None
    antigen = strip_anti_prefix(strip_isotype_suffix(term)).strip()
    tokens = split_tokens(antigen)
    if len(tokens) != 1:
        return None
    fused = "Anti" + re.sub(r"[^A-Za-z0-9]", "", tokens[0])
    if fused.lower() == "anti":
        return None
    return cross_field_tokens_clause([fused])


def expansion_key(term: str) -> str:
    return strip_anti_prefix(strip_isotype_suffix(term)).strip().lower()


def lookup_expansion(term: str, dictionary: dict) -> dict | None:
    return dictionary.get(expansion_key(term))


EXPANSION_STOPWORDS = {"anti", "antibody"}


def split_expansion_tokens(phrase: str) -> list[str]:
    parts = re.split(r"[\s/,()]+", phrase)
    return [p for p in parts if p and p.lower() not in EXPANSION_STOPWORDS]


def group_implies_anti(tokens: list[str]) -> bool:
    return len(tokens) == 1 and bool(re.match(r"^anti", tokens[0], re.IGNORECASE))


def build_expansion_expr(expansion: dict, mode: str) -> str | None:
    phrase = expansion.get("search") or expansion["full"]
    groups = [split_expansion_tokens(g) for g in phrase.split("/")]
    groups = [g for g in groups if g]
    if not groups:
        return None
    anti_exempt = [g for g in groups if group_implies_anti(g)]
    anti_required = [g for g in groups if not group_implies_anti(g)]
    parts = []
    if anti_required:
        required_expr = "(" + " OR ".join(cross_field_tokens_clause(g) for g in anti_required) + ")"
        parts.append(with_cross_field_anti(required_expr, mode))
    if anti_exempt:
        parts.append("(" + " OR ".join(cross_field_tokens_clause(g) for g in anti_exempt) + ")")
    if not parts:
        return None
    return "(" + " OR ".join(parts) + ")"


PANEL_INDICATOR_WORDS = ["profile", "panel", "blot", "multiplex", "euroline", "screen", "essential"]


def build_panel_expr(category_words: list[str]) -> str | None:
    if not category_words:
        return None
    words = category_words
    if "connective tissue" in words and "ctd" not in words:
        words = [*words, "ctd"]
    fields = ["device_name", "openfda.device_name"]  # statement_or_summary is just a flag, not real text
    panel_clause = lambda f: "(" + " OR ".join(f'{f}:"{w}"' for w in PANEL_INDICATOR_WORDS) + ")"
    category_clause = lambda f: "(" + " OR ".join(f'{f}:"{w}"' for w in words) + ")"
    return "(" + " OR ".join(f"({panel_clause(f)} AND {category_clause(f)})" for f in fields) + ")"


def merge_query_results(a: dict, b: dict) -> dict:
    by_k = {r["k_number"]: r for r in a["records"]}
    by_k.update({r["k_number"]: r for r in b["records"]})
    records = list(by_k.values())
    total = max(a["total"], b["total"], len(records))
    return {"total": total, "records": records}


async def fetch_biomarker_matches(client, endpoint: str, term: str, dictionary: dict,
                                   api_key: str | None = None) -> dict:
    """Python port of fetchBiomarker (JS), tiers 1-5, minus the UMLS tier (tier 4b) — the
    indexer only ever looks up dictionary-known biomarkers, so there's no "zero dictionary
    entry" case for UMLS to handle here. Returns the same shape: total, records, match_mode,
    expansion, panel_candidates.
    """
    search_term = to_search_term(term)
    expansion = lookup_expansion(search_term, dictionary)
    best = None

    exact = await run_query(client, endpoint, build_exact_expr(search_term), api_key)
    if exact["total"] > 0:
        best = {**exact, "match_mode": "exact"}

    if not best:
        broad_expr = build_broad_expr(search_term)
        if broad_expr:
            broad = await run_query(client, endpoint, broad_expr, api_key)
            if broad["total"] > 0:
                best = {**broad, "match_mode": "broad"}

    if not best:
        antigen_expr = build_antigen_expr(search_term)
        if antigen_expr and antigen_expr != build_exact_expr(search_term):
            antigen = await run_query(client, endpoint, antigen_expr, api_key)
            if antigen["total"] > 0:
                best = {**antigen, "match_mode": "antigen-only"}

    fused_expr = build_fused_anti_expr(search_term)
    if fused_expr:
        fused = await run_query(client, endpoint, fused_expr, api_key)
        if fused["total"] > 0:
            if best:
                merged = merge_query_results(best, fused)
                best = {**merged, "match_mode": best["match_mode"]}
            else:
                best = {**fused, "match_mode": "fused-anti"}

    if expansion:
        expansion_expr = build_expansion_expr(expansion, anti_requirement_mode(search_term))
        if expansion_expr and (not best or expansion.get("alwaysCheck")):
            exp = await run_query(client, endpoint, expansion_expr, api_key)
            if exp["total"] > 0:
                if best:
                    merged = merge_query_results(best, exp)
                    best = {**merged, "match_mode": best["match_mode"]}
                else:
                    best = {**exp, "match_mode": "expansion"}

    if best:
        return {**best, "expansion": expansion, "panel_candidates": []}

    panel_candidates: list[dict] = []
    if expansion and expansion.get("panel"):
        panel_expr = build_panel_expr(expansion["panel"])
        if panel_expr:
            panel = await run_query(client, endpoint, panel_expr, api_key)
            if panel["total"] > 0:
                panel_candidates = panel["records"][:20]

    return {**exact, "match_mode": "exact", "expansion": expansion, "panel_candidates": panel_candidates}


# PMA records don't share the 510(k) schema (trade_name/generic_name instead of device_name,
# pma_number instead of k_number, no statement_or_summary flag) — rather than thread an extra
# field-name parameter through every tier-1..5 helper above, PMA gets its own small matcher:
# exact-phrase plus antigen-token matching only. PMA is a supplementary gap-filler source (891
# Immunology records never queried before this indexer existed), not required to replicate the
# full 5-tier pipeline the way 510(k) — the dictionary's primary, best-understood source — does.
#
# PMA spans every device category FDA regulates (pacemakers, hip implants, everything), not
# just IVD tests — a much bigger collision surface than 510(k) for short/ambiguous dictionary
# keys. Confirmed directly: a bare "cl" search matched a Biotronik pacemaker (P950037) purely
# because its trade name string happens to end in "...PROTOS DR/CL". The 510(k) tiers avoid
# this class of false positive via anti-prefix cross-field checks, which only fire when the
# user typed "Anti-"/an Ig-suffix — a bare "cl" has neither, so the same checks wouldn't have
# caught it there either. Restricting PMA queries to advisory committees already relevant to
# this dictionary (same ADVISORY_COMMITTEES list the indexer's PDF crawl scope uses) is a much
# more reliable filter here, since it's unrelated to how the term was typed: no cardiovascular
# implant will ever carry an Immunology/Chemistry/Hematology/Microbiology/Pathology/Toxicology
# advisory committee, regardless of what its trade name happens to contain.
from indexer.scope import ADVISORY_COMMITTEES  # noqa: E402

PMA_SEARCH_FIELDS = ["trade_name", "generic_name", "openfda.device_name"]


def _pma_field_or(build) -> str:
    return "(" + " OR ".join(build(f) for f in PMA_SEARCH_FIELDS) + ")"


def _pma_committee_clause() -> str:
    return "(" + " OR ".join(f'advisory_committee:"{c}"' for c in ADVISORY_COMMITTEES) + ")"


def build_pma_exact_expr(term: str) -> str:
    return f"({_pma_field_or(lambda f: f'{f}:\"{term}\"')} AND {_pma_committee_clause()})"


def build_pma_antigen_expr(term: str) -> str | None:
    mode = anti_requirement_mode(term)
    antigen = strip_anti_prefix(strip_isotype_suffix(term)).strip()
    if not antigen:
        return None
    tokens = split_tokens(antigen)
    if len(tokens) > 1:
        main_expr = _pma_field_or(lambda f: token_clause(f, tokens))
    else:
        main_expr = _pma_field_or(lambda f: f'{f}:"{antigen}"')
    main_expr = f"({main_expr} AND {_pma_committee_clause()})"
    return with_cross_field_anti(main_expr, mode)


async def fetch_pma_matches(client, term: str, dictionary: dict, api_key: str | None = None) -> dict:
    # Deliberately exact + antigen-only, no expansion tier: build_expansion_expr's cross-field
    # clauses are written against the 510(k) field set (device_name/statement_or_summary),
    # which don't exist on PMA records — reusing it here would silently only ever match via
    # the one overlapping field (openfda.device_name), which isn't worth the inconsistency for
    # a supplementary source. expansion is still looked up and returned for display purposes.
    search_term = to_search_term(term)
    expansion = lookup_expansion(search_term, dictionary)

    exact = await run_query(client, DEVICE_PMA, build_pma_exact_expr(search_term), api_key)
    if exact["total"] > 0:
        return {**exact, "match_mode": "exact", "expansion": expansion}

    antigen_expr = build_pma_antigen_expr(search_term)
    if antigen_expr and antigen_expr != build_pma_exact_expr(search_term):
        antigen = await run_query(client, DEVICE_PMA, antigen_expr, api_key)
        if antigen["total"] > 0:
            return {**antigen, "match_mode": "antigen-only", "expansion": expansion}

    return {**exact, "match_mode": "exact", "expansion": expansion}
