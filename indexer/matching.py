"""Python port of the tiered text-matching pipeline in FDA510kBiomarkerSearch.html
(buildExactExpr / buildBroadExpr / buildAntigenExpr / buildFusedAntiExpr /
buildExpansionExpr / buildPanelExpr and their shared helpers). Kept in lockstep
with the JS so the indexer's "confirmed" matches agree with what the live tool
finds for the same term. See FDA510kBiomarkerSearch.html's own comments (search
for these function names) for the reasoning behind each tier — this file
intentionally does not re-derive it, only reproduces the logic.
"""
import re
import time
import unicodedata

from indexer.openfda import run_query


def _trace(trace: list[dict] | None, stage: str, outcome: str, detail: str,
           elapsed_ms: int | None = None) -> None:
    """See indexer/ai_expansion.py's identical helper — appends to the caller's trace list, a
    no-op when trace is None so every existing caller not asking for search-process visibility
    is unaffected."""
    if trace is not None:
        trace.append({"stage": stage, "outcome": outcome, "detail": detail, "elapsedMs": elapsed_ms})

SEARCH_FIELDS = ["device_name", "statement_or_summary", "openfda.device_name"]

GREEK_TO_LATIN = {
    "α": "alpha", "Α": "Alpha", "β": "beta", "Β": "Beta",
    "γ": "gamma", "Γ": "Gamma", "δ": "delta", "Δ": "Delta",
    "κ": "kappa", "Κ": "Kappa", "λ": "lambda", "Λ": "Lambda",
    "μ": "mu", "Μ": "Mu",
}


# Confirmed live: openFDA's search endpoint rejects any query containing a non-ASCII letter
# inside a quoted phrase with "Search not supported" — e.g. "anti-Sjögren" (with the accented
# ö) errors outright where the plain-ASCII "anti-Sjogren" returns a normal (possibly empty)
# result. This isn't specific to ö; openFDA's Lucene-style parser appears to choke on
# non-ASCII text generally. AI-resolved synonym text (e.g. Tavily/Ollama returning "Sjögren's
# syndrome") routinely contains these, so every string that ends up quoted in a query — the
# raw search term and every expansion-derived token — gets transliterated to its closest ASCII
# form before being used, not just this one term.
def strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _replace_greek_letters(text: str) -> str:
    for greek, latin in GREEK_TO_LATIN.items():
        text = text.replace(greek, latin)
    return text


def to_search_term(term: str) -> str:
    return strip_diacritics(_replace_greek_letters(term))


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


# Confirmed live: "Centromere (CENP-A/B)" split (on whitespace/slash only, the previous
# pattern) into ["Centromere", "(CENP-A", "B)"] — the stray parentheses stuck to the adjacent
# token, producing a malformed literal-phrase search no real device text would ever contain
# verbatim. Parentheses are common in how a term's own clarifying abbreviation gets typed
# ("Name (Abbrev)"), so they're stripped here the same way whitespace/slashes already are.
def split_tokens(term: str) -> list[str]:
    return [t for t in re.split(r"[\s/()]+", term.strip()) if t]


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


# Port of generateOrthographicVariants/buildWordformExpr in FDA510kBiomarkerSearch.html —
# see that file's own comment for the full reasoning (generalizes the dsDNA/K041628 fix so it
# doesn't need a human to notice each specific split/fused-word miss). Naturally stays out of
# the short-abbreviation collision risk found elsewhere this project (PMA, then GUDID) since a
# bare 2-3 letter term has no camelCase boundary/hyphen/space to transform in the first place.
CAMEL_BOUNDARY_RE = re.compile(r"([a-z])([A-Z])")

# FDA device names aren't consistent about spacing a trailing digit off its preceding word
# either (e.g. "Domain1" vs "Domain 1") — confirmed live: K152875's actual device name spells
# it "Domain 1" (spaced), which a term typed/resolved as "...Domain1" (fused) would otherwise
# never match, the same class of gap CAMEL_BOUNDARY_RE already closes for letter-case
# transitions, just for a letter-to-digit one instead.
ALPHA_DIGIT_BOUNDARY_RE = re.compile(r"([A-Za-z])(\d)")

