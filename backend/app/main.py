from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.config import get_settings
from backend.app.database import Base
from backend.app.routers import cases, countries, trends, map_data, anomalies, forecast, severity

settings = get_settings()
logger = structlog.get_logger()


async def _init_db():
    """Create tables and load seed data on first run."""
    from sqlalchemy import text
    from backend.app.database import engine, async_session
    from backend.app.models import Country  # noqa: ensure models loaded

    # Try to enable TimescaleDB; works on TimescaleDB images, skipped on plain Postgres
    has_timescaledb = False
    async with engine.begin() as conn:
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
            has_timescaledb = True
            logger.info("TimescaleDB extension enabled")
        except Exception:
            logger.info("TimescaleDB not available, using plain PostgreSQL")

    async with engine.begin() as conn:
        if has_timescaledb:
            # Check if flu_cases is already a hypertable
            result = await conn.execute(text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM timescaledb_information.hypertables "
                "  WHERE hypertable_name = 'flu_cases'"
                ")"
            ))
            is_hypertable = result.scalar()

            if not is_hypertable:
                await conn.execute(text("DROP TABLE IF EXISTS flu_cases CASCADE"))
                logger.info("Dropped old flu_cases table for hypertable recreation")

        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured")

    # Create hypertable if TimescaleDB is available
    if has_timescaledb:
        async with engine.begin() as conn:
            try:
                await conn.execute(text(
                    "SELECT create_hypertable('flu_cases', 'time', if_not_exists => TRUE, migrate_data => TRUE)"
                ))
                logger.info("Hypertable ensured")
            except Exception as e:
                logger.warning("Hypertable setup note", detail=str(e))

    # Load seed data if countries table is empty
    async with async_session() as db:
        from sqlalchemy import select, func
        count = (await db.execute(select(func.count()).select_from(Country))).scalar()
        if count == 0:
            import json
            from pathlib import Path
            seed_file = Path(__file__).parent.parent / "seed_data" / "countries.json"
            if seed_file.exists():
                with open(seed_file) as f:
                    data = json.load(f)
                for entry in data["countries"]:
                    db.add(Country(
                        code=entry["code"],
                        name=entry["name"],
                        population=entry["population"],
                        continent=entry["continent"],
                        scraper_id=entry["scraper_id"],
                        scrape_frequency=entry["scrape_frequency"],
                    ))
                await db.commit()
                logger.info("Seed data loaded", countries=len(data["countries"]))
        else:
            logger.info("Countries already seeded", count=count)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FluTracker", env=settings.app_env)
    await _init_db()
    if settings.scrape_enabled:
        from backend.ingestion.scheduler import start_scheduler
        start_scheduler()
        logger.info("Scraper scheduler started")
    yield
    logger.info("Shutting down FluTracker")


app = FastAPI(
    title="FluTracker API",
    version="1.0.0",
    description="Global influenza surveillance dashboard",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# API routers
app.include_router(cases.router, prefix="/api")
app.include_router(countries.router, prefix="/api")
app.include_router(trends.router, prefix="/api")
app.include_router(map_data.router, prefix="/api")
app.include_router(anomalies.router, prefix="/api")
app.include_router(forecast.router, prefix="/api")
app.include_router(severity.router, prefix="/api")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

# Serve frontend static files (used when running without nginx, e.g. Railway)
import os
from pathlib import Path

_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
