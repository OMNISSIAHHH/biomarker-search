"""Python port of the GUDID cross-check (buildGudidExpr/fetchGudidKNumbers) in
FDA510kBiomarkerSearch.html — see that file's own comment for the full story,
including the two real precision corrections found during testing:

1. gudidRawTermSafe is opt-in, not opt-out: a bare short dictionary key (e.g. "cl")
   collides badly against GUDID's device_description, which spans every device
   category FDA regulates, not just IVD (confirmed: dental porcelain, a spinal
   implant, dental handpieces, a chemistry calibrator). Only 'dsdna' is currently
   verified safe to search by its raw fused form.
2. gudidSearch overrides search/full for GUDID specifically, when the dictionary's
   normal alternate wording is unsafe there in a way it isn't against 510(k) (e.g.
   'dsdna's "Double-Stranded DNA" collided with a PCR instrument's generic
   methodology text — a real semantic ambiguity, not a token coincidence).

Treated as an UNCONFIRMED source in the caller (indexer/crawl.py), not merged into
confirmed matches — found via testing that some 510(k) clearances cover a whole
product family (e.g. Abaxis's Piccolo panel discs), so a GUDID link to a K-number
doesn't always mean the specific device shown contains the analyte, only that
something under its clearance does.
"""
from indexer.matching import (
    cross_field_tokens_clause,
    split_tokens,
    strip_anti_prefix,
    strip_isotype_suffix,
)
from indexer.openfda import MAX_RECORDS, PAGE_LIMIT, fetch_with_retry

GUDID_ENDPOINT = "https://api.fda.gov/device/udi.json"
GUDID_FIELDS = ["device_description", "brand_name"]


def _gudid_field_or(build) -> str:
    return "(" + " OR ".join(build(f) for f in GUDID_FIELDS) + ")"


def _gudid_token_group_clause(tokens: list[str]) -> str:
    return "(" + " AND ".join(_gudid_field_or(lambda f, tok=tok: f'{f}:"{tok}"') for tok in tokens) + ")"


def build_gudid_expr(term: str, expansion: dict | None) -> str | None:
    groups: list[list[str]] = []

    if expansion and expansion.get("gudidRawTermSafe"):
        antigen = strip_anti_prefix(strip_isotype_suffix(term)).strip()
        if antigen:
            groups.extend(g for g in (split_tokens(p) for p in antigen.split("/")) if g)
    elif not expansion:
        antigen = strip_anti_prefix(strip_isotype_suffix(term)).strip()
        if antigen:
            groups.extend(g for g in (split_tokens(p) for p in antigen.split("/")) if g)

    if expansion:
        phrase = expansion.get("gudidSearch") or expansion.get("search") or expansion.get("full")
        if phrase:
            groups.extend(g for g in (split_tokens(p) for p in phrase.split("/")) if g)

    if not groups:
        return None

    seen = set()
    unique_groups = []
    for g in groups:
        key = "|".join(t.lower() for t in g)
        if key in seen:
            continue
        seen.add(key)
        unique_groups.append(g)

    return "(" + " OR ".join(_gudid_token_group_clause(g) for g in unique_groups) + ")"


async def fetch_gudid_k_numbers(client, expr: str, api_key: str | None = None) -> set[str]:
    """Returns the set of K/DEN-numbers found via GUDID's premarket_submissions link — not
    full device records, same posture as the JS version, since the caller fetches the actual
    510(k) records for these numbers via a normal k_number query.
    """
    import re

    k_number_re = re.compile(r"^(K\d{6}|DEN\d{6})$", re.IGNORECASE)
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
            for sub in r.get("premarket_submissions") or []:
                num = (sub.get("submission_number") or "").upper()
                if k_number_re.match(num):
                    k_numbers.add(num)
        total = data.get("meta", {}).get("results", {}).get("total", 0)
        skip += PAGE_LIMIT
        if not (skip < total and skip < MAX_RECORDS):
            break
    return k_numbers
