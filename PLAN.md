# Flu Tracker — Implementation Plan

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (Client)                      │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Leaflet  │  │ D3 Charts    │  │ Dashboard Tables  │  │
│  │ World Map│  │ (trendlines) │  │ (filter/sort)     │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ REST API
┌───────────────────────▼─────────────────────────────────┐
│                  FastAPI Backend                         │
│  /api/cases  /api/countries  /api/trends  /api/map      │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│          PostgreSQL + TimescaleDB                        │
│  hypertable: flu_cases (time, country, region, city,    │
│              case_count, flu_type, source)               │
└───────────────────────┬─────────────────────────────────┘
                        │ populated by
┌───────────────────────▼─────────────────────────────────┐
│            Data Ingestion Pipeline                       │
│  Scheduled scrapers (one per country/source)            │
│  APScheduler or cron → scraper modules → DB insert      │
└─────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Plain HTML/CSS/JS, D3.js, Leaflet.js |
| Backend API | Python 3.12, FastAPI, Uvicorn |
| Database | PostgreSQL 16 + TimescaleDB extension |
| Data ingestion | Python scrapers (httpx + BeautifulSoup/lxml), APScheduler |
| Deployment | Docker Compose (Postgres + App), Nginx reverse proxy |
| Testing | pytest, Playwright (E2E) |

## Countries in Scope (~80 countries with 10M+ population)

- **Tier 1 — Structured APIs/data feeds exist:** USA (CDC), UK (UKHSA), Australia (DoH), Canada (PHAC), Japan (NIID), South Korea (KDCA), Germany (RKI), France (Santé Publique France)
- **Tier 2 — Published reports/dashboards to scrape:** Brazil (SVS), India (IDSP/NCDC), Mexico (DGE), Russia (Rospotrebnadzor), Indonesia, Turkey, Thailand, etc.
- **Tier 3 — Limited data, WHO FluNet as fallback:** Many African/Central Asian countries — use WHO FluNet (weekly) as baseline, supplement where possible

Note: True daily city-level data is only available from ~10-15 countries. Most national health ministries publish weekly or biweekly. The system handles mixed cadences gracefully.

## Database Schema

```sql
-- Core hypertable
CREATE TABLE flu_cases (
    time            TIMESTAMPTZ NOT NULL,
    country_code    CHAR(2) NOT NULL,
    region          TEXT,
    city            TEXT,
    new_cases       INTEGER NOT NULL,
    flu_type        TEXT,
    source          TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);
SELECT create_hypertable('flu_cases', 'time');

-- Lookup tables
CREATE TABLE countries (
    code            CHAR(2) PRIMARY KEY,
    name            TEXT NOT NULL,
    population      BIGINT,
    continent       TEXT,
    scraper_id      TEXT,
    last_scraped    TIMESTAMPTZ,
    scrape_frequency TEXT DEFAULT 'daily'
);

CREATE TABLE regions (
    id              SERIAL PRIMARY KEY,
    country_code    CHAR(2) REFERENCES countries(code),
    name            TEXT NOT NULL,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    population      BIGINT
);

-- Anomaly detection results
CREATE TABLE anomalies (
    id              SERIAL PRIMARY KEY,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    country_code    CHAR(2) NOT NULL,
    region          TEXT,
    metric          TEXT NOT NULL,
    z_score         DOUBLE PRECISION NOT NULL,
    description     TEXT,
    severity        TEXT CHECK (severity IN ('low', 'medium', 'high', 'critical'))
);

-- Scraper health tracking
CREATE TABLE scrape_log (
    id              SERIAL PRIMARY KEY,
    scraper_id      TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    status          TEXT CHECK (status IN ('running', 'success', 'error')),
    records_fetched INTEGER DEFAULT 0,
    error_message   TEXT
);

-- Indexes
CREATE INDEX idx_cases_country ON flu_cases (country_code, time DESC);
CREATE INDEX idx_cases_region ON flu_cases (country_code, region, time DESC);
CREATE INDEX idx_anomalies_country ON anomalies (country_code, detected_at DESC);
```

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/countries` | List all tracked countries with latest stats |
| `GET /api/cases` | Filtered case data (country, date range, flu_type) |
| `GET /api/cases/by-region` | Breakdown by state/province |
| `GET /api/cases/by-city` | City-level if available |
| `GET /api/trends` | Time-series for trendline charts |
| `GET /api/trends/global` | Global aggregate trend |
| `GET /api/trends/compare` | Compare multiple countries |
| `GET /api/map/geojson` | GeoJSON with case counts for map coloring |
| `GET /api/flu-types` | Subtype breakdown over time |
| `GET /api/summary` | Dashboard summary stats |
| `GET /api/anomalies` | Active anomaly alerts |
| `GET /api/forecast` | Projected trendlines with confidence intervals |
| `GET /api/severity` | Composite severity index per country |
| `GET /api/health` | System health check |

## Frontend Layout

```
┌─────────────────────────────────────────────────────────────┐
│  FluTracker   [N.Hemisphere|S.Hemisphere]  [Updated: 2h ago]│
├──────────────────────┬──────────────────────────────────────┤
│                      │  Trendline Charts (D3)               │
│  Interactive Map     │  - Global / selected country          │
│  (Leaflet)           │  - Subtype stacked area              │
│  - Choropleth        │  - Historical overlay (past 5 yrs)   │
│  - Region bubbles    │  - Forecast projection               │
│  - Anomaly markers   │  - Comparison mode (2-3 countries)   │
│  - Travel risk       │                                      │
│                      │                                      │
├──────────────────────┴──────────────────────────────────────┤
│  ⚠ Anomaly Alerts: [Spain: +340% week-over-week] [...]     │
├─────────────────────────────────────────────────────────────┤
│  Dashboard Table                                            │
│  [Search] [Continent ▾] [Flu Type ▾] [Trend ▾] [Sort ▾]   │
│  ┌──────┬────────┬────────┬───────┬──────────┬───────────┐  │
│  │ Rank │Country │ Cases  │ Trend │ Severity │ Subtypes  │  │
│  │  1   │ USA    │ 45,231 │↑ 12%  │ ██░░ Med │ H3N2 62% │  │
│  │  2   │ Brazil │ 38,102 │↓  3%  │ █░░░ Low │ H1N1 45% │  │
│  └──────┴────────┴────────┴───────┴──────────┴───────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Enhanced Features

