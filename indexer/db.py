"""SQLite index: 510(k) devices, their PDF text/measurand, the predicate citation
graph, and the resulting biomarker matches (confirmed via the tiered text-matching
pipeline, or inferred via predicate chain / panel-keyword tier).
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "index.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
  k_number TEXT PRIMARY KEY,
  source TEXT NOT NULL,              -- '510k' (kept generic for future 510(k)-adjacent sources)
  device_name TEXT,
  openfda_device_name TEXT,
  applicant TEXT,
  decision_description TEXT,
  decision_date TEXT,
  advisory_committee TEXT,
  advisory_committee_description TEXT,
  product_code TEXT,
  raw_json TEXT
);

CREATE TABLE IF NOT EXISTS pdf_text (
  k_number TEXT PRIMARY KEY REFERENCES devices(k_number),
  fetched_at TEXT,
  source_url TEXT,
  full_text TEXT,
  measurand_label TEXT,
  measurand_value TEXT,
  fetch_error TEXT
);

CREATE TABLE IF NOT EXISTS predicates (
  device_k TEXT NOT NULL,
  predicate_k TEXT NOT NULL,
  predicate_name TEXT,
  PRIMARY KEY (device_k, predicate_k)
);

CREATE TABLE IF NOT EXISTS biomarker_matches (
  k_number TEXT NOT NULL,
  biomarker_key TEXT NOT NULL,
  match_mode TEXT NOT NULL,          -- 'exact'|'broad'|'antigen-only'|'fused-anti'|'wordform'
                                      -- |'ai-suggested'|'umls'|'predicate'|'gudid' — 'expansion'
                                      -- (matching.py's raw tier tag) is relabeled to
                                      -- 'ai-suggested'/'umls' before being stored here, per the
                                      -- AI engine that actually resolved it (indexer/lookup.py)
  confidence TEXT NOT NULL,          -- 'confirmed' | 'inferred'
  via_k_number TEXT,
  PRIMARY KEY (k_number, biomarker_key, match_mode)
);

CREATE INDEX IF NOT EXISTS idx_matches_biomarker ON biomarker_matches(biomarker_key, confidence);
CREATE INDEX IF NOT EXISTS idx_predicates_device ON predicates(device_k);

-- AI-resolved {full, search} per term, keyed by expansion_key(term) — see indexer/ai_expansion.py.
-- Replaces the old hand-curated dictionary.json; caching this is what makes searching hundreds
-- of biomarkers practical without re-asking the AI for a term it's already answered.
CREATE TABLE IF NOT EXISTS expansion_cache (
  term_key TEXT PRIMARY KEY,
  full TEXT,
  search TEXT,
  source TEXT,                       -- 'local-llm' | 'umls' | 'none'
  generated_at TEXT
);

-- Whether a term's full lookup pipeline (confirmed tiers + GUDID + predicate propagation) has
-- already run, at least once. Needed because zero rows in biomarker_matches for a key is
-- ambiguous without a static dictionary to consult — it could mean "never searched" or
-- "searched, genuinely zero matches." This table is the only thing that disambiguates the two.
CREATE TABLE IF NOT EXISTS searched_terms (
  term_key TEXT PRIMARY KEY,
  searched_at TEXT
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_device(conn: sqlite3.Connection, record: dict, source: str) -> None:
    k_number = record.get("k_number")
    device_name = record.get("device_name")
    openfda = record.get("openfda") or {}
    openfda_device_name = openfda.get("device_name")
    if isinstance(openfda_device_name, list):
        openfda_device_name = "; ".join(openfda_device_name)

    # `source` distinguishes which FDA dataset a device row came from (510k today; kept
    # generic, not hardcoded to "510k" throughout, so a future additional 510(k)-adjacent
    # source — e.g. GUDID or Registration & Listing — can reuse this same table/column).
    normalized = dict(record)
    normalized["source"] = source

    conn.execute(
        """INSERT INTO devices (k_number, source, device_name, openfda_device_name, applicant,
             decision_description, decision_date, advisory_committee,
             advisory_committee_description, product_code, raw_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(k_number) DO UPDATE SET
             source=excluded.source, device_name=excluded.device_name,
             openfda_device_name=excluded.openfda_device_name, applicant=excluded.applicant,
             decision_description=excluded.decision_description, decision_date=excluded.decision_date,
             advisory_committee=excluded.advisory_committee,
             advisory_committee_description=excluded.advisory_committee_description,
             product_code=excluded.product_code, raw_json=excluded.raw_json""",
        (
            k_number, source, device_name, openfda_device_name,
            record.get("applicant"),
            normalized.get("decision_description"),
            record.get("decision_date"),
            record.get("advisory_committee"), record.get("advisory_committee_description"),
            record.get("product_code"), json.dumps(normalized),
        ),
    )


def upsert_pdf_text(conn: sqlite3.Connection, k_number: str, fetched_at: str, source_url: str | None,
                     full_text: str | None, measurand_label: str | None, measurand_value: str | None,
                     fetch_error: str | None) -> None:
    conn.execute(
        """INSERT INTO pdf_text (k_number, fetched_at, source_url, full_text, measurand_label,
             measurand_value, fetch_error)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(k_number) DO UPDATE SET
             fetched_at=excluded.fetched_at, source_url=excluded.source_url,
             full_text=excluded.full_text, measurand_label=excluded.measurand_label,
             measurand_value=excluded.measurand_value, fetch_error=excluded.fetch_error""",
        (k_number, fetched_at, source_url, full_text, measurand_label, measurand_value, fetch_error),
    )


def already_fetched(conn: sqlite3.Connection, k_number: str) -> bool:
    row = conn.execute("SELECT 1 FROM pdf_text WHERE k_number = ?", (k_number,)).fetchone()
    return row is not None


def insert_predicates(conn: sqlite3.Connection, device_k: str, predicates: list[dict]) -> None:
    for p in predicates:
        conn.execute(
            "INSERT OR REPLACE INTO predicates (device_k, predicate_k, predicate_name) VALUES (?, ?, ?)",
            (device_k, p["k_number"], p["name"]),
        )


def insert_match(conn: sqlite3.Connection, k_number: str, biomarker_key: str, match_mode: str,
                  confidence: str, via_k_number: str | None = None) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO biomarker_matches (k_number, biomarker_key, match_mode, confidence, via_k_number)
           VALUES (?, ?, ?, ?, ?)""",
        (k_number, biomarker_key, match_mode, confidence, via_k_number),
    )


