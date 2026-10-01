import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .ingest import run_ingestion

log = logging.getLogger(__name__)
_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler or not settings.daily_update_enabled:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone=settings.timezone)

    def job():
        try:
            log.info("Running daily Bhajan Marg update")
            run_ingestion(
                limit=settings.daily_scan_latest,
                force=False,
                mode="daily",
            )
        except Exception:
            log.exception("Daily ingestion failed")

    _scheduler.add_job(
        job,
        CronTrigger(
            hour=settings.daily_update_hour,
            minute=settings.daily_update_minute,
            timezone=settings.timezone,
        ),
        id="bhajan_daily_update",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
