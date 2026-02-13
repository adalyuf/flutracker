"""Backfill influenza genomic sequences from Nextstrain datasets.

Usage:
  python -m backend.ingestion.backfill_genomics --years 10
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from backend.app.database import async_session
from backend.app.models import Country, GenomicSequence

logger = structlog.get_logger()

NEXTSTRAIN_DATASETS = {
    "h3n2": [
        "https://data.nextstrain.org/seasonal-flu_h3n2_ha_12y.json",
        "https://data.nextstrain.org/seasonal-flu_h3n2_ha_6y.json",
        "https://data.nextstrain.org/seasonal-flu_h3n2_ha_2y.json",
    ],
    "h1n1pdm": [
        "https://data.nextstrain.org/seasonal-flu_h1n1pdm_ha_12y.json",
        "https://data.nextstrain.org/seasonal-flu_h1n1pdm_ha_6y.json",
        "https://data.nextstrain.org/seasonal-flu_h1n1pdm_ha_2y.json",
    ],
    "vic": [
        "https://data.nextstrain.org/seasonal-flu_vic_ha_12y.json",
        "https://data.nextstrain.org/seasonal-flu_vic_ha_6y.json",
        "https://data.nextstrain.org/seasonal-flu_vic_ha_2y.json",
    ],
    "yam": [
        "https://data.nextstrain.org/seasonal-flu_yam_ha_12y.json",
        "https://data.nextstrain.org/seasonal-flu_yam_ha_6y.json",
        "https://data.nextstrain.org/seasonal-flu_yam_ha_2y.json",
    ],
}

COUNTRY_ALIASES = {
    "usa": "US",
    "united states": "US",
    "united states of america": "US",
    "uk": "GB",
    "united kingdom": "GB",
}


def _norm_name(value: str) -> str:
    return "".join(ch for ch in value.lower().strip() if ch.isalnum() or ch == " ").strip()


def _parse_collection_date(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%Y-%m":
                dt = dt.replace(day=1)
            elif fmt == "%Y":
                dt = dt.replace(month=1, day=1)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        # decimal year fallback
        year_float = float(text)
        year = int(year_float)
        frac = year_float - year
        return (
            datetime(year, 1, 1, tzinfo=timezone.utc)
            + timedelta(days=int(frac * 365.25))
        )
    except ValueError:
        return None


def _attr_value(node_attrs: dict, key: str) -> Any:
    value = node_attrs.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _iter_leaves(node: dict):
    children = node.get("children") or []
    if not children:
        yield node
        return
    for child in children:
        yield from _iter_leaves(child)


async def _fetch_dataset(client: httpx.AsyncClient, urls: list[str]) -> tuple[str, dict] | tuple[None, None]:
    for url in urls:
        try:
            resp = await client.get(url, timeout=90.0)
            if resp.status_code == 200:
                return url, resp.json()
        except Exception:
            continue
    return None, None


async def run_backfill(years: int):
    since = datetime.now(timezone.utc) - timedelta(days=365 * years)

    async with async_session() as db:
        countries = (await db.execute(select(Country.code, Country.name))).all()
        name_to_code = {_norm_name(name): code for code, name in countries}
        for alias, code in COUNTRY_ALIASES.items():
            name_to_code[_norm_name(alias)] = code

        async with httpx.AsyncClient(
            headers={"User-Agent": "FluTracker/1.0 genomics backfill"},
            follow_redirects=True,
        ) as client:
            inserted = 0
            for lineage, urls in NEXTSTRAIN_DATASETS.items():
                dataset_url, payload = await _fetch_dataset(client, urls)
                if not payload:
                    logger.warning("No dataset found", lineage=lineage)
                    continue

                tree = payload.get("tree")
                if not tree:
                    logger.warning("Dataset missing tree", lineage=lineage, url=dataset_url)
                    continue

                dataset_name = dataset_url.rsplit("/", 1)[-1]
                leaves = list(_iter_leaves(tree))
                strain_names = [leaf.get("name", "") for leaf in leaves if leaf.get("name")]
                existing = set()
                if strain_names:
                    query = (
                        select(GenomicSequence.strain_name)
                        .where(
                            GenomicSequence.source_dataset == dataset_name,
                            GenomicSequence.strain_name.in_(strain_names),
                        )
                    )
                    existing_rows = (await db.execute(query)).all()
                    existing = {r.strain_name for r in existing_rows}

                batch: list[GenomicSequence] = []
                for leaf in leaves:
                    strain = leaf.get("name")
                    if not strain or strain in existing:
                        continue

                    attrs = leaf.get("node_attrs", {})
                    date_value = _attr_value(attrs, "date")
                    if date_value is None:
                        date_value = _attr_value(attrs, "num_date")
                    sample_date = _parse_collection_date(date_value)
                    if not sample_date or sample_date < since:
                        continue

                    country_name = _attr_value(attrs, "country")
                    country_name = str(country_name).strip() if country_name else None
                    country_code = name_to_code.get(_norm_name(country_name)) if country_name else None

                    clade = (
                        _attr_value(attrs, "clade_membership")
                        or _attr_value(attrs, "nextclade")
                        or _attr_value(attrs, "clade")
                    )

                    batch.append(GenomicSequence(
                        sample_date=sample_date,
                        country_code=country_code,
                        country_name=country_name,
                        lineage=lineage,
                        clade=str(clade) if clade else "Unknown",
                        strain_name=strain,
                        source="nextstrain",
                        source_dataset=dataset_name,
                    ))

                for row in batch:
                    db.add(row)
                await db.commit()
                inserted += len(batch)
                logger.info(
                    "Loaded dataset",
                    lineage=lineage,
                    dataset=dataset_name,
                    inserted=len(batch),
                )

            logger.info("Genomics backfill complete", years=years, inserted=inserted)


def main():
    parser = argparse.ArgumentParser(description="Backfill genomic sequence metadata")
    parser.add_argument("--years", type=int, default=10, help="Years to backfill (default: 10)")
    args = parser.parse_args()
    asyncio.run(run_backfill(args.years))


if __name__ == "__main__":
    main()
