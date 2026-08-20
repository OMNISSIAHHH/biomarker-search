"""Fetches an FDA decision summary PDF (same two-URL-pattern fallback as
worker/fda-pdf-proxy.js, no Worker needed here since Python isn't
browser-CORS-restricted) and extracts two things from its text:

1. Measurand — a faithful port of MEASURAND_FIELD_LABELS/measurandFieldPattern/
   extractMeasurand from FDA510kBiomarkerSearch.html. The JS builds its text by
   joining pdf.js's per-item strings with a single space per page (collapsing all
   line breaks), so this ports that exact flattening before applying the same
   regex, to keep behavior identical rather than re-deriving it against pypdf's
   differently-shaped output.

2. Predicate Device Names and 510(k) Numbers — new. Unlike Measurand, this is
   read from pypdf's line-preserving text (not flattened), because the predicate
   table is a real multi-row table in the source document and line breaks are
   exactly the structure needed to split one row from the next.
"""
import re
from dataclasses import dataclass, field

import httpx
from pypdf import PdfReader
from io import BytesIO

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DECISION_SUMMARY_BASE = "https://www.accessdata.fda.gov/cdrh_docs/reviews"
SUMMARY_BASE = "https://www.accessdata.fda.gov/cdrh_docs"

DEVICE_NUMBER_RE = re.compile(r"^(K\d{6}|DEN\d{6})$")


def summary_year_folder(device_number: str) -> str:
    """Port of summaryYearFolder in worker/fda-pdf-proxy.js: the plain "Summary" archive's
    year folder isn't consistently zero-padded — 1996-2001 has none at all, 2002-2009 uses a
    single digit with no leading zero, 2010+ uses the two-digit year as-is.
    """
    year_start = 3 if device_number.startswith("DEN") else 1
    yy = int(device_number[year_start:year_start + 2])
    if yy >= 96 or yy <= 1:
        return ""
    return str(yy)


class PdfFetchError(Exception):
    pass


async def fetch_decision_pdf(client: httpx.AsyncClient, k_number: str) -> tuple[bytes, str]:
    """Returns (pdf_bytes, source_url). Raises PdfFetchError if neither document exists."""
    if not DEVICE_NUMBER_RE.match(k_number):
        raise PdfFetchError(f"not a K/DEN number: {k_number}")

    headers = {"User-Agent": BROWSER_UA}
    urls = [f"{DECISION_SUMMARY_BASE}/{k_number}.pdf"]
    folder = summary_year_folder(k_number)
    urls.append(f"{SUMMARY_BASE}/pdf{folder}/{k_number}.pdf")

    last_status = None
    for url in urls:
        try:
            res = await client.get(url, headers=headers, timeout=30.0, follow_redirects=True)
        except httpx.HTTPError as e:
            last_status = str(e)
            continue
        if res.status_code == 404:
            last_status = 404
            continue
        if res.status_code != 200 or "pdf" not in res.headers.get("content-type", "").lower():
            last_status = res.status_code
            continue
        return res.content, url
    raise PdfFetchError(f"no decision document found (last status: {last_status})")


@dataclass
class ExtractedPdf:
    full_text: str
    measurand_label: str | None = None
    measurand_value: str | None = None
    predicates: list[dict] = field(default_factory=list)


# --- Measurand extraction (ported from extractMeasurand / measurandFieldPattern) -----------

MEASURAND_FIELD_LABELS = [
    "Measurand",
    "Analyte",
    r"Type of Test(?:s)?(?:\s+or\s+Tests\s+Performed)?",
    "Intended Use",
]


def _measurand_field_pattern(label_pattern: str) -> re.Pattern:
    # Deliberately case-sensitive, same as the JS: FDA section headers are consistently
    # capitalized ("B Measurand:"), and a case-insensitive match risks matching the word
    # "measurand" in ordinary prose elsewhere in the document.
    return re.compile(
        rf"[A-Z]\.?\s*({label_pattern})s?\s*:\s*([\s\S]{{1,400}}?)\s*(?=[A-Z]\.?\s+[A-Z][a-z]|$)"
    )


def _extract_measurand(flattened_text: str) -> tuple[str, str] | None:
    for label_pattern in MEASURAND_FIELD_LABELS:
        m = _measurand_field_pattern(label_pattern).search(flattened_text)
        if m:
            return m.group(1), m.group(2).strip()
    return None


# --- Predicate table extraction (new) -------------------------------------------------------

# FDA's decision-summary template for the predicate section has changed at least 3 times
# across eras (confirmed against 3 real PDFs, one per era — same kind of template drift the
# existing Measurand extraction already has to deal with, see MEASURAND_FIELD_LABELS above):
#
#   Strategy A (e.g. K213403, 2023): one combined table, "Predicate Name" then
#     "510(k) Number" as column headers, "<name>  K######" one pair per line.
#   Strategy B (e.g. K152013, 2016): two separate numbered subsections, "1. Predicate device
#     name(s):" listing name(s), then "2. Predicate 510(k) number(s):" listing number(s) —
#     paired by list position.
#   Strategy C (e.g. K223093, 2022): a "Predicate 510(k) Number(s):" subsection where each
#     line is number-first: "K###### - <name>".
#   Strategy D (e.g. K163133, 2016 — found while investigating a real AMA/M2 search miss):
#     one combined header, "Predicate device name (Predicate 510(k) number):", followed by one
#     or more lines of "<name> (K######)" — the number in parentheses at the end of the name.
#
# Tried in order; the first strategy that finds anything wins (a document should only match
# one template). This is unlikely to be exhaustive of every template FDA has used over the
# decades — same honest caveat the Measurand code already carries — so predicate extraction
# should keep being spot-checked as more documents get indexed, not assumed complete.