# FDA device names very commonly abbreviate a spelled-out Greek letter immediately preceding a
# number down to its single Latin initial instead — e.g. "beta-2-glycoprotein" becomes "B2GPI"
# in real device text, never spelled out as "beta2...". to_search_term's GREEK_TO_LATIN mapping
# (β -> "beta") only produces the spelled-out form; confirmed live this caused a real miss:
# K152875's device name is "B2GP1-Domain1", not "beta2-GP1-Domain1" (what a "β2" a user types
# becomes after Greek-letter conversion). Generated as an additional variant alongside the
# spelled-out form, since both conventions are genuinely common in real FDA text.
GREEK_SPELLED_TO_SINGLE_LETTER = {
    "alpha": "A", "beta": "B", "gamma": "G", "delta": "D", "kappa": "K", "lambda": "L", "mu": "M",
}
# Also consumes an immediately-following hyphen (the "-?" below) — a single-letter+digit
# abbreviation conventionally fuses directly with whatever follows it (e.g. "B2GPI", not
# "B2-GPI"), confirmed against K152875's real device name "B2GP1-Domain1": the hyphen the user
# typed between "β2" and "GP1" isn't present in FDA's own abbreviated convention, while the
# later hyphen before "Domain1" is untouched since this regex only matches at the Greek-letter
# prefix itself.
GREEK_SPELLED_PREFIX_RE = re.compile(r"\b(alpha|beta|gamma|delta|kappa|lambda|mu)(\d+)-?", re.IGNORECASE)


def abbreviate_greek_spelled(text: str) -> str:
    def repl(m: re.Match) -> str:
        letter = GREEK_SPELLED_TO_SINGLE_LETTER.get(m.group(1).lower(), m.group(1))
        return f"{letter}{m.group(2)}"
    return GREEK_SPELLED_PREFIX_RE.sub(repl, text)


# Confirmed live: "ZnT8A" (a common lab shorthand for Zinc Transporter 8 Autoantibody, using a
# bare "A" fused directly onto the antigen core) never matches DEN140001, whose actual device
# name is "ZINC TRANSPORTER 8 ANTIBODY (ZNT8AB)" — FDA's own fused abbreviation uses "Ab" for
# the antibody/autoantibody suffix, not a bare "A". The same convention shows up in an unrelated
# biomarker's real device name too ("IA-2Ab" in K171731/K220085), so this isn't specific to
# ZnT8 — it's FDA's general fused-suffix convention for "antibody." Generated as an additional
# variant alongside the term as typed, same additive, low-risk-of-false-match posture as the
# other variants here (an exact-phrase match still has to actually occur).
TRAILING_BARE_A_RE = re.compile(r"([A-Za-z0-9])A$")


def generate_orthographic_variants(antigen: str) -> list[str]:
    variants: list[str] = []
    seen = {antigen}

    def add(v: str) -> None:
        if v and v not in seen:
            variants.append(v)
            seen.add(v)

    add(CAMEL_BOUNDARY_RE.sub(r"\1 \2", antigen))
    add(ALPHA_DIGIT_BOUNDARY_RE.sub(r"\1 \2", antigen))

    if "-" in antigen:
        add(antigen.replace("-", " "))
    if " " in antigen:
        add(re.sub(r"\s+", "-", antigen))

    add(re.sub(r"[\s-]+", "", antigen))

    abbreviated = abbreviate_greek_spelled(antigen)
    if abbreviated != antigen:
        add(abbreviated)
        if "-" in abbreviated:
            add(abbreviated.replace("-", " "))
        add(re.sub(r"[\s-]+", "", abbreviated))

    if TRAILING_BARE_A_RE.search(antigen):
        add(antigen + "b")

    return variants


def build_wordform_expr(term: str) -> str | None:
    antigen = strip_anti_prefix(strip_isotype_suffix(term)).strip()
    if not antigen:
        return None
    variants = generate_orthographic_variants(antigen)
    if not variants:
        return None
    clauses = [cross_field_tokens_clause(split_tokens(v)) for v in variants]
    clauses = [c for c in clauses if c]
    if not clauses:
        return None
    return "(" + " OR ".join(clauses) + ")"


