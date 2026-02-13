# Claude Code Notes

## Project Overview
Global influenza surveillance dashboard: FastAPI backend + PostgreSQL + vanilla JS/D3/Leaflet frontend, deployed on Railway (app + managed Postgres).

## Deployment
- **Production**: Railway (project `flutracker`, service `pure-heart` + Postgres plugin)
  - App service builds from `backend/Dockerfile`, FastAPI serves both API and static frontend
  - Postgres plugin provides `DATABASE_URL` (internal: `postgres.railway.internal:5432`)
  - Public DB URL uses `interchange.proxy.rlwy.net:24493` (for running backfills locally)
  - No nginx — FastAPI mounts `frontend/` via `StaticFiles` at `/`
  - Railway CLI: `railway service pure-heart && railway logs` to check app logs
- **Local**: `docker compose up` runs postgres:16-alpine + app on port 80
  - `.env` has `DATABASE_URL` pointing to `@db:5432` (Docker internal hostname)
  - To run scripts locally against Railway DB, override with public URL:
    ```bash
    export DATABASE_URL="postgresql+asyncpg://postgres:PASSWORD@interchange.proxy.rlwy.net:24493/railway"
    export DATABASE_URL_SYNC="postgresql://postgres:PASSWORD@interchange.proxy.rlwy.net:24493/railway"
    ```
- **Config auto-detection**: `config.py` auto-converts plain `postgresql://` URLs (Railway format) to `postgresql+asyncpg://` for the async engine

## CDC FluView API (Phase 1)
- **Init endpoint**: `https://gis.cdc.gov/grasp/fluView1/Phase1IniP`
  - Returns season metadata (seasonid, label, MMWR weeks, states, activity levels)
  - Response is JSON wrapped in an XML `<string>` tag — must strip XML before parsing
  - Season IDs are arbitrary integers (48=2008-09, 65=2025-26), not years
  - Key in response is lowercase `"seasons"` (not `"Seasons"`)

- **Download endpoint**: `https://gis.cdc.gov/grasp/fluView1/Phase1DownloadDataP/{seasonid}`
  - Returns ~13MB per request — double-encoded JSON (JSON string inside JSON)
  - **Important**: Every season ID returns ALL historical data (~48,692 entries across all 18 seasons), not just that season. So downloading one season is sufficient to get everything.
  - Fields: `statename`, `activity_level` (0-13 string), `activity_level_label`, `weekend` (format: "Dec-27-2025"), `weeknumber`, `season`, `url`, `website`
  - Activity levels: 0=Insufficient Data, 1-3=Minimal, 4-5=Low, 6-7=Moderate, 8-10=High, 11-13=Very High
  - Covers 59 jurisdictions (50 states + DC + territories)

- Both endpoints use `_unwrap_cdc_json()` in `usa_cdc.py` to handle the XML wrapping and double-encoding.

## Backfill Scripts
All backfills use batch deduplication (single SELECT + Python set lookup) for fast inserts even over network connections. Run against Railway DB by setting `DATABASE_URL` and `DATABASE_URL_SYNC` to the public proxy URL.

- `python -m backend.ingestion.backfill_cdc [--from-year 2010] [--dry-run]`
  - Downloads CDC historical data and stores via the standard scraper pipeline
  - Since the download endpoint returns all seasons regardless of season ID requested, only the first season download actually inserts records; the rest are all duplicates
  - Backfill has been run on Railway: 758,128 records (~8 min)

- `python -m backend.ingestion.backfill_flunet [--from-year 2016] [--to-year 2026] [--dry-run]`
  - Downloads WHO FluNet global data year-by-year via xMart OData API
  - ~88k records for 10 years across ~168 countries
  - Backfill has been run on Railway: 87,920 records (~3 min). 2026 year fails (no data yet).

- `python -m backend.ingestion.backfill_ukhsa [--from-year 2015] [--to-year 2026] [--regions] [--dry-run]`
  - Downloads UKHSA hospital admission rate data year-by-year
  - ~411 nation-level records for 10 years; `--regions` adds 9 UKHSA regions (slower due to rate limiting)
  - Backfill has been run on Railway: 411 records