def clear_matches_for_biomarker(conn: sqlite3.Connection, biomarker_key: str) -> None:
    conn.execute("DELETE FROM biomarker_matches WHERE biomarker_key = ?", (biomarker_key,))


def get_expansion_cache_entry(conn: sqlite3.Connection, term_key: str) -> tuple[dict | None, str] | None:
    """Returns (expansion, source) if this term has been asked of the AI before, or None if it
    hasn't been cached at all yet. `expansion` is None (with source='none') when the AI was
    already asked and genuinely found nothing — distinct from "never asked," which is what the
    None-return case means; callers use this distinction to avoid re-asking a hard term on every
    single search while still resolving a genuinely new one.
    """
    row = conn.execute(
        "SELECT full, search, source FROM expansion_cache WHERE term_key = ?", (term_key,)
    ).fetchone()
    if row is None:
        return None
    if row["source"] == "none":
        return None, "none"
    expansion = {"full": row["full"]}
    if row["search"]:
        expansion["search"] = row["search"]
    return expansion, row["source"]


def upsert_expansion_cache(conn: sqlite3.Connection, term_key: str, expansion: dict | None,
                            source: str, generated_at: str) -> None:
    conn.execute(
        """INSERT INTO expansion_cache (term_key, full, search, source, generated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(term_key) DO UPDATE SET
             full=excluded.full, search=excluded.search, source=excluded.source,
             generated_at=excluded.generated_at""",
        (term_key, (expansion or {}).get("full"), (expansion or {}).get("search"), source, generated_at),
    )


def already_searched(conn: sqlite3.Connection, term_key: str) -> bool:
    row = conn.execute("SELECT 1 FROM searched_terms WHERE term_key = ?", (term_key,)).fetchone()
    return row is not None


def mark_searched(conn: sqlite3.Connection, term_key: str, searched_at: str) -> None:
    conn.execute(
        """INSERT INTO searched_terms (term_key, searched_at) VALUES (?, ?)
           ON CONFLICT(term_key) DO UPDATE SET searched_at=excluded.searched_at""",
        (term_key, searched_at),
    )
