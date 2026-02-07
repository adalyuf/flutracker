"""
Backfill historical UKHSA influenza data (~10 years).

Downloads weekly hospital admission rate data from the UKHSA Dashboard API
year by year, and stores through the standard scraper pipeline.

Usage:
    python -m backend.ingestion.backfill_ukhsa [--from-year 2015] [--to-year 2026] [--regions] [--dry-run]

    # Run inside Docker:
    docker compose exec app python -m backend.ingestion.backfill_ukhsa

    # Run locally (override DB host):
    DATABASE_URL=$DATABASE_URL/flutracker \
        python -m backend.ingestion.backfill_ukhsa
"""

import argparse
import asyncio
import time as time_mod

import structlog

from backend.app.database import async_session
from backend.ingestion.scrapers.uk_ukhsa import UKUKHSAScraper

logger = structlog.get_logger()


async def backfill(
    from_year: int = 2015,
    to_year: int = 2026,
    include_regions: bool = False,
    dry_run: bool = False,
):
    # Use a shorter delay for backfill since we paginate by year (small pages)
    scraper = UKUKHSAScraper(include_regions=include_regions, delay=10)

    print(f"UKHSA backfill: {from_year} → {to_year}"
          f" {'(with regions)' if include_regions else '(nation only)'}")

    if dry_run:
        for year in range(from_year, to_year + 1):
            records = await scraper.fetch_all(since_year=year)
            print(f"  {year}: {len(records)} records")
            await asyncio.sleep(10)  # Rate limit
        await scraper.close()
        print("\nDry run — no data stored.")
        return

    total_stored = 0
    total_skipped = 0

    for year in range(from_year, to_year + 1):
        print(f"\nFetching {year} ...")
        t0 = time_mod.time()

        try:
            records = await scraper.fetch_all(since_year=year)
        except Exception as e:
            logger.error("Failed to fetch year", year=year, error=str(e))
            print(f"  ERROR: {e}")
            continue

        elapsed = time_mod.time() - t0
        print(f"  Fetched {len(records)} records in {elapsed:.1f}s")

        if not records:
            continue

        print(f"  Deduplicating & storing ...")
        t1 = time_mod.time()

        async with async_session() as db:
            unique = await scraper._deduplicate(db, records)
            stored = await scraper._store(db, unique)
            await db.commit()

        elapsed_store = time_mod.time() - t1
        skipped = len(records) - stored
        total_stored += stored
        total_skipped += skipped
        print(f"  Stored {stored} new, skipped {skipped} duplicates "
              f"in {elapsed_store:.1f}s")

        # Rate limit between years
        if year < to_year:
            await asyncio.sleep(10)

    await scraper.close()
    print(f"\nBackfill complete: {total_stored} new records stored, "
          f"{total_skipped} duplicates skipped.")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical UKHSA influenza data"
    )
    parser.add_argument(
        "--from-year", type=int, default=2015,
        help="Start year (default: 2015)",
    )
    parser.add_argument(
        "--to-year", type=int, default=2026,
        help="End year (default: 2026)",
    )
    parser.add_argument(
        "--regions", action="store_true",
        help="Include regional breakdown (slower due to rate limiting)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and count records without storing",
    )
    args = parser.parse_args()
    asyncio.run(backfill(
        from_year=args.from_year,
        to_year=args.to_year,
        include_regions=args.regions,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
