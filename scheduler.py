import logging
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db import Database

logger = logging.getLogger(__name__)


class MonitoringScheduler:
    def __init__(
        self,
        db: Database,
        analyze_fn: Callable[[str], Awaitable[None]],
        *,
        macro_fn: Callable[[], Awaitable[None]] | None = None,
        hn_fn: Callable[[], Awaitable[None]] | None = None,
        reviews_fn: Callable[[], Awaitable[None]] | None = None,
        macro_enabled: bool = False,
        macro_weekday_utc: str = "sun",
        macro_hour_utc: int = 8,
        hn_enabled: bool = False,
        hn_interval_hours: int = 6,
        reviews_enabled: bool = False,
        reviews_interval_hours: int = 24,
    ):
        self.db = db
        self.analyze_fn = analyze_fn
        self.macro_fn = macro_fn
        self.hn_fn = hn_fn
        self.reviews_fn = reviews_fn
        self.macro_enabled = macro_enabled
        self.macro_weekday_utc = macro_weekday_utc
        self.macro_hour_utc = macro_hour_utc
        self.hn_enabled = hn_enabled
        self.hn_interval_hours = hn_interval_hours
        self.reviews_enabled = reviews_enabled
        self.reviews_interval_hours = reviews_interval_hours
        self.scheduler = AsyncIOScheduler()

    def start(self):
        self.scheduler.start()
        logger.info("scheduler_started stage=scheduler")

    def stop(self):
        self.scheduler.shutdown(wait=False)

    def job_count(self) -> int:
        return len([job for job in self.scheduler.get_jobs() if job.id.startswith(("monitor_", "macro_", "hn_", "reviews_"))])

    async def reload_jobs(self):
        for job in self.scheduler.get_jobs():
            if job.id.startswith(("monitor_", "macro_", "hn_", "reviews_")):
                job.remove()

        paused_value = await self.db.is_llm_paused()
        paused = paused_value if isinstance(paused_value, bool) else False
        if paused:
            logger.warning("scheduler_reload_skipped stage=scheduler reason=llm_paused")
            return

        subs = await self.db.get_monitored_subreddits()
        for sub in subs:
            self.scheduler.add_job(
                self._run_analysis,
                trigger="interval",
                hours=sub["interval_hours"],
                id=f"monitor_{sub['name']}",
                args=[sub["name"]],
                replace_existing=True,
            )
            logger.info(
                "scheduler_job_loaded stage=scheduler job=monitor subreddit=%s interval_hours=%d",
                sub["name"],
                sub["interval_hours"],
            )

        if self.macro_enabled and self.macro_fn is not None:
            self.scheduler.add_job(
                self._run_macro,
                trigger="cron",
                day_of_week=self.macro_weekday_utc,
                hour=self.macro_hour_utc,
                minute=0,
                id="macro_weekly",
                replace_existing=True,
            )
            logger.info(
                "scheduler_job_loaded stage=scheduler job=macro weekday=%s hour=%d",
                self.macro_weekday_utc,
                self.macro_hour_utc,
            )

        if self.hn_enabled and self.hn_fn is not None:
            self.scheduler.add_job(
                self._run_hn,
                trigger="interval",
                hours=max(1, self.hn_interval_hours),
                id="hn_ingest",
                replace_existing=True,
            )
            logger.info(
                "scheduler_job_loaded stage=scheduler job=hn interval_hours=%d",
                self.hn_interval_hours,
            )

        if self.reviews_enabled and self.reviews_fn is not None:
            self.scheduler.add_job(
                self._run_reviews,
                trigger="interval",
                hours=max(1, self.reviews_interval_hours),
                id="reviews_ingest",
                replace_existing=True,
            )
            logger.info(
                "scheduler_job_loaded stage=scheduler job=reviews interval_hours=%d",
                self.reviews_interval_hours,
            )

    async def _run_analysis(self, subreddit: str):
        logger.info("scheduled_analysis_start stage=scheduler subreddit=%s", subreddit)
        try:
            await self.analyze_fn(subreddit)
            await self.db.update_last_checked(subreddit)
            logger.info("scheduled_analysis_complete stage=scheduler subreddit=%s", subreddit)
        except Exception:
            logger.exception("scheduled_analysis_failed stage=scheduler subreddit=%s", subreddit)

    async def _run_macro(self):
        logger.info("scheduled_macro_start stage=scheduler")
        try:
            if self.macro_fn:
                await self.macro_fn()
            logger.info("scheduled_macro_complete stage=scheduler")
        except Exception:
            logger.exception("scheduled_macro_failed stage=scheduler")

    async def _run_hn(self):
        logger.info("scheduled_hn_start stage=scheduler")
        try:
            if self.hn_fn:
                await self.hn_fn()
            logger.info("scheduled_hn_complete stage=scheduler")
        except Exception:
            logger.exception("scheduled_hn_failed stage=scheduler")

    async def _run_reviews(self):
        logger.info("scheduled_reviews_start stage=scheduler")
        try:
            if self.reviews_fn:
                await self.reviews_fn()
            logger.info("scheduled_reviews_complete stage=scheduler")
        except Exception:
            logger.exception("scheduled_reviews_failed stage=scheduler")