SECTION_A_RE = re.compile(r"Predicate\s+Device\s+Names?\s+and\s+510", re.IGNORECASE)
SECTION_A_HEADER_ROW_RE = re.compile(r"^Predicate\s+Name\b.*510", re.IGNORECASE)
SECTION_A_ROW_RE = re.compile(r"^(.+?)\s+(K\d{6}|DEN\d{6})\s*$")

SECTION_B_NAMES_RE = re.compile(r"Predicate\s+device\s+names?\s*\(?s?\)?\s*:", re.IGNORECASE)
SECTION_B_NUMBERS_RE = re.compile(r"Predicate\s+510\(?k\)?\s+numbers?\s*\(?s?\)?\s*:", re.IGNORECASE)
STANDALONE_KNUM_RE = re.compile(r"^(K\d{6}|DEN\d{6})$")

SECTION_C_HEADER_RE = re.compile(r"Predicate\s+510\(?k\)?\s+Numbers?\s*\(?s?\)?\s*:", re.IGNORECASE)
SECTION_C_ROW_RE = re.compile(r"^(K\d{6}|DEN\d{6})\s*-\s*(.+)$")

SECTION_D_HEADER_RE = re.compile(r"Predicate\s+device\s+names?\s*\(Predicate\s+510", re.IGNORECASE)
SECTION_D_ROW_RE = re.compile(r"^(.+?)\s*\((K\d{6}|DEN\d{6})\)\s*$")

NEXT_SECTION_MARKER_RE = re.compile(r"^([A-Z]\.?|[0-9]+\.)\s+[A-Z]")


def _lines_until_next_section(lines: list[str], start_idx: int) -> list[str]:
    """Collect non-empty lines from start_idx until a new lettered/numbered section header
    (e.g. "B Comparison..." or "2. Predicate...") — used by strategies B and C to bound a
    subsection without needing to know its exact end marker in advance.
    """
    out = []
    for ln in lines[start_idx:]:
        stripped = ln.strip()
        if not stripped:
            continue
        if out and NEXT_SECTION_MARKER_RE.match(stripped):
            break
        out.append(stripped)
    return out


def _try_strategy_a(lines: list[str]) -> list[dict]:
    start_idx = None
    for i, ln in enumerate(lines):
        if SECTION_A_RE.search(ln):
            start_idx = i + 1
            break
    if start_idx is None:
        return []

    predicates: list[dict] = []
    consumed_any_row = False
    for ln in lines[start_idx:]:
        stripped = ln.strip()
        if not stripped:
            continue
        if SECTION_A_HEADER_ROW_RE.match(stripped):
            continue
        m = SECTION_A_ROW_RE.match(stripped)
        if m:
            predicates.append({"name": m.group(1).strip(), "k_number": m.group(2).upper()})
            consumed_any_row = True
            continue
        if consumed_any_row:
            break
    return predicates


def _try_strategy_b(lines: list[str]) -> list[dict]:
    names_idx = numbers_idx = None
    for i, ln in enumerate(lines):
        if names_idx is None and SECTION_B_NAMES_RE.search(ln):
            names_idx = i + 1
        elif numbers_idx is None and SECTION_B_NUMBERS_RE.search(ln):
            numbers_idx = i + 1
    if names_idx is None or numbers_idx is None:
        return []

    name_lines = [
        l for l in _lines_until_next_section(lines, names_idx)
        if not SECTION_B_NUMBERS_RE.search(l)
    ]
    number_lines = [l for l in _lines_until_next_section(lines, numbers_idx) if STANDALONE_KNUM_RE.match(l)]
    if not name_lines or not number_lines:
        return []
    return [
        {"name": name, "k_number": knum.upper()}
        for name, knum in zip(name_lines, number_lines)
    ]


def _try_strategy_c(lines: list[str]) -> list[dict]:
    start_idx = None
    for i, ln in enumerate(lines):
        if SECTION_C_HEADER_RE.search(ln):
            start_idx = i + 1
            break
    if start_idx is None:
        return []

    predicates: list[dict] = []
    for ln in _lines_until_next_section(lines, start_idx):
        m = SECTION_C_ROW_RE.match(ln)
        if m:
            predicates.append({"name": m.group(2).strip(), "k_number": m.group(1).upper()})
    return predicates


def _try_strategy_d(lines: list[str]) -> list[dict]:
    start_idx = None
    for i, ln in enumerate(lines):
        if SECTION_D_HEADER_RE.search(ln):
            start_idx = i + 1
            break
    if start_idx is None:
        return []

    predicates: list[dict] = []
    for ln in _lines_until_next_section(lines, start_idx):
        m = SECTION_D_ROW_RE.match(ln)
        if m:
            predicates.append({"name": m.group(1).strip(), "k_number": m.group(2).upper()})
    return predicates


def _extract_predicates(line_text: str) -> list[dict]:
    lines = line_text.splitlines()
    for strategy in (_try_strategy_a, _try_strategy_c, _try_strategy_d, _try_strategy_b):
        found = strategy(lines)
        if found:
            return found
    return []


def extract_pdf(pdf_bytes: bytes) -> ExtractedPdf:
    reader = PdfReader(BytesIO(pdf_bytes))
    page_texts = [p.extract_text() or "" for p in reader.pages]
    line_text = "\n".join(page_texts)
    flattened = " ".join(line_text.split())

    result = ExtractedPdf(full_text=line_text)

    measurand = _extract_measurand(flattened)
    if measurand:
        result.measurand_label, result.measurand_value = measurand

    result.predicates = _extract_predicates(line_text)
    return result
