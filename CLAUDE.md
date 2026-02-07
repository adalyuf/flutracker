# Claude Code Notes

## Project Overview
Global influenza surveillance dashboard: FastAPI backend + PostgreSQL/TimescaleDB + vanilla JS/D3/Leaflet frontend, deployed via Docker Compose.

## Running Outside Docker
The `.env` file has `DATABASE_URL` pointing to `@db:5432` (Docker internal hostname). When running scripts locally (outside containers), override with:
```bash
DATABASE_URL=$DATABASE_URL/flutracker" python -m <module>
```
Port 5432 is mapped to the host in docker-compose.yml.

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
- `python -m backend.ingestion.backfill_cdc [--from-year 2010] [--dry-run]`
  - Downloads CDC historical data and stores via the standard scraper pipeline
  - Deduplication is row-by-row against the DB (time + country_code + source + region), which is slow for large datasets (~40s per 47k records)
  - Since the download endpoint returns all seasons regardless of season ID requested, only the first season download actually inserts records; the rest are all duplicates.

- `python -m backend.ingestion.backfill_flunet [--from-year 2016] [--to-year 2026] [--dry-run]`
  - Downloads WHO FluNet global data year-by-year via xMart OData API
  - ~112k records for 10 years across ~168 countries
  - Each year takes ~2s to fetch, ~5-9s to deduplicate & store
  - Backfill has been run: 2016-2026 data is loaded (109,504 records)

- `python -m backend.ingestion.backfill_ukhsa [--from-year 2015] [--to-year 2026] [--regions] [--dry-run]`
  - Downloads UKHSA hospital admission rate data year-by-year
  - ~411 nation-level records for 10 years; `--regions` adds 9 UKHSA regions (slower due to rate limiting)
  - Backfill has been run: 2015-2026 nation data loaded (411 records)

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

## Historical Seasons Endpoint
- `GET /api/trends/historical-seasons?country=US&seasons=5`
- Flu season = Oct 1 → Sep 30 (northern hemisphere)
- Returns current season + N past seasons, each with weekly data indexed by week-of-season (0 = first week of Oct)
- `date` field in TrendPoint is repurposed as week-of-season string (e.g., "0", "5", "12")
- Timezone gotcha: PostgreSQL `date_trunc` returns tz-aware datetimes; season boundaries must be tz-aware too (fixed with `timezone.utc`)
- Route registered before `/trends` to avoid FastAPI path conflicts

## Data Model
- `flu_cases` is a TimescaleDB hypertable partitioned by `time`
- CDC records use: `country_code="US"`, `source="usa_cdc"`, `region=<state name>`, `flu_type=None`
- `new_cases` for CDC is an estimate mapped from ILI activity level (0-13) since the API provides intensity levels, not raw counts
- FluNet records use: `country_code=<ISO2>`, `source="who_flunet"`, `region=None`, `flu_type=<subtype>`
- UKHSA records use: `country_code="GB"`, `source="uk_ukhsa"`, `region=None` or region name
- As of 2026-02-07: 157,298 total records (47k CDC + 109k FluNet + 411 UKHSA)

## Next Steps
- **Fix India NCDC and Brazil SVS scrapers**: These are scheduled but likely have broken endpoints (similar to the old FluNet/UKHSA URLs). Test each, find working APIs, rewrite, and backfill.
- **UKHSA regional backfill**: The `--regions` flag exists but hasn't been run yet. Would add 9 UKHSA regions but is slow due to rate limiting (~9 * 12 years * 10s = ~18 min).
- **UKHSA data is low volume**: Only 411 records (nation-level, 1 data point per week). This is because it's admission *rates* converted to estimated counts. Consider also ingesting `influenza_testing_positivityByWeek` (positivity %) as a separate metric if richer UK data is needed.
- **Deduplication performance**: Row-by-row dedup (`_deduplicate` in `BaseScraper`) is O(n) DB queries. For large backfills, consider batch dedup using `INSERT ... ON CONFLICT DO NOTHING` or a temp table approach.
- **FluNet `flu_type` aggregation**: The historical-seasons endpoint sums all `flu_type` rows for a country/week. If subtype-level historical charts are desired, the endpoint needs a `flu_type` filter or grouped response.
- **Southern hemisphere seasons**: The historical-seasons endpoint hardcodes Oct-Sep (NH). Countries like Australia/Brazil have flu seasons ~Apr-Sep. Could add hemisphere-aware season boundaries.
- **Map/GeoJSON with FluNet data**: The map view likely only shows countries with recent data. With 184 countries now in FluNet, verify the map populates globally and that the time window used for the map is wide enough.
- **Frontend country selector**: With 184 countries having data, the country dropdown/selector should be populated from countries that actually have data, not just the 94 seeded ones.
- **GB data overlap**: UKHSA provides England-specific data under `country_code="GB"`, while FluNet also has GB data. The historical-seasons endpoint and trend charts will sum both sources for GB. May want to deduplicate across sources or clearly separate them.
