from datetime import datetime
from pydantic import BaseModel, Field


# --- Country schemas ---

class CountryOut(BaseModel):
    code: str
    name: str
    population: int | None = None
    continent: str | None = None
    last_scraped: datetime | None = None
    total_recent_cases: int | None = None
    trend_pct: float | None = None
    severity_score: float | None = None

    model_config = {"from_attributes": True}


# --- Case schemas ---

class CaseOut(BaseModel):
    time: datetime
    country_code: str
    region: str | None = None
    city: str | None = None
    new_cases: int
    flu_type: str | None = None
    source: str

    model_config = {"from_attributes": True}


class RegionCases(BaseModel):
    region: str
    total_cases: int
    flu_types: dict[str, int] = {}
    lat: float | None = None
    lon: float | None = None
    trend_pct: float | None = None
    population: int | None = None


class CasesByRegionOut(BaseModel):
    country_code: str
    period_days: int
    regions: list[RegionCases]


# --- Trend schemas ---

class TrendPoint(BaseModel):
    date: str
    cases: int
    cases_per_100k: float | None = None


class TrendOut(BaseModel):
    country_code: str | None = None
    granularity: str = "week"
    data: list[TrendPoint]


class SeasonData(BaseModel):
    label: str  # e.g. "2023-24"
    data: list[TrendPoint]


class HistoricalSeasonsOut(BaseModel):
    country_code: str | None = None
    current_season: SeasonData
    past_seasons: list[SeasonData]


class ComparisonOut(BaseModel):
    granularity: str = "week"
    series: dict[str, list[TrendPoint]]


# --- Map schemas ---

class MapFeatureProperties(BaseModel):
    country_code: str
    country_name: str
    new_cases_7d: int
    cases_per_100k: float | None = None
    trend_pct: float | None = None
    dominant_flu_type: str | None = None
    severity_score: float | None = None


# --- Anomaly schemas ---

class AnomalyOut(BaseModel):
    id: int
    detected_at: datetime
    country_code: str
    region: str | None = None
    metric: str
    z_score: float
    description: str | None = None
    severity: str

    model_config = {"from_attributes": True}


# --- Forecast schemas ---

class ForecastPoint(BaseModel):
    date: str
    predicted_cases: float
    lower_80: float
    upper_80: float
    lower_95: float
    upper_95: float


class ForecastOut(BaseModel):
    country_code: str
    forecast_weeks: int
    data: list[ForecastPoint]
    peak_date: str | None = None
    peak_magnitude: float | None = None


# --- Severity schemas ---

class SeverityOut(BaseModel):
    country_code: str
    country_name: str
    score: float = Field(ge=0, le=100)
    components: dict[str, float]
    level: str  # low, moderate, high, very_high, critical


# --- Flu type schemas ---

class FluTypeBreakdown(BaseModel):
    flu_type: str
    count: int
    percentage: float


class FluTypesOut(BaseModel):
    country_code: str | None = None
    period_days: int
    breakdown: list[FluTypeBreakdown]


# --- Summary schemas ---

class SummaryOut(BaseModel):
    total_countries_tracked: int
    total_cases_7d: int
    total_cases_28d: int
    global_trend_pct: float
    top_countries: list[CountryOut]
    active_anomalies: int
    dominant_global_flu_type: str | None = None
    last_updated: datetime


# --- Health schemas ---

class HealthOut(BaseModel):
    status: str
    database: str
    scrapers_active: int
    last_scrape: datetime | None = None
