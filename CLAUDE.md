# Claude Code Notes

## Project Overview
Global influenza surveillance dashboard: FastAPI backend + PostgreSQL + vanilla JS/D3/Leaflet frontend, deployed on Railway (app + managed Postgres). Uses WHO FluNet as the single global data source for consistent lab-confirmed specimen counts.

## Deployment
- **Production**: Railway (project `flutracker`, service `pure-heart` + Postgres plugin)
  - App service builds from `backend/Dockerfile`, FastAPI serves both API and static frontend
  - Postgres plugin provides `DATABASE_URL` (internal: `postgres.railway.internal:5432`)
  - Public DB URL uses `interchange.proxy.rlwy.net:24493` (for running backfills locally)
  - No nginx — FastAPI mounts `frontend/` via `StaticFiles` at `/`
  - Railway CLI: `railway link --project flutracker`, then `railway service pure-heart && railway logs`
- **Local / Devcontainer**: see "Database Access" section below
- **Config auto-detection**: `config.py` auto-converts plain `postgresql://` URLs (Railway format) to `postgresql+asyncpg://` for the async engine

## Database Access

### Devcontainer (primary dev environment)
- Postgres runs as the `db` service inside the devcontainer's docker-compose
- **Credentials**: `flutracker:devpassword@db:5432/flutracker` (set in `.devcontainer/docker-compose.yml`)
- **psql access**: `psql "postgresql://flutracker:devpassword@db:5432/flutracker"`
- **pg_isready**: `pg_isready -h db -U flutracker`
- **Python scripts**: env vars are already set by devcontainer; to override explicitly:
  ```bash
  export DATABASE_URL="postgresql+asyncpg://flutracker:devpassword@db:5432/flutracker"
  export DATABASE_URL_SYNC="postgresql://flutracker:devpassword@db:5432/flutracker"
  ```
- **Important**: The `.env` file has *different* credentials (`SpanishFlu1920`) meant for standalone `docker compose up`. The devcontainer uses `devpassword`. If psql fails with auth errors, check which credentials match the running Postgres.

### Production (Railway)
- **Internal** (from Railway app service): `postgres.railway.internal:5432` — not reachable from outside Railway
- **Public proxy** (for local scripts/psql): `interchange.proxy.rlwy.net:24493`
- **Get credentials via Railway CLI**:
  ```bash
  railway link --project flutracker
  railway service Postgres
  railway variables --json | python3 -c "import sys,json; print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])"
  ```
- **Run backfills against production**:
  ```bash
  export DATABASE_URL="postgresql+asyncpg://postgres:<PASSWORD>@interchange.proxy.rlwy.net:24493/railway"
  export DATABASE_URL_SYNC="postgresql://postgres:<PASSWORD>@interchange.proxy.rlwy.net:24493/railway"
  python -m backend.ingestion.backfill_flunet --from-year 2016
  ```

### Standalone Docker Compose (without devcontainer)
- `docker compose up` uses `.env` credentials: `flutracker:SpanishFlu1920@db:5432/flutracker`
- Postgres on port 5432, app on port 80

## Data Status (as of 2026-02-13)
Both production and devcontainer databases are synchronized:
- **flu_cases**: 89,405 records, 184 countries, 2016–2026 (FluNet only)
- **genomic_sequences**: ~5,150 records, 75 countries, 52 clades (Nextstrain)
- COVID dip in 2020–2021 is expected (fewer flu specimens submitted globally)

## Backfill Scripts
All backfills use batch deduplication (single SELECT + Python set lookup) for fast inserts. Run against the appropriate DB by setting `DATABASE_URL` and `DATABASE_URL_SYNC`.

- `python -m backend.ingestion.backfill_flunet [--from-year 2016] [--to-year 2026] [--dry-run]`
  - Downloads WHO FluNet global data year-by-year via xMart OData API
  - ~89k records for 10 years across ~168 countries (~3 min)
  - **Gotcha**: If running against a DB that already has partial data for a year, the dedup logic handles it. But if the existing data was from a different source (e.g., old CDC records), truncate `flu_cases` first to avoid mixing sources.

- `python -m backend.ingestion.backfill_genomics [--years 10]`
  - Downloads Nextstrain seasonal flu datasets (h3n2, h1n1pdm, vic, yam)
  - ~5k records for 10 years across 75 countries
  - Dedup key: `(source_dataset, strain_name)`

## Config Gotcha
`backend/app/config.py` uses pydantic-settings with `extra="ignore"` because the `.env` file contains Docker Compose variables (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) that aren't declared in the Settings class.

## Scraper Architecture
- All scrapers extend `BaseScraper` in `backend/ingestion/base_scraper.py`
- Interface: `fetch_latest() -> list[FluCaseRecord]`, run via `BaseScraper.run(db)`
- Scheduler in `backend/ingestion/scheduler.py` — FluNet runs every 6 hours, anomaly detection runs 4x daily
- Only one scraper remains: `WHOFluNetScraper` (country-specific scrapers for CDC, UKHSA, Brazil SVS were removed to eliminate double-counting with incompatible data definitions)
- HTTP client: httpx with 30s timeout, 3 retries with exponential backoff (tenacity)

