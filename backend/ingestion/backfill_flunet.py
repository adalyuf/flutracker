"""
Backfill historical WHO FluNet data (up to 10 years).

Downloads global influenza surveillance data from the WHO xMart OData API,
year by year, and stores through the standard scraper pipeline with dedup.

Usage:
    python -m backend.ingestion.backfill_flunet [--from-year 2016] [--to-year 2026] [--dry-run]

    # Run inside Docker:
    docker compose exec app python -m backend.ingestion.backfill_flunet

    # Run locally (override DB host):
    DATABASE_URL=$DATABASE_URL"/flutracker" \
        python -m backend.ingestion.backfill_flunet
"""

import argparse
import asyncio
import time

import structlog

from backend.app.database import async_session
from backend.ingestion.scrapers.who_flunet import WHOFluNetScraper

logger = structlog.get_logger()


async def backfill(from_year: int = 2016, to_year: int = 2026, dry_run: bool = False):
    scraper = WHOFluNetScraper()

    print(f"WHO FluNet backfill: {from_year} → {to_year}")

    if dry_run:
        # Just check record counts per year
        for year in range(from_year, to_year + 1):
            records = await scraper.fetch_range(year, 1, year, 53)
            countries = set(r.country_code for r in records)
            print(f"  {year}: {len(records)} records across {len(countries)} countries")
        await scraper.close()
        print("\nDry run — no data stored.")
        return

    total_stored = 0
    total_skipped = 0

    for year in range(from_year, to_year + 1):
        print(f"\nFetching {year} ...")
        t0 = time.time()

        try:
            records = await scraper.fetch_range(year, 1, year, 53)
        except Exception as e:
            logger.error("Failed to fetch year", year=year, error=str(e))
            print(f"  ERROR: {e}")
            continue

        elapsed_fetch = time.time() - t0
        countries = set(r.country_code for r in records)
        print(f"  Fetched {len(records)} records from {len(countries)} countries "
              f"in {elapsed_fetch:.1f}s")

        if not records:
            continue

        print(f"  Deduplicating & storing ...")
        t1 = time.time()

        async with async_session() as db:
            unique = await scraper._deduplicate(db, records)
            stored = await scraper._store(db, unique)
            await db.commit()

        elapsed_store = time.time() - t1
        skipped = len(records) - stored
        total_stored += stored
        total_skipped += skipped
        print(f"  Stored {stored} new, skipped {skipped} duplicates "
              f"in {elapsed_store:.1f}s")

    await scraper.close()
    print(f"\nBackfill complete: {total_stored} new records stored, "
          f"{total_skipped} duplicates skipped.")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical WHO FluNet data"
    )
    parser.add_argument(
        "--from-year", type=int, default=2016,
        help="Start year (default: 2016)",
    )
    parser.add_argument(
        "--to-year", type=int, default=2026,
        help="End year (default: 2026)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and count records without storing",
    )
    args = parser.parse_args()
    asyncio.run(backfill(
        from_year=args.from_year,
        to_year=args.to_year,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