### 1. Anomaly Detection
- Z-score on 4-week rolling average vs 12-week baseline
- Flag spikes > 2 standard deviations as alerts
- Alert badges on map (pulsing markers) and in alert bar
- Severity levels: low (2σ), medium (2.5σ), high (3σ), critical (3.5σ+)

### 2. Flu Season Forecasting
- Fit Gaussian curve to current season's trajectory
- Project 2-4 weeks ahead with 80% and 95% confidence intervals
- Show projected peak date and magnitude
- Rendered as dashed line + shaded CI band in D3

### 3. Severity Index
- Composite score (0-100) combining:
  - New cases per 100k population (40% weight)
  - Week-over-week growth rate (30% weight)
  - Positivity rate where available (20% weight)
  - Hospitalization data where available (10% weight)
- Color-coded in table and on map

### 4. Comparison Mode
- Select 2-3 countries from table or map
- Overlay normalized trendlines (per 100k) on same chart
- Align by calendar date or by "weeks since season start"

### 5. Hemisphere Toggle
- Northern hemisphere: season = Oct-Apr
- Southern hemisphere: season = Apr-Oct
- Toggle reframes timeline x-axis to "weeks into flu season"
- Default view shows calendar time

### 6. Historical Context Overlay
- Current season bold line
- Past 5 seasons as faded lines
- Shaded band showing historical min/max range
- Immediately shows if current season is abnormal

### 7. Travel Risk Indicator
- Highlight countries with active outbreaks + high travel connectivity
- Color code by risk level on map
- Tooltip shows: current severity, trend, dominant strain

## Project Structure

```
flu-tracker/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── cases.py
│   │   │   ├── countries.py
│   │   │   ├── trends.py
│   │   │   ├── map_data.py
│   │   │   ├── anomalies.py
│   │   │   ├── forecast.py
│   │   │   └── severity.py
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── aggregation.py
│   │       ├── anomaly_detection.py
│   │       ├── forecasting.py
│   │       ├── severity.py
│   │       └── geo.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── scheduler.py
│   │   ├── base_scraper.py
│   │   └── scrapers/
│   │       ├── __init__.py
│   │       ├── who_flunet.py
│   │       ├── usa_cdc.py
│   │       ├── uk_ukhsa.py
│   │       ├── india_ncdc.py
│   │       ├── brazil_svs.py
│   │       ├── canada_phac.py
│   │       ├── germany_rki.py
│   │       ├── france_spf.py
│   │       ├── japan_niid.py
│   │       ├── australia_doh.py
│   │       └── ...
│   ├── alembic/
│   │   ├── alembic.ini
│   │   ├── env.py
│   │   └── versions/
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_api/
│   │   ├── test_scrapers/
│   │   └── test_services/
│   ├── seed_data/
│   │   └── countries.json
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html
│   ├── css/
│   │   ├── styles.css
│   │   └── responsive.css
│   ├── js/
│   │   ├── app.js
│   │   ├── api.js
│   │   ├── map.js
│   │   ├── charts.js
│   │   ├── dashboard.js
│   │   ├── anomalies.js
│   │   ├── comparison.js
│   │   ├── forecast.js
│   │   └── utils.js
│   └── data/
│       └── world-topo.json
├── docker-compose.yml
├── nginx.conf
├── .env.example
├── PLAN.md
└── README.md
```

## Implementation Order

| Step | What | Files |
|---|---|---|
| 1 | Project scaffolding, Docker Compose, DB setup, config | ~10 |
| 2 | Database models, Alembic migrations, seed countries | ~6 |
| 3 | Base scraper abstraction + WHO FluNet scraper | ~4 |
| 4 | Country-specific scrapers (USA CDC, UK UKHSA, India NCDC) | ~4 |
| 5 | Core API endpoints (cases, countries, trends, map GeoJSON, summary) | ~10 |
| 6 | Anomaly detection service + API | ~3 |
| 7 | Forecasting service + API | ~3 |
| 8 | Severity index service + API | ~3 |
| 9 | Frontend: HTML shell, CSS layout, Leaflet choropleth map | ~5 |
| 10 | Frontend: D3 trendline charts + historical overlay | ~3 |
| 11 | Frontend: Dashboard table with filter/sort/sparklines | ~2 |
| 12 | Frontend: Anomaly alerts bar, comparison mode, hemisphere toggle | ~3 |
| 13 | Frontend: Forecast visualization, travel risk, severity display | ~3 |
| 14 | Wire interactivity (map↔chart↔table sync) | ~2 |
| 15 | Production hardening (caching, rate limiting, error handling, nginx) | ~5 |
| 16 | Tests (unit, integration, E2E) | ~8 |
| 17 | Remaining country scrapers | ~10+ |
