"""Load seed data into the database."""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from backend.app.database import async_session
from backend.app.models import Country


async def load_countries():
    """Load country seed data from JSON file."""
    seed_file = Path(__file__).parent / "countries.json"
    with open(seed_file) as f:
        data = json.load(f)

    async with async_session() as db:
        for entry in data["countries"]:
            # Upsert: update if exists, insert if not
            result = await db.execute(
                select(Country).where(Country.code == entry["code"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.name = entry["name"]
                existing.population = entry["population"]
                existing.continent = entry["continent"]
                existing.scraper_id = entry["scraper_id"]
                existing.scrape_frequency = entry["scrape_frequency"]
            else:
                country = Country(
                    code=entry["code"],
                    name=entry["name"],
                    population=entry["population"],
                    continent=entry["continent"],
                    scraper_id=entry["scraper_id"],
                    scrape_frequency=entry["scrape_frequency"],
                )
                db.add(country)

        await db.commit()
        print(f"Loaded {len(data['countries'])} countries")


if __name__ == "__main__":
    asyncio.run(load_countries())