## WHO FluNet API (xMart OData)
- **Endpoint**: `https://xmart-api-public.who.int/FLUMART/VIW_FNT`
- Old Azure Front Door URL (`frontdoor-l4uikgap6gz3m.azurefd.net`) is **dead** — do not use
- OData format: default is JSON (no `$format` param), also supports `$format=csv`
- **Important**: `$format=json` is NOT valid — omit the param for JSON
- Max `$top` is 120,000 records per request
- Pagination via `@odata.nextLink` in response
- Filter by `ISOYW` (compact year+week, e.g., 202401) for efficient range queries
- `ISO2` field = 2-letter country code; subtype fields: `AH1N12009`, `AH3`, `AH5`, `INF_A`, `BVIC`, `BYAM`, `INF_B`, `INF_ALL`
- FluNet records use: `country_code=<ISO2>`, `source="who_flunet"`, `flu_type=<subtype>`
- Subtype parsing: specific subtypes (AH1N12009, AH3, BVIC, BYAM) are preferred over aggregates (INF_A, INF_B) to avoid double-counting

## Historical Seasons Endpoint
- `GET /api/trends/historical-seasons?country=US&seasons=5`
- Flu season = Oct 1 → Sep 30 (northern hemisphere)
- Returns current season + N past seasons, each with weekly data indexed by week-of-season (0 = first week of Oct)
- `date` field in TrendPoint is repurposed as week-of-season string (e.g., "0", "5", "12")
- Timezone gotcha: PostgreSQL `date_trunc` returns tz-aware datetimes; season boundaries must be tz-aware too (fixed with `timezone.utc`)
- Route registered before `/trends` to avoid FastAPI path conflicts

## Data Model
- **`flu_cases`** table: `time`, `country_code`, `region`, `city`, `new_cases`, `flu_type`, `source`
  - All records use `source="who_flunet"`, `region=None`, `flu_type=<subtype>`
  - FluNet provides country-level data only (no state/region breakdown)
- **`genomic_sequences`** table: `sample_date`, `country_code`, `country_name`, `lineage`, `clade`, `strain_name`, `source`, `source_dataset`
  - Source: Nextstrain seasonal flu datasets

## Dashboard Layout
- **Top row**: Global map (choropleth, cases per 100k) + Historical comparison chart
- **Middle row**: Clade trends (1yr, genomics stacked area) + Subtype trends (1yr, flu type stacked area)
  - Clade chart uses cool green-blue palette; subtype chart uses warm amber-red palette
  - Both rendered by `MiniCharts` module in `frontend/js/mini-charts.js`
  - Clade panel links to full genomics dashboard (`genomics.html`)
  - Backend endpoints: `GET /api/genomics/trends?years=1`, `GET /api/flu-types/trends?days=365`
- **Bottom**: Country dashboard table with search/filter/sort
- **Map**: Locked to cases-per-100k metric (no dropdown), color scale calibrated for FluNet lab-confirmed data (0–40+ per 100k range)

## Devcontainer Setup
- `.devcontainer/` with Dockerfile (python:3.12-slim), docker-compose.yml (postgres:16-alpine + app), devcontainer.json
- Postgres runs as `db` service with healthcheck; app service mounts workspace and sets all env vars
- `postCreateCommand` installs pip dependencies; `postStartCommand` runs `.devcontainer/start.sh` which waits for DB, runs migrations, seeds countries, then starts uvicorn on port 8000 with `--reload`
- Ports 8000 (FastAPI) and 5432 (PostgreSQL) forwarded; VS Code extensions: Python, debugpy, Ruff

## Frontend Design
- **Typography**: DM Sans (body/headings) + JetBrains Mono (data/mono) via Google Fonts
- **Color hierarchy**: Amber/gold (`#F5A623`) as dominant brand accent; cyan reserved for data/health signals; blue demoted to secondary
- **Chart animations**: trend line draws in left-to-right via `stroke-dashoffset`, area fades in after delay, data dots cascade in sequentially
- **Map**: CSS inward box-shadow vignette, amber hover borders on countries, legend bar with "per 100k" unit label
- **Controls**: custom SVG chevron arrows on selects, consistent 32px height, amber hover/focus states

## Next Steps
- **FluNet `flu_type` aggregation**: The historical-seasons endpoint sums all `flu_type` rows for a country/week. If subtype-level historical charts are desired, the endpoint needs a `flu_type` filter or grouped response.
- **Frontend country selector**: With 184 countries having data, the country dropdown/selector should be populated from countries that actually have data, not just the 94 seeded ones.
- **Database indexing**: With ~89k records, queries may benefit from indexes on `(country_code, time)` and `(country_code, source, time)` if performance degrades.
