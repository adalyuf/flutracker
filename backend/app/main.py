import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.config import get_settings
from backend.app.database import Base
from backend.app.routers import (
    anomalies,
    cases,
    countries,
    forecast,
    genomics,
    map_data,
    severity,
    trends,
)

settings = get_settings()
logger = structlog.get_logger()


async def _init_db():
    """Create tables and load seed data on first run."""
    from backend.app.database import engine, async_session
    from backend.app.models import Country  # noqa: ensure models loaded
    from sqlalchemy.exc import OperationalError

    def _is_retryable_db_error(exc: Exception) -> bool:
        current: BaseException | None = exc
        while current is not None:
            if isinstance(current, (OperationalError, OSError, ConnectionError)):
                return True
            message = str(current).lower()
            if (
                "name resolution" in message
                or "could not translate host name" in message
                or "connection refused" in message
                or "connection reset" in message
                or "timeout" in message
            ):
                return True
            current = current.__cause__ or current.__context__
        return False

    attempts = max(1, settings.db_startup_max_attempts)
    initial_backoff = max(1, settings.db_startup_initial_backoff_seconds)
    max_backoff = max(initial_backoff, settings.db_startup_max_backoff_seconds)

    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                logger.info("Database tables ensured")

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
            return
        except Exception as exc:
            if attempt >= attempts or not _is_retryable_db_error(exc):
                raise
            backoff = min(initial_backoff * (2 ** (attempt - 1)), max_backoff)
            logger.warning(
                "Database unavailable during startup; retrying",
                attempt=attempt,
                max_attempts=attempts,
                retry_in_seconds=backoff,
                error=str(exc),
            )
            await asyncio.sleep(backoff)


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
app.include_router(genomics.router, prefix="/api")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

# Serve frontend static files (used when running without nginx, e.g. Railway)
from pathlib import Path

_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
