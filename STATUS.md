# FluTracker Project Status — 2026-02-07

## Database Contents

| Source | Records | Countries | Year Range |
|--------|---------|-----------|------------|
| CDC FluView (`usa_cdc`) | 47,383 | 1 (US) | 2008-2026 |
| WHO FluNet (`who_flunet`) | 109,504 | 168 | 2016-2026 |
| **Total** | **156,887** | **168** | **2008-2026** |

### WHO FluNet Yearly Breakdown

| Year | Records | Countries |
|------|---------|-----------|
| 2016 | 8,289 | 141 |
| 2017 | 8,022 | 152 |
| 2018 | 10,223 | 162 |
| 2019 | 9,865 | 165 |
| 2020 | 4,268 | 161 |
| 2021 | 2,928 | 130 |
| 2022 | 8,125 | 152 |
| 2023 | 11,011 | 165 |
| 2024 | 20,104 | 168 |
| 2025 | 25,734 | 167 |
| 2026 | 935 | 128 |

Note: 2020-2021 low counts reflect real-world flu suppression during COVID-19.

## Working Scrapers

| Scraper | Status | Schedule | Endpoint |
|---------|--------|----------|----------|
| CDC FluView | Working | Every 6h at :15 | `gis.cdc.gov/grasp/fluView1/` |
| WHO FluNet | Working | Every 6h on startup | `xmart-api-public.who.int/FLUMART/VIW_FNT` |
| UK UKHSA | Not verified | Every 6h at :30 | Unknown status |
| India NCDC | Not verified | Every 12h at :45 | Unknown status |
| Brazil SVS | Not verified | Every 12h at :00 | Unknown status |

## Recent Changes (this session)

### Historical Seasons API + Chart (completed)
- Added `GET /api/trends/historical-seasons?country=US&seasons=5` endpoint
- Returns real seasonal data (Oct-Sep flu seasons) with week-of-season indexing
- Frontend `drawHistoricalOverlay()` now uses real data instead of random noise
- Deleted `_generateHistoricalSeasons()` fake data generator

### WHO FluNet Scraper Fix + Backfill (completed)
- Old Azure Front Door endpoint (`frontdoor-l4uikgap6gz3m.azurefd.net`) is dead
- Rewrote scraper to use WHO xMart public OData API
- Added `fetch_range()` method for flexible year/week queries
- Improved subtype parsing to avoid double-counting (specific subtypes prioritized over aggregates)
- Created `backfill_flunet.py` script and ran 10-year backfill successfully

## Infrastructure
- Docker Compose: 3 containers (app, db/TimescaleDB, nginx)
- All containers healthy and running
- Scheduler running 6 jobs (5 scrapers + anomaly detection)