- `python -m backend.ingestion.backfill_brazil [--from-year 2019] [--to-year 2025] [--dry-run]`
  - Downloads SRAG CSV files from OpenDataSUS S3, filters flu-confirmed cases
  - Aggregates by state + epi week + flu type; provides 27-state breakdown for Brazil
  - CSV files are 100-320MB each, streamed row-by-row to avoid memory issues
  - Frozen bank URLs (2019-2024) are hardcoded; current year URL is scraped from the dataset page
  - Backfill has been run on Railway: ~11k records. CSV streaming is slow for COVID-era years (2020-2021 have 1M+ rows, take ~20-40 min each).

## Config Gotcha
`backend/app/config.py` uses pydantic-settings with `extra="ignore"` because the `.env` file contains Docker Compose variables (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) that aren't declared in the Settings class.

## Scraper Architecture
- All scrapers extend `BaseScraper` in `backend/ingestion/base_scraper.py`
- Interface: `fetch_latest() -> list[FluCaseRecord]`, run via `BaseScraper.run(db)`
- Scheduler in `backend/ingestion/scheduler.py` — CDC runs every 6 hours at :15
- Scraper class name `USACDCScraper` and import path are used directly in the scheduler
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

## UKHSA Dashboard API
- **Endpoint**: `https://api.ukhsa-dashboard.data.gov.uk/themes/infectious_disease/sub_themes/respiratory/topics/Influenza/geography_types/{geo_type}/geographies/{geo}/metrics/{metric}`
- **Swagger**: `https://api.ukhsa-dashboard.data.gov.uk/api/swagger/`
- Topic name is `Influenza` (capital I) — case-sensitive
- Page size max is **365**; paginate with `page` param
- **Aggressively rate-limited**: needs 8-15s delay between requests; empty 200 response = rate limited
- Data covers **England only** (Scotland/Wales/NI have separate systems)
- Key metrics: `influenza_healthcare_hospitalAdmissionRateByWeek` (from 2015), `influenza_testing_positivityByWeek` (from 2017), `influenza_healthcare_ICUHDUadmissionRateByWeek`
- Geographies: Nation (`England`), UKHSA Region (9 regions), UKHSA Super-Region (4 regions)
- `metric_value` for hospital admissions is a **rate per 100k** — scraper converts to estimated cases using population
- Filter params: `age` (use `all`), `year`, `epiweek`, `page_size`
- UKHSA records use: `country_code="GB"`, `source="uk_ukhsa"`, `region=None` (or region name with `--regions`)

## Brazil OpenDataSUS SIVEP-Gripe
- **Data source**: OpenDataSUS SRAG CSV files on S3
- **Dataset page**: `https://dadosabertos.saude.gov.br/dataset/srag-2019-a-2026`
- **S3 pattern**: `https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/{year}/INFLUD{yy}-{date}.csv`
- Old InfoGripe API (`info.gripe.fiocruz.br`) is **dead** (ECONNREFUSED) — do not use
- CSV files are semicolon-delimited, 100-320MB, ~194 columns per record
- Updated weekly on Wednesdays; frozen banks (closed years) have stable filenames
- **Key columns**: `SG_UF_NOT` (state code), `SEM_NOT` (epi week), `DT_NOTIFIC` (notification date), `CLASSI_FIN` (final classification), `POS_PCRFLU` (PCR flu positive), `TP_FLU_PCR` (flu type), `PCR_FLUASU` (flu A subtype)
- **Flu filter**: `CLASSI_FIN=1` (SRAG by influenza) OR `POS_PCRFLU=1` (PCR positive for flu)
- **Flu type mapping**: TP_FLU_PCR=1+PCR_FLUASU=1→H1N1pdm09, =2→H3N2, other→A (unsubtyped); TP_FLU_PCR=2→B; else→unknown
- Brazil SVS records use: `country_code="BR"`, `source="brazil_svs"`, `region=<state name>`, `flu_type=<subtype>`
- Scraper streams CSV to avoid loading 300MB into memory; uses `httpx` streaming + `csv.reader`
- `fetch_year(year)` method available for backfill (uses frozen URLs for 2019-2024, scrapes dataset page for current year)

## Historical Seasons Endpoint
- `GET /api/trends/historical-seasons?country=US&seasons=5`
- Flu season = Oct 1 → Sep 30 (northern hemisphere)
- Returns current season + N past seasons, each with weekly data indexed by week-of-season (0 = first week of Oct)
- `date` field in TrendPoint is repurposed as week-of-season string (e.g., "0", "5", "12")
- Timezone gotcha: PostgreSQL `date_trunc` returns tz-aware datetimes; season boundaries must be tz-aware too (fixed with `timezone.utc`)
- Route registered before `/trends` to avoid FastAPI path conflicts

