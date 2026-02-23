import logging
from typing import Callable, Awaitable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import Database

logger = logging.getLogger(__name__)


class MonitoringScheduler:
    def __init__(self, db: Database, analyze_fn: Callable[[str], Awaitable[None]]):
        self.db = db
        self.analyze_fn = analyze_fn
        self.scheduler = AsyncIOScheduler()

    def start(self):
        self.scheduler.start()
        logger.info("Scheduler started")

    def stop(self):
        self.scheduler.shutdown(wait=False)

    def job_count(self) -> int:
        return len([j for j in self.scheduler.get_jobs() if j.id.startswith("monitor_")])

    async def reload_jobs(self):
        # Remove all existing monitoring jobs
        for job in self.scheduler.get_jobs():
            if job.id.startswith("monitor_"):
                job.remove()

        # Re-add from DB
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
            logger.info("Scheduled r/%s every %dh", sub["name"], sub["interval_hours"])

    async def _run_analysis(self, subreddit: str):
        logger.info("Running scheduled analysis for r/%s", subreddit)
        try:
            await self.analyze_fn(subreddit)
            await self.db.update_last_checked(subreddit)
        except Exception as e:
            logger.error("Scheduled analysis failed for r/%s: %s", subreddit, e)
