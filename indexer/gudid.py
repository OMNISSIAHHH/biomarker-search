"""Python port of the GUDID cross-check (buildGudidExpr/fetchGudidKNumbers) in
FDA510kBiomarkerSearch.html.

GUDID is only ever searched using an AI-resolved expansion's full name/synonyms — never the
bare/raw term a user typed. This used to be a curated, opt-in exception (gudidRawTermSafe) for
one dictionary entry ('dsdna'); every other entry was safe from raw-term search only as a side
effect of merely existing in the dictionary at all (a term with no entry fell into a raw-term
search branch by default). Confirmed via testing that raw-term search is what caused "cl" to
collide with dental porcelain, a spinal implant, and dental handpieces in GUDID's free-text
device_description, which spans every device category FDA regulates, not just IVD. Now that
there's no curated dictionary to accidentally provide that protection, raw-term search is
removed entirely rather than re-implemented as a default — a term with no resolved expansion
simply isn't searched against GUDID at all (fail closed, not fail open).

Bare-instrument exclusion (_record_is_bare_instrument, below) is the other precision fix, and is
unrelated to the above — confirmed via curl that a PCR instrument ("Revogene", K222779) matches
"dsDNA" purely through generic methodology text ("...specific sequences of double stranded DNA,
amplified from a biological source...") — its product_codes/gmdn_terms are pure hardware
classification ("Real Time Nucleic Acid Amplification System"), with no antibody/antigen/reagent
language anywhere in the record. Excludes a hit only when its classification data reads as bare
instrumentation with zero reagent-type language — deliberately narrow, not "does the
classification name this exact analyte": an earlier, stricter version of this check (requiring
the classification to name the specific analyte) also silently dropped confirmed genuine matches
like K030929 ("ANA Detect ELISA", whose own device_description explicitly lists "dsDNA" as one
of 8 profiled antigens) — FDA's product code for bundled ANA panels is generically "Multiple
antinuclear antibody (ANA)...," never naming individual antigens, so requiring exact-analyte
corroboration would exclude every bundled panel, which is exactly the category GUDID's free-text
description exists to catch in the first place.

Treated as an UNCONFIRMED source in the caller (indexer/lookup.py), not merged into confirmed
matches — found via testing that some 510(k) clearances cover a whole product family (e.g.
Abaxis's Piccolo panel discs), so a GUDID link to a K-number doesn't always mean the specific
device shown contains the analyte, only that something under its clearance does.
"""
import re

from indexer.matching import split_tokens
from indexer.openfda import MAX_RECORDS, PAGE_LIMIT, fetch_with_retry

GUDID_ENDPOINT = "https://api.fda.gov/device/udi.json"
GUDID_FIELDS = ["device_description", "brand_name"]
K_NUMBER_RE = re.compile(r"^(K\d{6}|DEN\d{6})$", re.IGNORECASE)

INSTRUMENT_SIGNAL_WORDS = {"system", "instrument", "analyzer", "analyser", "amplification", "thermal cycler", "sequencer", "reader"}
REAGENT_SIGNAL_WORDS = {"antibody", "antibodies", "antigen", "reagent", "elisa", "immunoassay"}


def _search_token_groups(expansion: dict | None) -> list[list[str]]:
    if not expansion:
        return []
    phrase = expansion.get("search") or expansion.get("full")
    if not phrase:
        return []
    groups = [g for g in (split_tokens(p) for p in phrase.split("/")) if g]

    seen = set()
    unique_groups = []
    for g in groups:
        key = "|".join(t.lower() for t in g)
        if key in seen:
            continue
        seen.add(key)
        unique_groups.append(g)
    return unique_groups


def _gudid_field_or(build) -> str:
    return "(" + " OR ".join(build(f) for f in GUDID_FIELDS) + ")"


def _gudid_token_group_clause(tokens: list[str]) -> str:
    return "(" + " AND ".join(_gudid_field_or(lambda f, tok=tok: f'{f}:"{tok}"') for tok in tokens) + ")"


def build_gudid_expr(expansion: dict | None) -> str | None:
    groups = _search_token_groups(expansion)
    if not groups:
        return None
    return "(" + " OR ".join(_gudid_token_group_clause(g) for g in groups) + ")"


def _record_is_bare_instrument(record: dict) -> bool:
    """True only when the record's own FDA-assigned classification (product_codes /
    gmdn_terms) reads as pure hardware — an instrument/system/analyzer word present, and
    zero antibody/antigen/reagent-type language anywhere. See this module's own docstring for
    why this is deliberately narrow (not "does the classification name this exact analyte").
    """
    parts = []
    for pc in record.get("product_codes") or []:
        parts.append(pc.get("name") or "")
        parts.append((pc.get("openfda") or {}).get("device_name") or "")
    for g in record.get("gmdn_terms") or []:
        parts.append(g.get("name") or "")
        parts.append(g.get("definition") or "")
    combined = " ".join(parts).lower()
    has_instrument_signal = any(w in combined for w in INSTRUMENT_SIGNAL_WORDS)
    has_reagent_signal = any(w in combined for w in REAGENT_SIGNAL_WORDS)
    return has_instrument_signal and not has_reagent_signal


async def fetch_gudid_k_numbers(client, expansion: dict | None,
                                 api_key: str | None = None) -> set[str]:
    """Returns the set of K/DEN-numbers found via GUDID's premarket_submissions link, after the
    classification-corroboration check above — not full device records, since the caller fetches
    the actual 510(k) records for these numbers via a normal k_number query.
    """
    expr = build_gudid_expr(expansion)
    if not expr:
        return set()

    k_numbers: set[str] = set()
    skip = 0
    total = 0
    while True:
        params = {"search": expr, "limit": PAGE_LIMIT, "skip": skip}
        if api_key:
            params["api_key"] = api_key
        res = await fetch_with_retry(client, GUDID_ENDPOINT, params)
        if res.status_code == 404:
            break
        if res.status_code >= 400:
            break  # best-effort supplementary source — don't fail the whole crawl over this
        data = res.json()
        for r in data.get("results", []):
            if _record_is_bare_instrument(r):
                continue
            for sub in r.get("premarket_submissions") or []:
                num = (sub.get("submission_number") or "").upper()
                if K_NUMBER_RE.match(num):
                    k_numbers.add(num)
        total = data.get("meta", {}).get("results", {}).get("total", 0)
        skip += PAGE_LIMIT
        if not (skip < total and skip < MAX_RECORDS):
            break
    return k_numbers