## Data Model
- `flu_cases` table (plain PostgreSQL, no TimescaleDB) with columns: `time`, `country_code`, `region`, `city`, `new_cases`, `flu_type`, `source`
- CDC records use: `country_code="US"`, `source="usa_cdc"`, `region=<state name>`, `flu_type=None`
- `new_cases` for CDC is an estimate mapped from ILI activity level (0-13) since the API provides intensity levels, not raw counts
- FluNet records use: `country_code=<ISO2>`, `source="who_flunet"`, `region=None`, `flu_type=<subtype>`
- UKHSA records use: `country_code="GB"`, `source="uk_ukhsa"`, `region=None` or region name
- Brazil SVS records use: `country_code="BR"`, `source="brazil_svs"`, `region=<state name>`, `flu_type=<subtype>`
- As of 2026-02-10: ~860k total records on Railway (758k CDC + 88k FluNet + 411 UKHSA + ~11k Brazil SVS)

## State/Province Drill-Down (Completed 2026-02-10)
- Dashboard table rows for US and BR show expand chevrons (▸/▾) that reveal state-level sub-rows
- Map shows state-level choropleth when clicking US or BR (TopoJSON loaded on demand)
- US states: TopoJSON from CDN (`us-atlas@3/states-10m.json`), FIPS code mapping in `map.js`
- Brazil states: bundled at `frontend/data/brazil-states.json` (~179KB), 27 states with `name` and `sigla` properties
- Backend: `GET /api/countries/with-regions` returns country codes with region data; `/api/cases/by-region` enhanced with `trend_pct` and `population`
- Antimeridian fix in `map.js` (`_fixAntimeridian()`) prevents Russia/Fiji from stretching across the map

## Frontend Design Overhaul (Completed 2026-02-12)
- **Typography**: DM Sans (body/headings) + JetBrains Mono (data/mono) via Google Fonts, replacing system font stack
- **Color hierarchy**: Amber/gold (`#F5A623`) as dominant brand accent; cyan reserved for data/health signals; blue demoted to secondary. Semantic roles: amber=interactive, cyan=data, red=danger, green=healthy
- **Header**: SVG virus/crosshair logo icon, live green pulse dot next to "Updated" timestamp, subtle top-to-bottom gradient background
- **Table**: staggered row fade-in animation (first 20 rows), alternating row backgrounds, wider severity bars (80px) with colored glow, sparkline area fills beneath lines
- **Chart animations**: trend line draws in left-to-right via `stroke-dashoffset` (1.2s), area fades in after 400ms delay, data dots cascade in sequentially, subtype bars grow from zero width, historical overlay current-season line animates in
- **Map**: CSS inward box-shadow vignette on `.map-container::after`, amber hover borders on countries, refined popup styling (deeper shadow + border), legend bar with dark tinted background
- **Controls**: all `<select>` elements use custom SVG chevron arrow (`appearance: none`), consistent 32px height across all inputs/selects, amber hover/focus states with subtle ring glow on search input, chart tabs redesigned with bottom-border accent instead of solid fill
- **Fonts loaded via**: `<link>` tags with `preconnect` to Google Fonts in `index.html`

## Devcontainer Setup (Added 2026-02-12)
- `.devcontainer/` with Dockerfile (python:3.12-slim), docker-compose.yml (postgres:16-alpine + app), devcontainer.json
- Postgres runs as `db` service with healthcheck; app service mounts workspace and sets all env vars
- `postCreateCommand` installs pip dependencies; `postStartCommand` auto-starts uvicorn on port 8000 with `--reload`
- Ports 8000 (FastAPI) and 5432 (PostgreSQL) forwarded; VS Code extensions: Python, debugpy, Ruff
- India NCDC scraper removed (no public API); scheduler imports cleaned up

## Updates (Completed 2026-02-13)
- **Dashboard chart controls simplified**:
  - Removed `Trend` and `Forecast` tabs from `frontend/index.html`.
  - `Historical` is now default chart tab (`Charts.currentView = "historical"` in `frontend/js/charts.js`).
  - Forecast is rendered as a dotted extension directly inside Historical view for selected countries (uses `/api/forecast` in `drawHistoricalOverlay()`).
