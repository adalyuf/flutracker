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

    # Create all tables if they don't exist
    async with engine.begin() as conn:
        # Enable TimescaleDB extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))

        # Check if flu_cases is already a hypertable
        result = await conn.execute(text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM timescaledb_information.hypertables "
            "  WHERE hypertable_name = 'flu_cases'"
            ")"
        ))
        is_hypertable = result.scalar()

        if not is_hypertable:
            # Drop old flu_cases table if it exists with wrong PK structure
            await conn.execute(text("DROP TABLE IF EXISTS flu_cases CASCADE"))
            logger.info("Dropped old flu_cases table for hypertable recreation")

        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured")

    # Create hypertable if not already one
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
