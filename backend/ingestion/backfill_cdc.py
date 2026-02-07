"""
Backfill historical CDC FluView data from 2010 to present.

Downloads all available seasons from the CDC Phase 1 API starting from the
2010-11 season onward, and stores them through the standard scraper pipeline
(with deduplication).

Usage:
    python -m backend.ingestion.backfill_cdc [--from-year 2010] [--dry-run]
"""

import argparse
import asyncio
import sys

import structlog

from backend.app.database import async_session
from backend.ingestion.scrapers.usa_cdc import USACDCScraper

logger = structlog.get_logger()


def parse_season_start_year(label: str) -> int | None:
    """Extract the starting year from a season label like '2010-11'."""
    try:
        return int(label.split("-")[0])
    except (ValueError, IndexError):
        return None


async def backfill(from_year: int = 2010, dry_run: bool = False):
    scraper = USACDCScraper()
    try:
        seasons = await scraper._fetch_seasons()
    except Exception as e:
        logger.error("Failed to fetch seasons from CDC", error=str(e))
        return

    # Filter to seasons starting at from_year onward
    target_seasons = []
    for s in seasons:
        start = parse_season_start_year(s.get("label", ""))
        if start is not None and start >= from_year:
            target_seasons.append(s)

    target_seasons.sort(key=lambda s: s["seasonid"])

    print(f"Found {len(target_seasons)} seasons from {from_year} onward:")
    for s in target_seasons:
        print(f"  {s['label']} (id={s['seasonid']})")

    if dry_run:
        print("\nDry run — not downloading or storing data.")
        await scraper.close()
        return

    total_stored = 0

    for s in target_seasons:
        label = s["label"]
        season_id = s["seasonid"]
        print(f"\nDownloading season {label} ...")

        try:
            records = await scraper._fetch_season_data(season_id)
        except Exception as e:
            logger.error("Failed to download season", season=label, error=str(e))
            continue

        print(f"  Fetched {len(records)} records, deduplicating ...")

        async with async_session() as db:
            # Deduplicate against existing data
            unique = await scraper._deduplicate(db, records)
            stored = await scraper._store(db, unique)
            await scraper._update_last_scraped(db)
            await db.commit()

        print(f"  Stored {stored} new records (skipped {len(records) - stored} duplicates)")
        total_stored += stored

    await scraper.close()
    print(f"\nBackfill complete: {total_stored} total new records stored.")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical CDC FluView data"
    )
    parser.add_argument(
        "--from-year",
        type=int,
        default=2010,
        help="Start year for backfill (default: 2010)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List seasons without downloading",
    )
    args = parser.parse_args()
    asyncio.run(backfill(from_year=args.from_year, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