- **Country select toggle behavior**:
  - Clicking a selected country again now clears selection (`FluMap.selectCountry()` dispatches `countrySelected` with `code=null`).
  - App handler clears table highlight and map drill-down layers on deselect.
- **Historical endpoint output migrated to calendar dates**:
  - `/api/trends/historical-seasons` now returns `date` as `YYYY-MM-DD` instead of week-of-season indexes.
  - Historical chart parser supports both new date format and legacy numeric week offsets for backward compatibility.
- **New Genomics page added (separate from dashboard)**:
  - New standalone page: `frontend/genomics.html` with dedicated assets:
    - `frontend/js/genomics.js`
    - `frontend/css/genomics.css`
  - Existing dashboard page at `/` was not replaced.
- **New Genomics backend API**:
  - New model: `GenomicSequence` in `backend/app/models.py`
  - New router: `backend/app/routers/genomics.py`
  - Endpoints:
    - `GET /api/genomics/summary`
    - `GET /api/genomics/trends`
    - `GET /api/genomics/countries`
  - Router registered in `backend/app/main.py`.
- **Genomics backfill script**:
  - Added `python -m backend.ingestion.backfill_genomics --years N`.
  - Source used: Nextstrain seasonal flu datasets (`h3n2`, `h1n1pdm`, `vic`, `yam`; prefers 12y datasets, falls back to 6y/2y).
  - Stores sequence metadata (sample date, country, lineage, clade, strain) into `genomic_sequences`.
  - Dedup key: `(source_dataset, strain_name)`.
- **Backfill verification run on production DB**:
  - `--years 1` inserted 425 records.
  - `--years 10` inserted 4,726 records.
  - Verified total in DB after full run: `total_sequences=5151`, `country_codes=75`.
- **Genomics UX interactions**:
  - Added chart tooltips on clade hover with month + sequence count.
  - Added click-to-pin clade behavior (dim others) and legend hover/click interactions.
- **Tests added/passed**:
  - New API tests: `backend/tests/test_api/test_genomics.py`.
  - Seed data updated with genomic rows in `backend/tests/conftest.py`.
  - Genomics tests passing locally.

## Next Steps
- **India data**: Covered by WHO FluNet (country-level). India has no public flu surveillance API (NCDC/IDSP data is login-gated or PDF-only), so the dedicated India scraper was removed.
- **Brazil SVS `fetch_latest()` downloads full year**: The scheduled scraper downloads the entire current-year CSV (~300MB) every 12 hours. This is wasteful but unavoidable since OpenDataSUS doesn't offer incremental/date-filtered downloads. Could reduce frequency to weekly (data updates Wednesdays).
- **UKHSA regional backfill**: The `--regions` flag exists but hasn't been run yet. Would add 9 UKHSA regions but is slow due to rate limiting (~9 * 12 years * 10s = ~18 min).
- **UKHSA data is low volume**: Only 411 records (nation-level, 1 data point per week). This is because it's admission *rates* converted to estimated counts. Consider also ingesting `influenza_testing_positivityByWeek` (positivity %) as a separate metric if richer UK data is needed.
- **FluNet `flu_type` aggregation**: The historical-seasons endpoint sums all `flu_type` rows for a country/week. If subtype-level historical charts are desired, the endpoint needs a `flu_type` filter or grouped response.
- **Southern hemisphere seasons**: The historical-seasons endpoint hardcodes Oct-Sep (NH). Countries like Australia/Brazil have flu seasons ~Apr-Sep. Could add hemisphere-aware season boundaries.
- **Map/GeoJSON with FluNet data**: The map view likely only shows countries with recent data. With 184 countries now in FluNet, verify the map populates globally and that the time window used for the map is wide enough.
- **Frontend country selector**: With 184 countries having data, the country dropdown/selector should be populated from countries that actually have data, not just the 94 seeded ones.
- **GB data overlap**: UKHSA provides England-specific data under `country_code="GB"`, while FluNet also has GB data. The historical-seasons endpoint and trend charts will sum both sources for GB. May want to deduplicate across sources or clearly separate them.
- **BR data overlap**: Brazil SVS provides state-level data under `country_code="BR"`, while FluNet has country-level BR data (1,165 records). Trend charts for BR will sum both sources. May want to exclude FluNet for BR or clearly separate them.
- **Database indexing**: With ~860k records, queries may benefit from indexes on `(country_code, time)`, `(country_code, source, time)`, and `(country_code, region, time)` if performance degrades.
