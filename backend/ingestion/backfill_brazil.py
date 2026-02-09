"""
Backfill historical Brazil SIVEP-Gripe data (2019-present).

Downloads SRAG CSV files from OpenDataSUS S3, filters flu-confirmed cases,
aggregates by state + epi week + flu type, and stores via standard pipeline.

CSV files are 100-320MB each; streamed to avoid memory issues.

Usage:
    python -m backend.ingestion.backfill_brazil [--from-year 2019] [--to-year 2025] [--dry-run]

    # Run inside Docker:
    docker compose exec app python -m backend.ingestion.backfill_brazil

    # Run locally (override DB host):
    DATABASE_URL=$DATABASE_URL"/flutracker" \
        python -m backend.ingestion.backfill_brazil
"""

import argparse
import asyncio
import time

import structlog

from backend.app.database import async_session
from backend.ingestion.scrapers.brazil_svs import BrazilSVSScraper

logger = structlog.get_logger()


async def backfill(from_year: int = 2019, to_year: int = 2025, dry_run: bool = False):
    scraper = BrazilSVSScraper()

    print(f"Brazil SIVEP-Gripe backfill: {from_year} → {to_year}")

    if dry_run:
        for year in range(from_year, to_year + 1):
            t0 = time.time()
            try:
                records = await scraper.fetch_year(year)
            except Exception as e:
                print(f"  {year}: ERROR — {e}")
                continue
            elapsed = time.time() - t0
            states = set(r.region for r in records)
            total_cases = sum(r.new_cases for r in records)
            print(f"  {year}: {len(records)} records, {total_cases} flu cases "
                  f"across {len(states)} states in {elapsed:.1f}s")
        await scraper.close()
        print("\nDry run — no data stored.")
        return

    total_stored = 0
    total_skipped = 0

    for year in range(from_year, to_year + 1):
        print(f"\nFetching {year} ...")
        t0 = time.time()

        try:
            records = await scraper.fetch_year(year)
        except Exception as e:
            logger.error("Failed to fetch year", year=year, error=str(e))
            print(f"  ERROR: {e}")
            continue

        elapsed_fetch = time.time() - t0
        states = set(r.region for r in records)
        total_cases = sum(r.new_cases for r in records)
        print(f"  Fetched {len(records)} records ({total_cases} cases) "
              f"from {len(states)} states in {elapsed_fetch:.1f}s")

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
        description="Backfill historical Brazil SIVEP-Gripe flu data"
    )
    parser.add_argument(
        "--from-year", type=int, default=2019,
        help="Start year (default: 2019)",
    )
    parser.add_argument(
        "--to-year", type=int, default=2025,
        help="End year (default: 2025)",
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
