# FluTracker Project Status — 2026-02-07

## Database Contents

| Source | Records | Countries | Year Range |
|--------|---------|-----------|------------|
| CDC FluView (`usa_cdc`) | 47,383 | 1 (US) | 2008-2026 |
| WHO FluNet (`who_flunet`) | 109,504 | 184 | 2016-2026 |
| UKHSA (`uk_ukhsa`) | 411 | 1 (GB) | 2015-2026 |
| **Total** | **157,298** | **184** | **2008-2026** |

## Working Scrapers

| Scraper | Status | Schedule | Endpoint |
|---------|--------|----------|----------|
| CDC FluView | Working | Every 6h at :15 | `gis.cdc.gov/grasp/fluView1/` |
| WHO FluNet | Working | Every 6h on startup | `xmart-api-public.who.int/FLUMART/VIW_FNT` |
| UK UKHSA | Working | Every 6h at :30 | `api.ukhsa-dashboard.data.gov.uk/...` |
| India NCDC | Not verified | Every 12h at :45 | Likely broken |
| Brazil SVS | Not verified | Every 12h at :00 | Likely broken |

## Changes (this session)

### Historical Seasons API + Chart
- Added `GET /api/trends/historical-seasons?country=US&seasons=5` endpoint
- Returns real seasonal data (Oct-Sep flu seasons) with week-of-season indexing
- Frontend `drawHistoricalOverlay()` now uses real data instead of random noise
- Deleted `_generateHistoricalSeasons()` fake data generator

### WHO FluNet Scraper Fix + Backfill
- Old Azure Front Door endpoint (`frontdoor-l4uikgap6gz3m.azurefd.net`) is dead
- Rewrote scraper to use WHO xMart public OData API
- Added `fetch_range()` method for flexible year/week queries
- Improved subtype parsing to avoid double-counting
- Created `backfill_flunet.py` and ran 10-year backfill (109,504 records)

### UKHSA Scraper Fix + Backfill
- Old endpoints (`ukhsa-dashboard.data.gov.uk/api` and gov.uk HTML scraping) replaced
- Rewrote scraper for `api.ukhsa-dashboard.data.gov.uk` dashboard API
- Uses hospital admission rate metric, converts per-100k rates to estimated cases
- Handles aggressive rate limiting (8-15s delay between requests)
- Created `backfill_ukhsa.py` and ran 10-year backfill (411 records, nation-level)

## Infrastructure
- Docker Compose: 3 containers (app, db/TimescaleDB, nginx)
- All containers healthy and running
- Scheduler running 6 jobs (5 scrapers + anomaly detection)
