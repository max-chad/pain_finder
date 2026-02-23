import asyncio
import logging

import config
from bot import PainFinderBot, format_report
from classifier import Classifier
from db import Database
from openrouter import OpenRouterClient
from pipeline import AnalysisPipeline
from scheduler import MonitoringScheduler
from scraper import RedditScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    db = Database(config.DB_PATH)
    await db.init()

    scraper = RedditScraper(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )
    openrouter = OpenRouterClient(
        api_key=config.OPENROUTER_API_KEY,
        model=config.OPENROUTER_MODEL,
    )
    classifier = Classifier(openrouter=openrouter)
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=config.REPORTS_DIR,
    )

    bot = PainFinderBot(
        scraper=scraper,
        classifier=classifier,
        db=db,
        analyze_fn=pipeline.analyze_subreddit,
    )

    async def analyze_and_notify(subreddit: str) -> None:
        run_result = await pipeline.analyze_subreddit(subreddit=subreddit, limit=100)
        if bot.app:
            await bot.app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=format_report(subreddit, run_result.signals),
            )

    scheduler = MonitoringScheduler(db=db, analyze_fn=analyze_and_notify)
    bot.reload_jobs_fn = scheduler.reload_jobs
    scheduler_started = False

    try:
        scheduler.start()
        scheduler_started = True
        await scheduler.reload_jobs()

        tg_app = bot.build_app()
        logger.info("pain_finder starting...")

        async with tg_app:
            await tg_app.start()
            if tg_app.updater is None:
                raise RuntimeError("Telegram updater is not configured")
            await tg_app.updater.start_polling()
            logger.info("Bot is running. Send /status in Telegram to verify.")
            try:
                await asyncio.Event().wait()
            finally:
                await tg_app.updater.stop()
                await tg_app.stop()
    finally:
        if scheduler_started:
            scheduler.stop()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
