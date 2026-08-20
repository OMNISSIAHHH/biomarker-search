"""Orchestrates the full indexer run:

  1. Confirmed matches: run the tiered text-matching pipeline (same logic as the live JS
     tool) for every dictionary biomarker against 510(k). Cheap JSON-only calls, not
     bounded by scope — openFDA's own text search already narrows this.
  2. Populate the full scope population: every 510k device in ADVISORY_COMMITTEES, not just
     the ones step 1 already found by name — this is the point of the predicate crawl, to
     reach devices text search misses entirely.
  3. PDF crawl: fetch + parse (Measurand + predicate table) every scope device not already
     cached. The expensive step; skips anything already in pdf_text from a prior run.
  4. Predicate-chain propagation: mark devices that cite an already-confirmed predicate as
     inferred matches for that biomarker.

Usage: python -m indexer.crawl [--api-key KEY] [--limit-committees IM,CH]
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from indexer import db, pdf_extract
from indexer.matching import fetch_biomarker_matches
from indexer.openfda import DEVICE_510K, fetch_all_in_scope
from indexer.predicate_graph import propagate_predicate_matches
from indexer.scope import ADVISORY_COMMITTEES

DICTIONARY_PATH = Path(__file__).parent.parent / "dictionary.json"


def load_dictionary() -> dict:
    with open(DICTIONARY_PATH, encoding="utf-8") as f:
        return json.load(f)


async def crawl_confirmed_matches(client: httpx.AsyncClient, conn, dictionary: dict,
                                   api_key: str | None = None) -> None:
    for key in dictionary:
        db.clear_matches_for_biomarker(conn, key)

        result = await fetch_biomarker_matches(client, DEVICE_510K, key, dictionary, api_key)
        for r in result["records"]:
            db.upsert_device(conn, r, source="510k")
            db.insert_match(conn, r["k_number"], key, result["match_mode"], "confirmed")
        for r in result.get("panel_candidates", []):
            db.upsert_device(conn, r, source="510k")
            db.insert_match(conn, r["k_number"], key, "panel-candidate", "inferred")

        conn.commit()
        print(
            f"  {key}: {len(result['records'])} 510k confirmed, "
            f"{len(result.get('panel_candidates', []))} panel candidates"
        )


async def populate_scope_devices(client: httpx.AsyncClient, conn, committees: list[str],
                                  api_key: str | None = None) -> None:
    """Every 510k device in the bounded advisory-committee scope, not just the ones already
    found by text matching — the predicate graph's whole value is reaching devices that text
    search misses entirely, so it needs the full population to crawl PDFs for, not a subset.
    """
    records = await fetch_all_in_scope(client, DEVICE_510K, "advisory_committee", committees, api_key)
    for r in records:
        db.upsert_device(conn, r, source="510k")
    conn.commit()
    print(f"  {len(records)} devices in scope ({', '.join(committees)})")


async def crawl_pdfs_in_scope(client: httpx.AsyncClient, conn, committees: list[str],
                               concurrency: int = 5) -> None:
    placeholders = ",".join("?" * len(committees))
    rows = conn.execute(
        f"SELECT k_number FROM devices WHERE advisory_committee IN ({placeholders}) AND source = '510k'",
        committees,
    ).fetchall()
    to_fetch = [r["k_number"] for r in rows if not db.already_fetched(conn, r["k_number"])]
    print(f"  {len(to_fetch)} devices to fetch (of {len(rows)} in scope, rest already cached)")

    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(k_number: str) -> None:
        async with sem:
            fetched_at = datetime.now(timezone.utc).isoformat()
            try:
                pdf_bytes, source_url = await pdf_extract.fetch_decision_pdf(client, k_number)
            except pdf_extract.PdfFetchError as e:
                db.upsert_pdf_text(conn, k_number, fetched_at, None, None, None, None, str(e))
                return
            try:
                extracted = pdf_extract.extract_pdf(pdf_bytes)
            except Exception as e:  # malformed/unparseable PDF — record and move on
                db.upsert_pdf_text(conn, k_number, fetched_at, source_url, None, None, None, f"parse error: {e}")
                return
            db.upsert_pdf_text(
                conn, k_number, fetched_at, source_url, extracted.full_text,
                extracted.measurand_label, extracted.measurand_value, None,
            )
            db.insert_predicates(conn, k_number, extracted.predicates)

    for i in range(0, len(to_fetch), 50):
        batch = to_fetch[i:i + 50]
        await asyncio.gather(*(fetch_one(k) for k in batch))
        conn.commit()
        print(f"  fetched {min(i + 50, len(to_fetch))}/{len(to_fetch)}")


def propagate_all(conn, dictionary: dict) -> None:
    total = 0
    for key in dictionary:
        total += propagate_predicate_matches(conn, key)
    conn.commit()
    print(f"  {total} inferred matches added via predicate chains")


async def run(committees: list[str], api_key: str | None = None) -> None:
    dictionary = load_dictionary()
    conn = db.connect()
    try:
        async with httpx.AsyncClient() as client:
            print("Step 1/4: confirmed text-tier matches (510k)...")
            await crawl_confirmed_matches(client, conn, dictionary, api_key)

            print("Step 2/4: populating full scope device list...")
            await populate_scope_devices(client, conn, committees, api_key)

            print("Step 3/4: PDF crawl (Measurand + predicates) for devices in scope...")
            await crawl_pdfs_in_scope(client, conn, committees)

        print("Step 4/4: predicate-chain propagation...")
        propagate_all(conn, dictionary)
    finally:
        conn.close()
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl and index FDA 510(k) data for the biomarker search tool.")
    parser.add_argument("--api-key", default=None, help="openFDA API key (optional, raises rate limits).")
    parser.add_argument(
        "--committees", default=",".join(ADVISORY_COMMITTEES),
        help=f"Comma-separated advisory committee codes to crawl (default: {','.join(ADVISORY_COMMITTEES)}).",
    )
    args = parser.parse_args()
    committees = [c.strip() for c in args.committees.split(",") if c.strip()]
    asyncio.run(run(committees, args.api_key))


if __name__ == "__main__":
    main()