# Confirmed live, twice: "Centromere (CENP-A/B)" was missing 11 of 12 real Centromere/CENP-A/
# CENP-B devices (found only 1), and "Desmoglein 3 (Dsg3)" was missing K091969 (real device
# name: "...ANTI-DESMOGLEIN 3 ELISA...", spelled out with a space — never the fused "Dsg3" the
# rest of the term folded into the same mandatory AND-group). Beyond split_tokens's own
# parenthesis bug above, the deeper issue is that every existing tier ANDs its tokens together,
# but "Name (Alt)" and "Name (Prefix-Alt1/Alt2)" both describe an OR relationship — a real
# device names the antigen ONE of these ways, not all of them at once ("MESACUP-2 TEST CENP-B"
# never says "Centromere" or "CENP-A"; K091969 never says "Dsg3"). A slash-separated
# parenthetical is also a shared-prefix shorthand ("CENP-A/B" for "CENP-A and CENP-B", the same
# convention as "IL-6/8" for "IL-6 and IL-8") — a bare trailing piece like "B" isn't a real name
# on its own, it borrows the prefix from before the slash. Generated as extra alternative
# candidate phrases, tried independently (OR'd) rather than folded into the same AND-group as
# the rest of the term — not specific to either term above, applies to any "Name (Alt)" or
# "Name (Prefix-Alt1/Alt2)" convention.
PAREN_CONTENT_RE = re.compile(r"\(([^()]+)\)")


def expand_paren_alternates(term: str) -> list[str]:
    m = PAREN_CONTENT_RE.search(term)
    if not m:
        return []
    inner = m.group(1).strip()
    if not inner:
        return []
    if "/" not in inner:
        return [inner]
    pieces = [p.strip() for p in inner.split("/") if p.strip()]
    if not pieces:
        return []
    first = pieces[0]
    prefix_match = re.match(r"^(.*-)", first)
    prefix = prefix_match.group(1) if prefix_match else ""
    alternates = [first]
    for piece in pieces[1:]:
        alternates.append(piece if "-" in piece else prefix + piece)
    return alternates


def build_paren_alternates_expr(term: str) -> str | None:
    alternates = expand_paren_alternates(term)
    if not alternates:
        return None
    paren_start = term.index("(")
    before_paren = term[:paren_start].strip()
    candidates = ([before_paren] if before_paren else []) + alternates
    clauses = [build_exact_expr(c) for c in candidates if c]
    if not clauses:
        return None
    return "(" + " OR ".join(clauses) + ")"


# Confirmed live: K123261's real Decision Summary Measurand is "Anti-nRNP/Sm, anti-Sm,
# anti-SS-A, anti-SS-B, anti-Scl-70, anti-Centromeres, anti-Jo-1, anti-Ribosomal P-proteins IgG
# antibodies (bundled)" — a bundled 8-antigen panel — but its device_name only ever says
# "ANTI-NRNP/SM", so it's structurally invisible to every text-matching tier here, which only
# ever queries openFDA's own device_name/statement_or_summary/openfda.device_name fields, never
# the actual PDF text. The predicate crawl (indexer/crawl.py) already reads and stores this real
# Measurand text locally (pdf_text.measurand_value) specifically to close this gap — confirmed
# via db.py that nothing ever reads it back out for search purposes; lookup.py's own
# `panelCandidates` field, clearly built for exactly this ("possible panel match", shown as
# unconfirmed/verify-manually), was hardcoded to `[]` everywhere. This generates the substrings
# worth checking a device's crawled Measurand text for, reusing the same antigen-extraction,
# wordform-variant generation, and parenthetical-alternate expansion the confirmed-match tiers
# already use — so "does this bundled panel's real Measurand mention this antigen" uses the same
# definition of "the antigen" as the rest of this pipeline, including the same fused/hyphenated
# form handling ("jo1" needs "Jo-1" too, the form real Measurand prose actually uses).
# Confirmed live: "jo1" only generates the variants "jo1"/"jo 1" (no hyphenated form — the
# digit-boundary split only ever adds a space, see generate_orthographic_variants), but the
# real Measurand text says "anti-Jo-1" — hyphenated. A literal whole-phrase substring match
# against either variant would never find it. The confirmed-match tiers don't have this problem
# because cross_field_tokens_clause never matches a *phrase* either — it splits each variant
# into separate words and requires them all present independently (which is why "jo 1" already
# correctly matches "JO-1" today: "jo" and "1" each just have to appear somewhere). Returning
# token groups instead of phrase strings mirrors that same semantics for panel-candidate search.
def panel_candidate_search_token_groups(search_term: str) -> list[list[str]]:
    antigen = strip_anti_prefix(strip_isotype_suffix(search_term)).strip()
    if not antigen:
        return []
    variants = [antigen] + generate_orthographic_variants(antigen)
    # Mirrors build_paren_alternates_expr: expand_paren_alternates only returns what's *inside*
    # the parens ("CENP-A"/"CENP-B"), not the term before them ("Centromere") — without adding
    # that too, every remaining group still requires the parenthetical alternates ANDed in
    # alongside "Centromere", so a device whose Measurand just says "anti-Centromeres" (no
    # CENP-A/B at all, confirmed live: K123261) would never match on that alone.
    if "(" in search_term:
        before_paren = search_term[:search_term.index("(")].strip()
        if before_paren:
            variants.append(before_paren)
    variants += expand_paren_alternates(search_term)
    seen: set[tuple[str, ...]] = set()
    groups: list[list[str]] = []
    for v in variants:
        if not v:
            continue
        tokens = tuple(split_tokens(v))
        if tokens and tokens not in seen:
            seen.add(tokens)
            groups.append(list(tokens))
    return groups


