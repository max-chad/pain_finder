import asyncio
import logging
import os
import signal

import config
from bot import PainFinderBot
from budget import BudgetGuard
from classifier import Classifier
from clusterer import MacroTrendClusterer
from db import Database
from deduplicator import Deduplicator
from digest_delivery import DailyDigestDocumentService
from dspy_parser import DSPyRedditPainParser
from embedder import Embedder
from export_sheets import ExportService
from generator_gtm import GTMGenerator
from openrouter import OpenRouterClient
from pipeline import AnalysisPipeline
from scheduler import MonitoringScheduler
from scraper import RedditScraper
from scraper_hn import HackerNewsScraper
from scraper_reviews import ReviewScraper, ReviewTarget

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _build_review_targets() -> list[ReviewTarget]:
    targets: list[ReviewTarget] = []
    for raw in config.REVIEW_TARGETS:
        if not isinstance(raw, dict):
            continue
        site = str(raw.get("site", "")).strip().lower()
        name = str(raw.get("name", "")).strip()
        url = str(raw.get("url", "")).strip()
        enabled = bool(raw.get("enabled", True))
        if not site or not name or not url:
            continue
        targets.append(ReviewTarget(site=site, name=name, url=url, enabled=enabled))
    return targets


def _build_dspy_parser():
    if not config.DSPY_REDDIT_PARSER_ENABLED:
        return None
    if not config.DSPY_API_KEY:
        logger.warning("DSPy Reddit parser enabled but no API key was provided; falling back to the configured LLM client")
        return None
    dspy_available = getattr(DSPyRedditPainParser, "is_available", lambda: True)()
    if not dspy_available:
        logger.warning("DSPy Reddit parser enabled but the dspy package is not installed; falling back to the configured LLM client")
        return None
    return DSPyRedditPainParser(
        api_key=config.DSPY_API_KEY,
        provider=config.DSPY_PROVIDER,
        model=config.DSPY_MODEL,
        api_base=config.DSPY_API_BASE,
        reasoning_effort=config.DSPY_REASONING_EFFORT,
        temperature=config.DSPY_TEMPERATURE,
        max_tokens=config.DSPY_MAX_TOKENS,
    )


def _build_shutdown_event() -> asyncio.Event:
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_shutdown(signame: str) -> None:
        if not shutdown_event.is_set():
            logger.info("shutdown_requested stage=runtime signal=%s", signame)
            shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown, sig.name)
        except (AttributeError, NotImplementedError, RuntimeError, ValueError):
            logger.debug("Signal handler unavailable for %s on this event loop", sig.name)
    return shutdown_event


async def _publish_daily_digest(*, digest_service: DailyDigestDocumentService):
    result = await digest_service.build_document(
        hours=config.DIGEST_HOURS,
        group_by=config.DIGEST_GROUP_BY,
        min_wtp=config.DIGEST_MIN_WTP,
        max_items_per_group=config.DIGEST_MAX_ITEMS_PER_GROUP,
    )
    if result.docx_path is None:
        logger.info("daily_digest_skipped stage=digest reason=no_items")
        return result

    from telegram import Bot

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    with open(result.docx_path, "rb") as document_file:
        await bot.send_document(
            chat_id=config.TELEGRAM_CHAT_ID,
            document=document_file,
            filename=os.path.basename(result.docx_path),
            caption=(
                f"pain_finder daily digest • {result.total_items} items • {result.group_count} groups"
            ),
        )
    logger.info(
        "daily_digest_sent stage=digest path=%s total_items=%d group_count=%d",
        result.docx_path,
        result.total_items,
        result.group_count,
    )
    return result


