"""Scraper scheduler — orchestrates periodic data ingestion."""

from datetime import datetime

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from backend.app.config import get_settings
from backend.app.database import async_session

logger = structlog.get_logger()
settings = get_settings()

scheduler = AsyncIOScheduler()


async def run_who_flunet():
    """Run WHO FluNet scraper for all countries."""
    from backend.ingestion.scrapers.who_flunet import WHOFluNetScraper

    async with async_session() as db:
        scraper = WHOFluNetScraper()
        try:
            count = await scraper.run(db)
            logger.info("WHO FluNet scrape complete", records=count)
        except Exception as e:
            logger.error("WHO FluNet scrape failed", error=str(e))
        finally:
            await scraper.close()


async def run_anomaly_detection():
    """Run anomaly detection on current data."""
    from backend.app.services.anomaly_detection import detect_anomalies

    async with async_session() as db:
        try:
            anomalies = await detect_anomalies(db)
            logger.info("Anomaly detection complete", new_anomalies=len(anomalies))
        except Exception as e:
            logger.error("Anomaly detection failed", error=str(e))


def start_scheduler():
    """Configure and start the scraper scheduler."""
    interval_hours = settings.scrape_interval_hours

    # WHO FluNet: every 6 hours (checks for weekly updates)
    scheduler.add_job(
        run_who_flunet,
        trigger=IntervalTrigger(hours=interval_hours),
        id="who_flunet",
        name="WHO FluNet Scraper",
        next_run_time=datetime.utcnow(),  # Run immediately on startup
    )

    # Anomaly detection: run after each scrape cycle
    scheduler.add_job(
        run_anomaly_detection,
        trigger=CronTrigger(hour="1,7,13,19", minute=0),
        id="anomaly_detection",
        name="Anomaly Detection",
    )

    scheduler.start()
    logger.info(
        "Scheduler started",
        jobs=len(scheduler.get_jobs()),
        interval_hours=interval_hours,
    )