def expansion_key(term: str) -> str:
    return strip_anti_prefix(strip_isotype_suffix(term)).strip().lower()


# Confirmed live: an AI-crosscheck-resolved synonym list for "ama-m2" included a bare "Serum"
# entry — a generic specimen-type word, not a name for the analyte at all — which became its
# own fully unconstrained match branch (see build_expansion_expr) and matched 775 unrelated
# devices (e.g. "LIAISON CMV IgG Serum Control Set") purely because they mention serum
# somewhere, same failure shape as the earlier bare-"IgG" bug. These words get stripped from
# every group the same way "anti"/"antibody" already are — a group reduced to nothing but
# stopwords becomes empty and is dropped entirely (see build_expansion_expr's `if g` filter);
# a group with other, specific content alongside one of these just loses the filler word. Not
# an exhaustive list — expect to keep adding to it as new generic "synonyms" turn up.
EXPANSION_STOPWORDS = {
    "anti", "antibody", "antibodies",
    "serum", "plasma", "blood", "urine",
    "test", "assay", "panel", "screen", "profile", "control", "sample", "specimen",
    "immunology", "diagnostic", "laboratory",
    # Confirmed live (with a real UMLS key): UMLS resolved "ama-m2 igG" to an NCI Thesaurus
    # concept name, "Mitochondrial M2 IgG Antibody Measurement" — "Measurement" is NCI's own
    # ontology-naming suffix for a lab-test *concept*, never how an actual FDA device/kit
    # describes itself. Same category as "test"/"assay"/"panel" above, just a source (NCI
    # Thesaurus via UMLS) this project hadn't hit before.
    "measurement",
}


# Confirmed live: an AI-resolved synonym for "Anti-β2-GP1 IgA" included literal Greek-letter
# text ("β2GP1", "β2A-CIC") that reached openFDA completely unconverted — to_search_term's Greek
# handling only ever ran on the raw typed term, never on expansion-derived text, so a Greek
# letter anywhere in an AI/UMLS-resolved name or synonym slipped straight through
# strip_diacritics (which only strips combining marks off Latin letters — Greek letters have no
# such decomposition, so it's a no-op on them) and into a quoted query, triggering the exact
# same "Search not supported" openFDA rejection strip_diacritics exists to prevent.
def split_expansion_tokens(phrase: str) -> list[str]:
    parts = re.split(r"[\s/,()]+", strip_diacritics(_replace_greek_letters(phrase)))
    return [
        p for p in parts
        if p and p.lower() not in EXPANSION_STOPWORDS and not BARE_ISOTYPE_RE.match(p)
    ]


def group_implies_anti(tokens: list[str]) -> bool:
    return len(tokens) == 1 and bool(re.match(r"^anti", tokens[0], re.IGNORECASE))


# Confirmed live: the Tavily+Ollama crosscheck resolved "dsDNA" to a synonym list including a
# bare "IgG" group (the model treating the antibody *class* as if it were itself an alternate
# name for the analyte). Since a bare isotype group has no anti-prefix, anti_requirement_mode
# for a term like "dsDNA" (which has none of its own) returns "none", so the group got zero
# extra constraint — the query became "any device mentioning IgG anywhere," matching nearly
# every antibody-class immunoassay in the database (e.g. "Alinity i Rubella IgG", completely
# unrelated). Filtered out by split_expansion_tokens (same treatment as any other stopword) so
# an isotype marker is never itself part of a match requirement — regardless of whether it's the
# *entire* group (the dsDNA case above) or just one word alongside others: confirmed live (real
# UMLS key) "ama-m2 igG" resolved to "Mitochondrial M2 IgG Antibody Measurement", where requiring
# "IgG" as a mandatory AND-condition alongside "Mitochondrial"/"M2" excluded real devices that
# either don't specify isotype at all or fuse multiple isotypes into one word ("IGGAM"). The raw
# term's own isotype suffix already gets this same treatment via strip_isotype_suffix before the
# exact/broad/wordform tiers ever see it — this is that same reasoning, applied to
# AI/UMLS-resolved text too, which strip_isotype_suffix never touches.
BARE_ISOTYPE_RE = re.compile(r"^Ig[AGME][1-4]?$", re.IGNORECASE)

