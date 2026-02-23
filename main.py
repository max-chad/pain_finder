import asyncio
import json
import logging
import os
from datetime import UTC, datetime

import config
from bot import PainFinderBot, format_report
from classifier import Classifier
from db import Database
from openrouter import OpenRouterClient
from scheduler import MonitoringScheduler
from scraper import RedditScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    os.makedirs(config.REPORTS_DIR, exist_ok=True)

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
    bot = PainFinderBot(scraper=scraper, classifier=classifier, db=db)

    async def analyze_and_notify(subreddit: str, limit: int = 100) -> None:
        posts = await scraper.fetch_posts(subreddit, limit=limit)
        signals = await classifier.classify_batch(posts)

        for signal in signals:
            await db.insert_pain_point(
                subreddit=subreddit,
                post_id=signal.post.post_id,
                url=signal.post.url,
                title=signal.post.title,
                body=signal.post.body,
                category=signal.category,
                summary=signal.summary,
                severity=signal.severity,
            )

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        json_path = os.path.join(config.REPORTS_DIR, f"{subreddit}_{timestamp}.json")
        with open(json_path, "w", encoding="utf-8") as report_file:
            json.dump(
                [
                    {
                        "post_id": signal.post.post_id,
                        "title": signal.post.title,
                        "url": signal.post.url,
                        "category": signal.category,
                        "summary": signal.summary,
                        "severity": signal.severity,
                    }
                    for signal in signals
                ],
                report_file,
                indent=2,
                ensure_ascii=False,
            )

        await db.save_report(
            subreddit=subreddit,
            post_count=len(posts),
            pain_count=len(signals),
            json_path=json_path,
        )

        if bot.app:
            await bot.app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=format_report(subreddit, signals),
            )

    scheduler = MonitoringScheduler(db=db, analyze_fn=analyze_and_notify)
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