async def run() -> None:
    db = Database(config.DB_PATH)
    await db.init()

    embedder = Embedder(
        api_key=config.EMBED_API_KEY,
        model=config.EMBED_MODEL,
        provider=config.EMBED_PROVIDER,
        api_base=config.EMBED_API_BASE,
    )
    deduplicator = Deduplicator(db=db, embedder=embedder, threshold=config.DEDUP_SIMILARITY_THRESHOLD)
    dedup_merged = await deduplicator.backfill()
    logger.info("Dedup backfill complete: %d cross-source duplicates merged", dedup_merged)

    budget_guard = BudgetGuard(db=db, daily_cap_usd=config.DAILY_BUDGET_USD)

    scraper = RedditScraper(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
        top_comments_limit=config.SCRAPER_TOP_COMMENTS,
        comment_fetch_concurrency=config.SCRAPER_COMMENT_FETCH_CONCURRENCY,
        retry_max_attempts=config.SCRAPER_RETRY_MAX_ATTEMPTS,
        retry_base_delay=config.SCRAPER_RETRY_BASE_DELAY,
        feed_mix=config.SCRAPER_FEED_MIX,
        search_queries=config.SCRAPER_SEARCH_QUERIES,
    )
    openrouter = OpenRouterClient(
        api_key=config.LLM_API_KEY,
        model=config.LLM_MODEL,
        deep_dive_model=config.LLM_DEEP_DIVE_MODEL,
        cluster_model=config.LLM_CLUSTER_MODEL,
        gtm_model=config.LLM_GTM_MODEL,
        pricing_map=config.LLM_MODEL_PRICING,
        budget_guard=budget_guard,
        cache_db=db,
        provider=config.LLM_PROVIDER,
        api_base=config.LLM_API_BASE,
        reasoning_effort=config.LLM_REASONING_EFFORT,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
        primary_max_output_tokens=config.PRIMARY_MAX_OUTPUT_TOKENS,
    )
    dspy_parser = _build_dspy_parser()

    classifier = Classifier(
        openrouter=openrouter,
        dspy_parser=dspy_parser,
        mode=config.CLASSIFIER_MODE,
        max_concurrency=config.CLASSIFIER_MAX_CONCURRENCY,
        screen_min_rule_score=config.SCREEN_MIN_RULE_SCORE,
        screen_max_llm_candidates_per_run=config.SCREEN_MAX_LLM_CANDIDATES_PER_RUN,
    )
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=config.REPORTS_DIR,
        deep_dive_wtp_threshold=config.DEEP_DIVE_WTP_THRESHOLD,
        deep_dive_max_comments=config.DEEP_DIVE_MAX_COMMENTS,
        budget_guard=budget_guard,
        deduplicator=deduplicator,
        llm_max_classifications_per_run=config.LLM_MAX_CLASSIFICATIONS_PER_RUN,
        screen_max_llm_candidates_per_run=config.SCREEN_MAX_LLM_CANDIDATES_PER_RUN,
        current_opportunity_max_age_days=config.CURRENT_OPPORTUNITY_MAX_AGE_DAYS,
    )
    clusterer = MacroTrendClusterer(
        db=db,
        openrouter=openrouter,
        min_cluster_size=config.TREND_MIN_CLUSTER_SIZE,
        similarity_threshold=config.TREND_CLUSTER_SIMILARITY,
        min_wtp=config.EXPORT_MIN_WTP,
    )
    gtm_generator = GTMGenerator(db=db, openrouter=openrouter)

    hn_scraper = HackerNewsScraper(user_agent=config.REDDIT_USER_AGENT)
    review_scraper = ReviewScraper(user_agent=config.REDDIT_USER_AGENT)
    review_targets = _build_review_targets()

    export_service = ExportService(
        db=db,
        reports_dir=config.REPORTS_DIR,
        min_wtp=config.EXPORT_MIN_WTP,
        sheets_credentials_json=config.GOOGLE_SHEETS_CREDENTIALS_JSON,
        sheets_spreadsheet_id=config.GOOGLE_SHEETS_SPREADSHEET_ID,
        sheets_worksheet_prefix=config.GOOGLE_SHEETS_WORKSHEET_PREFIX,
    )
    digest_service = DailyDigestDocumentService(db=db, reports_dir=config.REPORTS_DIR)
    notifications_enabled = config.APP_MODE == "telegram"

    async def deep_dive_from_bot(post_id: str, subreddit: str, source: str):
        row = await db.get_pain_point(post_id)
        return await pipeline.run_deep_dive(
            post_id=post_id,
            subreddit=subreddit,
            source=source,
            title=(row.get("title") if row else "") or "",
            body=(row.get("body") if row else "") or "",
        )

    async def digest_from_bot(subreddit: str | None, hours: int):
        return await pipeline.generate_digest(subreddit=subreddit, hours=hours)

    async def macro_from_bot(days: int):
        return await clusterer.run(window_days=days)

    async def budget_status_from_bot():
        return await budget_guard.get_status()

    async def resume_budget_from_bot():
        return await budget_guard.resume_until_next_utc_day()

    async def gtm_from_bot(post_id: str):
        return await gtm_generator.generate(post_id)

    bot = PainFinderBot(
        scraper=scraper,
        classifier=classifier,
        db=db,
        analyze_fn=pipeline.analyze_subreddit,
        deep_dive_fn=deep_dive_from_bot,
        digest_fn=digest_from_bot,
        macro_fn=macro_from_bot,
        budget_status_fn=budget_status_from_bot,
        resume_budget_fn=resume_budget_from_bot,
        gtm_fn=gtm_from_bot,
        export_service=export_service,
    )

    async def analyze_and_notify(subreddit: str) -> None:
        run_result = await pipeline.analyze_subreddit(subreddit=subreddit, limit=100)
        if notifications_enabled and run_result.pain_count:
            await bot.send_grouped_notification(
                chat_id=config.TELEGRAM_CHAT_ID,
                signals=run_result.signals,
                label=f"r/{subreddit}",
            )

    async def run_macro_job() -> None:
        result = await clusterer.run(window_days=config.TREND_LOOKBACK_DAYS)
        if notifications_enabled and bot.app and result.clusters:
            top = result.clusters[0]
            await bot.app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=(
                    f"Macro trend detected ({len(result.clusters)} clusters, {result.candidate_count} candidates).\n"
                    f"Top: {top.label} | items={top.item_count} | signal={top.estimated_monetization_signal}\n"
                    f"{top.summary}"
                ),
            )

    async def run_hn_job() -> None:
        if not config.HN_ENABLED:
            return
        posts = await hn_scraper.fetch_posts(
            keywords=[str(keyword) for keyword in config.HN_KEYWORDS],
            lookback_hours=config.HN_LOOKBACK_HOURS,
            max_posts=config.HN_MAX_POSTS,
        )
        if not posts:
            return
        run_result = await pipeline.analyze_external_posts(posts=posts, source="hn", run_scope="hackernews")
        if notifications_enabled and run_result.pain_count:
            await bot.send_grouped_notification(
                chat_id=config.TELEGRAM_CHAT_ID,
                signals=run_result.signals,
                label="HN",
            )

    async def run_reviews_job() -> None:
        if not config.REVIEWS_ENABLED:
            return
        posts = await review_scraper.fetch_many_targets(
            targets=review_targets,
            max_per_target=config.REVIEWS_MAX_PER_TARGET,
        )
        if not posts:
            return
        run_result = await pipeline.analyze_external_posts(posts=posts, source="reviews", run_scope="reviews")
        if notifications_enabled and run_result.pain_count:
            await bot.send_grouped_notification(
                chat_id=config.TELEGRAM_CHAT_ID,
                signals=run_result.signals,
                label="Reviews",
            )

    async def run_daily_digest_job() -> None:
        await _publish_daily_digest(digest_service=digest_service)

    scheduler = MonitoringScheduler(
        db=db,
        analyze_fn=analyze_and_notify,
        macro_fn=run_macro_job,
        hn_fn=run_hn_job,
        reviews_fn=run_reviews_job,
        digest_fn=run_daily_digest_job,
        macro_enabled=config.MACRO_TREND_ENABLED,
        macro_weekday_utc=config.MACRO_TREND_WEEKDAY_UTC,
        macro_hour_utc=config.MACRO_TREND_HOUR_UTC,
        hn_enabled=config.HN_ENABLED,
        hn_interval_hours=config.HN_INTERVAL_HOURS,
        reviews_enabled=config.REVIEWS_ENABLED,
        reviews_interval_hours=config.REVIEWS_INTERVAL_HOURS,
        digest_enabled=config.DIGEST_DELIVERY_ENABLED,
        digest_hour_utc=config.DIGEST_HOUR_UTC,
        digest_minute_utc=config.DIGEST_MINUTE_UTC,
    )
    bot.reload_jobs_fn = scheduler.reload_jobs

    async def on_budget_pause(reason: str) -> None:
        await scheduler.reload_jobs()
        if bot.app:
            await bot.app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=f"Budget cap reached. Monitoring paused. Reason: {reason}. Use /resume to override.",
            )

    budget_guard.set_on_pause_callback(on_budget_pause)

    scheduler_started = False
    shutdown_event = _build_shutdown_event()
    try:
        scheduler.start()
        scheduler_started = True
        await scheduler.reload_jobs()

        logger.info("pain_finder starting in %s mode...", config.APP_MODE)
        if notifications_enabled:
            tg_app = bot.build_app()
            async with tg_app:
                await tg_app.start()
                if tg_app.updater is None:
                    raise RuntimeError("Telegram updater is not configured")
                await tg_app.updater.start_polling()
                logger.info("Bot is running. Send /status in Telegram to verify.")
                try:
                    await shutdown_event.wait()
                finally:
                    await tg_app.updater.stop()
                    await tg_app.stop()
        else:
            logger.info("Hermes mode enabled: skipping Telegram polling and keeping scheduler alive.")
            await shutdown_event.wait()
    finally:
        if scheduler_started:
            scheduler.stop()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