# Confirmed live: an AI-resolved synonym for "ama-m2" — "Immunology Profile (AMA)" — reduces to
# a bare "AMA" group once "Immunology" and "Profile" are stripped as stopwords, matching wildly
# unrelated devices that merely contain "AMA" as a substring (a dental "CROWN REMOVER & AMA."
# tool, a "DISPOSABLE AMA STERILE DRAPE SHEET"). Same failure shape as the bare-isotype bug
# above and the bare-digit/bare-single-letter ones found on the LDT side — any short (here,
# 4 characters or fewer) token left standing alone after stopword-filtering is inherently too
# ambiguous a medical abbreviation to serve as its own unconstrained match branch, regardless of
# which specific short word it happens to be. Not applied to the raw search term's own tiers
# (exact/broad/antigen-only already handle that case appropriately) — only to expansion groups,
# where a short leftover token is usually an accident of stopword-stripping a longer AI phrase
# rather than a deliberate, specific abbreviation someone actually typed.
def _is_bare_short_token(tokens: list[str]) -> bool:
    return len(tokens) == 1 and len(tokens[0]) <= 4


def build_expansion_expr(expansion: dict, mode: str) -> str | None:
    phrase = expansion.get("search") or expansion["full"]
    groups = [split_expansion_tokens(g) for g in phrase.split("/")]
    groups = [g for g in groups if g]
    groups = [g for g in groups if not _is_bare_short_token(g)]
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


def merge_query_results(a: dict, b: dict) -> dict:
    by_k = {r["k_number"]: r for r in a["records"]}
    by_k.update({r["k_number"]: r for r in b["records"]})
    records = list(by_k.values())
    total = max(a["total"], b["total"], len(records))
    return {"total": total, "records": records}


async def _timed_query(client, endpoint: str, expr: str, api_key: str | None) -> tuple[dict, int]:
    t0 = time.monotonic()
    result = await run_query(client, endpoint, expr, api_key)
    return result, int((time.monotonic() - t0) * 1000)


