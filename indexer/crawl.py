"""Refreshes the foundational, biomarker-agnostic device+PDF corpus the predicate-chain tier
depends on. This has nothing to do with any specific biomarker — it crawls every device in the
bounded advisory-committee scope regardless of which biomarkers anyone will ever search for, so
it's run periodically (independent of what's being searched), not per-term.

  1. Populate the full scope device list: every 510k device in ADVISORY_COMMITTEES — this is
     the point of the predicate crawl, to reach devices text search misses entirely.
  2. PDF crawl: fetch + parse (Measurand + predicate table) every scope device not already
     cached. The expensive step; skips anything already in pdf_text from a prior run.

Actual biomarker lookups (confirmed-match tiers, GUDID cross-check, predicate-chain
propagation) happen lazily and per-term through indexer/lookup.py, called by the local server on
each /biomarker/{term} request — there is no dictionary/biomarker list here or anywhere else;
whatever's searched gets resolved (and cached) on the spot. Run this crawl once before searching
if you want predicate-chain ("inferred via predicate") results available immediately; confirmed
and GUDID results work without it, resolved live on first search either way.

Usage: python -m indexer.crawl [--api-key KEY] [--committees IM,CH]
"""
import argparse
import asyncio
from datetime import datetime, timezone

import httpx

from indexer import db, pdf_extract
from indexer.openfda import DEVICE_510K, fetch_all_in_scope
from indexer.scope import ADVISORY_COMMITTEES


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


async def run(committees: list[str], api_key: str | None = None) -> None:
    conn = db.connect()
    try:
        async with httpx.AsyncClient() as client:
            print("Step 1/2: populating full scope device list...")
            await populate_scope_devices(client, conn, committees, api_key)

            print("Step 2/2: PDF crawl (Measurand + predicates) for devices in scope...")
            await crawl_pdfs_in_scope(client, conn, committees)
    finally:
        conn.close()
    print("Done. Biomarker lookups themselves happen on demand via the local server "
          "(indexer/lookup.py) — nothing biomarker-specific to run here.")


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