async def fetch_biomarker_matches(client, endpoint: str, term: str, expansion: dict | None,
                                   api_key: str | None = None,
                                   trace: list[dict] | None = None) -> dict:
    """Python port of fetchBiomarker (JS), tiers 1-5. `expansion` is resolved by the caller
    (indexer/lookup.py, via ai_expansion.resolve_expansion + its cache) before this is called —
    this function treats it as an opaque {full, search} dict, same as the browser tool's
    ABBREVIATION_EXPANSIONS entries used to be. Returns the same shape: total, records,
    match_mode, expansion.
    """
    search_term = to_search_term(term)
    best = None

    exact, elapsed = await _timed_query(client, endpoint, build_exact_expr(search_term), api_key)
    if exact["total"] > 0:
        best = {**exact, "match_mode": "exact"}
        _trace(trace, "match:exact", "hit", f"{exact['total']} result(s)", elapsed)
    else:
        _trace(trace, "match:exact", "miss", "0 results", elapsed)

    if not best:
        broad_expr = build_broad_expr(search_term)
        if broad_expr:
            broad, elapsed = await _timed_query(client, endpoint, broad_expr, api_key)
            if broad["total"] > 0:
                best = {**broad, "match_mode": "broad"}
                _trace(trace, "match:broad", "hit", f"{broad['total']} result(s)", elapsed)
            else:
                _trace(trace, "match:broad", "miss", "0 results", elapsed)
        else:
            _trace(trace, "match:broad", "skipped", "term too short/single-token for a broad query")
    else:
        _trace(trace, "match:broad", "skipped", "an earlier tier already matched")

    if not best:
        antigen_expr = build_antigen_expr(search_term)
        if antigen_expr and antigen_expr != build_exact_expr(search_term):
            antigen, elapsed = await _timed_query(client, endpoint, antigen_expr, api_key)
            if antigen["total"] > 0:
                best = {**antigen, "match_mode": "antigen-only"}
                _trace(trace, "match:antigen-only", "hit", f"{antigen['total']} result(s)", elapsed)
            else:
                _trace(trace, "match:antigen-only", "miss", "0 results", elapsed)
        else:
            _trace(trace, "match:antigen-only", "skipped", "antigen-only query is identical to the exact query")
    else:
        _trace(trace, "match:antigen-only", "skipped", "an earlier tier already matched")

    fused_expr = build_fused_anti_expr(search_term)
    if fused_expr:
        fused, elapsed = await _timed_query(client, endpoint, fused_expr, api_key)
        if fused["total"] > 0:
            if best:
                merged = merge_query_results(best, fused)
                best = {**merged, "match_mode": best["match_mode"]}
                _trace(trace, "match:fused-anti", "hit",
                       f"{fused['total']} result(s), merged into existing {best['match_mode']} match", elapsed)
            else:
                best = {**fused, "match_mode": "fused-anti"}
                _trace(trace, "match:fused-anti", "hit", f"{fused['total']} result(s) — first tier to match", elapsed)
        else:
            _trace(trace, "match:fused-anti", "miss", "0 results", elapsed)
    else:
        _trace(trace, "match:fused-anti", "skipped", "term has no anti-prefix/isotype signal")

    wordform_expr = build_wordform_expr(search_term)
    if wordform_expr:
        wordform, elapsed = await _timed_query(client, endpoint, wordform_expr, api_key)
        if wordform["total"] > 0:
            if best:
                merged = merge_query_results(best, wordform)
                best = {**merged, "match_mode": best["match_mode"]}
                _trace(trace, "match:wordform", "hit",
                       f"{wordform['total']} result(s), merged into existing {best['match_mode']} match", elapsed)
            else:
                best = {**wordform, "match_mode": "wordform"}
                _trace(trace, "match:wordform", "hit",
                       f"{wordform['total']} result(s) — first tier to match", elapsed)
        else:
            _trace(trace, "match:wordform", "miss", "0 results", elapsed)
    else:
        _trace(trace, "match:wordform", "skipped", "no orthographic variants generated for this term")

    paren_expr = build_paren_alternates_expr(search_term)
    if paren_expr:
        paren_result, elapsed = await _timed_query(client, endpoint, paren_expr, api_key)
        if paren_result["total"] > 0:
            if best:
                merged = merge_query_results(best, paren_result)
                best = {**merged, "match_mode": best["match_mode"]}
                _trace(trace, "match:paren-alternates", "hit",
                       f"{paren_result['total']} result(s), merged into existing {best['match_mode']} match", elapsed)
            else:
                best = {**paren_result, "match_mode": "paren-alternates"}
                _trace(trace, "match:paren-alternates", "hit",
                       f"{paren_result['total']} result(s) — first tier to match", elapsed)
        else:
            _trace(trace, "match:paren-alternates", "miss", "0 results", elapsed)
    else:
        _trace(trace, "match:paren-alternates", "skipped", "no \"Name (Alt1/Alt2)\" pattern in this term")

    # Always merged in when an expansion resolved, regardless of whether an earlier tier already
    # matched — no per-entry alwaysCheck opt-in anymore (that was a curated-dictionary concept).
    # Same reasoning build_fused_anti_expr already relies on to run unconditionally: a multi-word
    # synonym/full-name phrase, not a bare token, makes an accidental cross-match unlikely.
    if expansion:
        expansion_expr = build_expansion_expr(expansion, anti_requirement_mode(search_term))
        if expansion_expr:
            exp, elapsed = await _timed_query(client, endpoint, expansion_expr, api_key)
            if exp["total"] > 0:
                if best:
                    merged = merge_query_results(best, exp)
                    best = {**merged, "match_mode": best["match_mode"]}
                    _trace(trace, "match:expansion", "hit",
                           f"{exp['total']} result(s), merged into existing {best['match_mode']} match", elapsed)
                else:
                    best = {**exp, "match_mode": "expansion"}
                    _trace(trace, "match:expansion", "hit",
                           f"{exp['total']} result(s) — first tier to match", elapsed)
            else:
                _trace(trace, "match:expansion", "miss", "0 results", elapsed)
        else:
            _trace(trace, "match:expansion", "skipped", "resolved expansion produced no usable query")
    else:
        _trace(trace, "match:expansion", "skipped", "no expansion resolved for this term")

    if best:
        return {**best, "expansion": expansion}

    return {**exact, "match_mode": "exact", "expansion": expansion}
