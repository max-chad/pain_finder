import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_build_dspy_parser_returns_none_when_dependency_missing(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DSPY_REDDIT_PARSER_ENABLED", "1")

    main = importlib.import_module("main")
    main = importlib.reload(main)

    class MissingDSPyParser:
        @staticmethod
        def is_available():
            return False

    monkeypatch.setattr(main, "DSPyRedditPainParser", MissingDSPyParser)

    assert main._build_dspy_parser() is None


def test_build_review_targets_respects_string_disabled_flags(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")

    main = importlib.import_module("main")
    main = importlib.reload(main)
    main.config.REVIEW_TARGETS = [
        {"site": "g2", "name": "Disabled", "url": "https://example.com/disabled", "enabled": "false"},
        {"site": "capterra", "name": "Off", "url": "https://example.com/off", "enabled": "off"},
        {"site": "g2", "name": "Enabled", "url": "https://example.com/enabled", "enabled": "yes"},
    ]

    targets = main._build_review_targets()

    assert [target.enabled for target in targets] == [False, False, True]


@pytest.mark.asyncio
async def test_build_shutdown_event_registers_sigint_and_sigterm(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")

    main = importlib.import_module("main")
    main = importlib.reload(main)
    registered = []

    class FakeLoop:
        def add_signal_handler(self, sig, callback, *args):
            registered.append((sig, callback, args))

    monkeypatch.setattr(main.asyncio, "get_running_loop", lambda: FakeLoop())

    event = main._build_shutdown_event()

    assert [item[0] for item in registered] == [main.signal.SIGINT, main.signal.SIGTERM]
    assert event.is_set() is False
    registered[1][1](*registered[1][2])
    assert event.is_set() is True


@pytest.mark.asyncio
async def test_safe_grouped_notification_swallows_delivery_failure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")

    main = importlib.import_module("main")
    main = importlib.reload(main)
    signals = [object()]
    bot = SimpleNamespace(send_grouped_notification=AsyncMock(side_effect=RuntimeError("telegram down")))

    await main._send_grouped_notification_safely(bot, chat_id=123, signals=signals, label="r/python")

    bot.send_grouped_notification.assert_awaited_once_with(chat_id=123, signals=signals, label="r/python")


@pytest.mark.asyncio
async def test_safe_telegram_message_truncates_and_swallows_delivery_failure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")

    main = importlib.import_module("main")
    main = importlib.reload(main)
    telegram_bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("telegram down")))

    await main._send_telegram_message_safely(
        telegram_bot,
        chat_id=123,
        text="x" * 6000,
        context="macro_trend",
    )

    sent_text = telegram_bot.send_message.await_args.kwargs["text"]
    assert len(sent_text) <= 4096
    assert "[truncated]" in sent_text


@pytest.mark.asyncio
async def test_run_wires_components_and_teardown(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.3-spark")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    monkeypatch.setenv("EMBED_PROVIDER", "codex")
    monkeypatch.setenv("EMBED_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("OPENAI_API_KEY", "dspy-key")
    monkeypatch.setenv("DSPY_REDDIT_PARSER_ENABLED", "1")
    monkeypatch.setenv("SCREEN_MIN_RULE_SCORE", "3")
    monkeypatch.setenv("SCREEN_MAX_LLM_CANDIDATES_PER_RUN", "21")
    monkeypatch.setenv("PRIMARY_MAX_OUTPUT_TOKENS", "777")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    import config
    importlib.reload(config)
    main = importlib.import_module("main")
    main = importlib.reload(main)
    main.config.APP_MODE = "telegram"
    main.config.MACRO_TREND_ENABLED = True
    main.config.HN_ENABLED = True
    main.config.REVIEWS_ENABLED = True
    main.config.HN_KEYWORDS = ["internal tool"]
    main.config.REVIEW_TARGETS = [{"site": "g2", "name": "ToolX", "url": "https://example.com/reviews", "enabled": True}]

    class FakeDB:
        instances = []

        def __init__(self, path):
            self.path = path
            self.init_called = False
            self.close_called = False
            FakeDB.instances.append(self)

        async def init(self):
            self.init_called = True

        async def close(self):
            self.close_called = True

        async def get_pain_point(self, post_id):
            return {"title": "t", "body": "b"}

        async def is_llm_paused(self):
            return False

        async def get_pain_points_without_embeddings(self):
            return []

        async def get_pain_points_with_embeddings(self):
            return []

    class FakeScraper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeEmbedder:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeEmbedder.instances.append(self)

    class FakeDeduplicator:
        instances = []

        def __init__(self, db, embedder, threshold):
            self.db = db
            self.embedder = embedder
            self.threshold = threshold
            FakeDeduplicator.instances.append(self)

        async def backfill(self):
            return 0

    class FakeOpenRouterClient:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeOpenRouterClient.instances.append(self)

    class FakeDSPyParser:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeDSPyParser.instances.append(self)

    class FakeClassifier:
        def __init__(
            self,
            openrouter,
            dspy_parser=None,
            mode="dual",
            max_concurrency=8,
            screen_min_rule_score=1,
            screen_max_llm_candidates_per_run=0,
        ):
            self.openrouter = openrouter
            self.dspy_parser = dspy_parser
            self.mode = mode
            self.max_concurrency = max_concurrency
            self.screen_min_rule_score = screen_min_rule_score
            self.screen_max_llm_candidates_per_run = screen_max_llm_candidates_per_run

    class FakePipeline:
        instances = []

        def __init__(
            self,
            scraper,
            classifier,
            db,
            reports_dir,
            deep_dive_wtp_threshold=8,
            deep_dive_max_comments=250,
            budget_guard=None,
            deduplicator=None,
            llm_max_classifications_per_run=0,
            screen_max_llm_candidates_per_run=0,
            current_opportunity_max_age_days=180,
        ):
            self.scraper = scraper
            self.classifier = classifier
            self.db = db
            self.reports_dir = reports_dir
            self.budget_guard = budget_guard
            self.llm_max_classifications_per_run = llm_max_classifications_per_run
            self.screen_max_llm_candidates_per_run = screen_max_llm_candidates_per_run
            self.calls = []
            self.deep_dive_calls = []
            self.digest_calls = []
            FakePipeline.instances.append(self)

        async def analyze_subreddit(self, subreddit, limit=100):
            self.calls.append((subreddit, limit))
            return SimpleNamespace(signals=[], post_count=1, pain_count=1)

        async def run_deep_dive(self, **kwargs):
            self.deep_dive_calls.append(kwargs)
            return SimpleNamespace(status="completed", summary="ok", error=None)

        async def generate_digest(self, subreddit=None, hours=24):
            self.digest_calls.append((subreddit, hours))
            return {
                "total": 0,
                "top_items": [],
                "niche_counts": {},
                "source_counts": {},
                "recurring_blockers": [],
            }

        async def analyze_external_posts(self, posts, source, run_scope):
            self.calls.append((run_scope, len(posts)))
            return SimpleNamespace(post_count=len(posts), pain_count=0)

    class FakeExportService:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeExportService.instances.append(self)

    class FakeUpdater:
        def __init__(self):
            self.start_polling_called = False
            self.stop_called = False

        async def start_polling(self):
            self.start_polling_called = True

        async def stop(self):
            self.stop_called = True

    class _AsyncRecorder:
        def __init__(self):
            self.calls = []

        async def __call__(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    class FakeTelegramApp:
        instances = []

        def __init__(self):
            self.start_called = False
            self.stop_called = False
            self.updater = FakeUpdater()
            self.bot = SimpleNamespace(send_message=_AsyncRecorder())
            FakeTelegramApp.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def start(self):
            self.start_called = True

        async def stop(self):
            self.stop_called = True

    class FakeBot:
        instances = []

        def __init__(
            self,
            scraper,
            classifier,
            db,
            reload_jobs_fn=None,
            analyze_fn=None,
            deep_dive_fn=None,
            digest_fn=None,
            macro_fn=None,
            budget_status_fn=None,
            resume_budget_fn=None,
            gtm_fn=None,
            export_service=None,
        ):
            self.scraper = scraper
            self.classifier = classifier
            self.db = db
            self.reload_jobs_fn = reload_jobs_fn
            self.analyze_fn = analyze_fn
            self.deep_dive_fn = deep_dive_fn
            self.digest_fn = digest_fn
            self.macro_fn = macro_fn
            self.budget_status_fn = budget_status_fn
            self.resume_budget_fn = resume_budget_fn
            self.gtm_fn = gtm_fn
            self.export_service = export_service
            self.app = None
            self.grouped_notifications: list[dict] = []
            FakeBot.instances.append(self)

        def build_app(self):
            self.app = FakeTelegramApp()
            return self.app

        async def send_grouped_notification(self, *, chat_id: int, signals: list, label: str) -> None:
            self.grouped_notifications.append({"chat_id": chat_id, "signals": signals, "label": label})

    class FakeScheduler:
        instances = []

        def __init__(self, db, analyze_fn, **kwargs):
            self.db = db
            self.analyze_fn = analyze_fn
            self.kwargs = kwargs
            self.started = False
            self.stopped = False
            self.reload_called = False
            FakeScheduler.instances.append(self)

        def start(self):
            self.started = True

        async def reload_jobs(self):
            self.reload_called = True

        def stop(self):
            self.stopped = True

    class FakeEvent:
        async def wait(self):
            scheduler = FakeScheduler.instances[-1]
            await scheduler.analyze_fn("python")
            return None

    monkeypatch.setattr(main, "Database", FakeDB)
    monkeypatch.setattr(main, "RedditScraper", FakeScraper)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)
    monkeypatch.setattr(main, "Deduplicator", FakeDeduplicator)
    monkeypatch.setattr(main, "OpenRouterClient", FakeOpenRouterClient)
    monkeypatch.setattr(main, "DSPyRedditPainParser", FakeDSPyParser)
    monkeypatch.setattr(main, "Classifier", FakeClassifier)
    monkeypatch.setattr(main, "AnalysisPipeline", FakePipeline)
    monkeypatch.setattr(main, "PainFinderBot", FakeBot)
    monkeypatch.setattr(main, "MonitoringScheduler", FakeScheduler)
    monkeypatch.setattr(main, "ExportService", FakeExportService)
    monkeypatch.setattr(main.asyncio, "Event", lambda: FakeEvent())

    await main.run()

    db = FakeDB.instances[0]
    scheduler = FakeScheduler.instances[0]
    bot = FakeBot.instances[0]
    telegram_app = FakeTelegramApp.instances[0]
    pipeline = FakePipeline.instances[0]

    assert db.init_called is True
    assert db.close_called is True
    assert scheduler.started is True
    assert scheduler.reload_called is True
    assert scheduler.stopped is True
    assert bot.reload_jobs_fn is not None
    assert bot.reload_jobs_fn.__self__ is scheduler
    assert bot.analyze_fn is not None
    assert bot.analyze_fn.__self__ is pipeline
    assert bot.deep_dive_fn is not None
    assert bot.digest_fn is not None
    assert bot.export_service is not None
    assert telegram_app.start_called is True
    assert telegram_app.updater.start_polling_called is True
    assert telegram_app.updater.stop_called is True
    assert telegram_app.stop_called is True
    assert pipeline.calls[-1] == ("python", 100)
    assert bot.scraper.kwargs["feed_mix"] == main.config.SCRAPER_FEED_MIX
    assert bot.scraper.kwargs["comment_fetch_concurrency"] == main.config.SCRAPER_COMMENT_FETCH_CONCURRENCY
    assert bot.classifier.max_concurrency == main.config.CLASSIFIER_MAX_CONCURRENCY
    assert bot.classifier.screen_min_rule_score == main.config.SCREEN_MIN_RULE_SCORE
    assert isinstance(bot.classifier.dspy_parser, FakeDSPyParser)
    assert bot.classifier.dspy_parser.kwargs["provider"] == main.config.DSPY_PROVIDER
    assert FakeEmbedder.instances[0].kwargs["provider"] == main.config.EMBED_PROVIDER
    assert FakeOpenRouterClient.instances[0].kwargs["provider"] == main.config.LLM_PROVIDER
    assert FakeOpenRouterClient.instances[0].kwargs["reasoning_effort"] == main.config.LLM_REASONING_EFFORT
    assert FakeOpenRouterClient.instances[0].kwargs["primary_max_output_tokens"] == main.config.PRIMARY_MAX_OUTPUT_TOKENS
    assert pipeline.llm_max_classifications_per_run == main.config.LLM_MAX_CLASSIFICATIONS_PER_RUN
    assert pipeline.screen_max_llm_candidates_per_run == main.config.SCREEN_MAX_LLM_CANDIDATES_PER_RUN
    bot = FakeBot.instances[-1]
    assert len(bot.grouped_notifications) == 1
    assert bot.grouped_notifications[0]["label"] == "r/python"


@pytest.mark.asyncio
async def test_run_executes_macro_hn_reviews_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("MACRO_TREND_ENABLED", "1")
    monkeypatch.setenv("HN_ENABLED", "1")
    monkeypatch.setenv("REVIEWS_ENABLED", "1")
    monkeypatch.setenv("HN_KEYWORDS_JSON", '["internal tool"]')
    monkeypatch.setenv(
        "REVIEW_TARGETS_JSON",
        '[{"site":"g2","name":"ToolX","url":"https://example.com/reviews","enabled":true}]',
    )

    main = importlib.import_module("main")
    main = importlib.reload(main)
    main.config.APP_MODE = "telegram"

    class FakeDB:
        instances = []

        def __init__(self, path):
            self.path = path
            self.init_called = False
            self.close_called = False
            FakeDB.instances.append(self)

        async def init(self):
            self.init_called = True

        async def close(self):
            self.close_called = True

        async def get_pain_point(self, post_id):
            return {"title": "t", "body": "b"}

        async def is_llm_paused(self):
            return False

        async def get_pain_points_without_embeddings(self):
            return []

        async def get_pain_points_with_embeddings(self):
            return []

    class FakeScraper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeEmbedder:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeEmbedder.instances.append(self)

    class FakeDeduplicator:
        instances = []

        def __init__(self, db, embedder, threshold):
            self.db = db
            self.embedder = embedder
            self.threshold = threshold
            FakeDeduplicator.instances.append(self)

        async def backfill(self):
            return 0

    class FakeOpenRouterClient:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.gtm_model = "gpt-test"
            FakeOpenRouterClient.instances.append(self)

    class FakeDSPyParser:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeDSPyParser.instances.append(self)

    class FakeClassifier:
        def __init__(
            self,
            openrouter,
            dspy_parser=None,
            mode="dual",
            max_concurrency=8,
            screen_min_rule_score=1,
            screen_max_llm_candidates_per_run=0,
        ):
            self.openrouter = openrouter
            self.dspy_parser = dspy_parser
            self.mode = mode
            self.max_concurrency = max_concurrency
            self.screen_min_rule_score = screen_min_rule_score
            self.screen_max_llm_candidates_per_run = screen_max_llm_candidates_per_run

    class FakePipeline:
        instances = []

        def __init__(self, **kwargs):
            self.calls = []
            self.external_calls = []
            self.llm_max_classifications_per_run = kwargs.get("llm_max_classifications_per_run", 0)
            self.screen_max_llm_candidates_per_run = kwargs.get("screen_max_llm_candidates_per_run", 0)
            FakePipeline.instances.append(self)

        async def analyze_subreddit(self, subreddit, limit=100):
            self.calls.append((subreddit, limit))
            return SimpleNamespace(signals=[], post_count=1, pain_count=1)

        async def analyze_external_posts(self, posts, source, run_scope):
            self.external_calls.append((source, run_scope, len(posts)))
            return SimpleNamespace(post_count=len(posts), pain_count=1, signals=[])

        async def run_deep_dive(self, **kwargs):
            return SimpleNamespace(status="completed", summary="ok", error=None)

        async def generate_digest(self, subreddit=None, hours=24):
            return {"total": 0, "top_items": [], "niche_counts": {}, "source_counts": {}, "recurring_blockers": []}

    class FakeClusterer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def run(self, window_days):
            cluster = SimpleNamespace(
                label="Cluster",
                item_count=3,
                estimated_monetization_signal="high",
                summary="Recurring issue",
            )
            return SimpleNamespace(run_id=1, candidate_count=5, clusters=[cluster])

    class FakeGTMGenerator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def generate(self, post_id):
            payload = SimpleNamespace(
                name_options=["A", "B", "C"],
                hero_h1="H1",
                hero_h2="H2",
                mvp_features=["f1", "f2", "f3"],
                pricing_tier="$29",
                positioning_rationale="rationale",
            )
            return SimpleNamespace(post_id=post_id, payload=payload)

    class FakeHNScraper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def fetch_posts(self, **kwargs):
            post = SimpleNamespace(post_id="hn:1")
            return [post]

    class FakeReviewScraper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def fetch_many_targets(self, **kwargs):
            post = SimpleNamespace(post_id="review:g2:1")
            return [post]

    class FakeExportService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeUpdater:
        def __init__(self):
            self.start_polling_called = False
            self.stop_called = False

        async def start_polling(self):
            self.start_polling_called = True

        async def stop(self):
            self.stop_called = True

    class _AsyncRecorder:
        def __init__(self):
            self.calls = []

        async def __call__(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    class FakeTelegramApp:
        instances = []

        def __init__(self):
            self.start_called = False
            self.stop_called = False
            self.updater = FakeUpdater()
            self.bot = SimpleNamespace(send_message=_AsyncRecorder())
            FakeTelegramApp.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def start(self):
            self.start_called = True

        async def stop(self):
            self.stop_called = True

    class FakeBot:
        instances = []

        def __init__(self, **kwargs):
            self.reload_jobs_fn = kwargs.get("reload_jobs_fn")
            self.app = None
            self.grouped_notifications: list[dict] = []
            FakeBot.instances.append(self)

        def build_app(self):
            self.app = FakeTelegramApp()
            return self.app

        async def send_grouped_notification(self, *, chat_id: int, signals: list, label: str) -> None:
            self.grouped_notifications.append({"chat_id": chat_id, "signals": signals, "label": label})

    class FakeScheduler:
        instances = []

        def __init__(self, db, analyze_fn, **kwargs):
            self.db = db
            self.analyze_fn = analyze_fn
            self.kwargs = kwargs
            self.started = False
            self.stopped = False
            self.reload_called = False
            FakeScheduler.instances.append(self)

        def start(self):
            self.started = True

        async def reload_jobs(self):
            self.reload_called = True

        def stop(self):
            self.stopped = True

    class FakeEvent:
        async def wait(self):
            scheduler = FakeScheduler.instances[-1]
            await scheduler.analyze_fn("python")
            await scheduler.kwargs["macro_fn"]()
            await scheduler.kwargs["hn_fn"]()
            await scheduler.kwargs["reviews_fn"]()
            return None

    monkeypatch.setattr(main, "Database", FakeDB)
    monkeypatch.setattr(main, "RedditScraper", FakeScraper)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)
    monkeypatch.setattr(main, "Deduplicator", FakeDeduplicator)
    monkeypatch.setattr(main, "OpenRouterClient", FakeOpenRouterClient)
    monkeypatch.setattr(main, "DSPyRedditPainParser", FakeDSPyParser)
    monkeypatch.setattr(main, "Classifier", FakeClassifier)
    monkeypatch.setattr(main, "AnalysisPipeline", FakePipeline)
    monkeypatch.setattr(main, "MacroTrendClusterer", FakeClusterer)
    monkeypatch.setattr(main, "GTMGenerator", FakeGTMGenerator)
    monkeypatch.setattr(main, "HackerNewsScraper", FakeHNScraper)
    monkeypatch.setattr(main, "ReviewScraper", FakeReviewScraper)
    monkeypatch.setattr(main, "PainFinderBot", FakeBot)
    monkeypatch.setattr(main, "MonitoringScheduler", FakeScheduler)
    monkeypatch.setattr(main, "ExportService", FakeExportService)
    monkeypatch.setattr(main.asyncio, "Event", lambda: FakeEvent())

    await main.run()

    scheduler = FakeScheduler.instances[0]
    pipeline = FakePipeline.instances[0]
    telegram_app = FakeTelegramApp.instances[0]
    messages_sent = telegram_app.bot.send_message.calls

    assert scheduler.started is True
    assert scheduler.reload_called is True
    assert scheduler.stopped is True
    assert ("python", 100) in pipeline.calls
    assert ("hn", "hackernews", 1) in pipeline.external_calls
    assert ("reviews", "reviews", 1) in pipeline.external_calls
    assert len(messages_sent) >= 1  # macro job still uses send_message directly
    bot = FakeBot.instances[-1]
    grouped_labels = [n["label"] for n in bot.grouped_notifications]
    assert "r/python" in grouped_labels
    assert "HN" in grouped_labels
    assert "Reviews" in grouped_labels


@pytest.mark.asyncio
async def test_run_in_hermes_mode_skips_telegram_polling(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("APP_MODE", "hermes")
    monkeypatch.setenv("DIGEST_DELIVERY_ENABLED", "1")
    monkeypatch.setenv("DSPY_REDDIT_PARSER_ENABLED", "0")

    main = importlib.import_module("main")
    main = importlib.reload(main)
    main.config.APP_MODE = "hermes"
    main.config.DIGEST_DELIVERY_ENABLED = True

    class FakeDB:
        instances = []

        def __init__(self, path):
            self.path = path
            self.init_called = False
            self.close_called = False
            FakeDB.instances.append(self)

        async def init(self):
            self.init_called = True

        async def close(self):
            self.close_called = True

        async def get_pain_point(self, post_id):
            return {"title": "t", "body": "b"}

        async def is_llm_paused(self):
            return False

        async def get_pain_points_without_embeddings(self):
            return []

        async def get_pain_points_with_embeddings(self):
            return []

    class FakeScraper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeEmbedder:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeDeduplicator:
        def __init__(self, db, embedder, threshold):
            self.db = db
            self.embedder = embedder
            self.threshold = threshold

        async def backfill(self):
            return 0

    class FakeOpenRouterClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeClassifier:
        def __init__(
            self,
            openrouter,
            dspy_parser=None,
            mode="dual",
            max_concurrency=8,
            screen_min_rule_score=1,
            screen_max_llm_candidates_per_run=0,
        ):
            self.openrouter = openrouter
            self.dspy_parser = dspy_parser
            self.mode = mode
            self.max_concurrency = max_concurrency
            self.screen_min_rule_score = screen_min_rule_score
            self.screen_max_llm_candidates_per_run = screen_max_llm_candidates_per_run

    class FakePipeline:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def analyze_subreddit(self, subreddit, limit=100):
            return SimpleNamespace(signals=[], post_count=0, pain_count=0)

        async def analyze_external_posts(self, posts, source, run_scope):
            return SimpleNamespace(signals=[], post_count=0, pain_count=0)

        async def run_deep_dive(self, **kwargs):
            return SimpleNamespace(status="completed", summary="ok", error=None)

        async def generate_digest(self, subreddit=None, hours=24):
            return {"total": 0, "top_items": [], "niche_counts": {}, "source_counts": {}, "recurring_blockers": []}

    class FakeClusterer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def run(self, window_days):
            return SimpleNamespace(run_id=1, candidate_count=0, clusters=[])

    class FakeGTMGenerator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def generate(self, post_id):
            return SimpleNamespace(post_id=post_id, payload=SimpleNamespace())

    class FakeHNScraper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def fetch_posts(self, **kwargs):
            return []

    class FakeReviewScraper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def fetch_many_targets(self, **kwargs):
            return []

    class FakeExportService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeDigestService:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeDigestService.instances.append(self)

        async def build_document(self, **kwargs):
            return SimpleNamespace(total_items=0, docx_path=None, group_count=0)

    class FakeBot:
        instances = []

        def __init__(self, *args, **kwargs):
            self.app = None
            FakeBot.instances.append(self)

        def build_app(self):
            raise AssertionError("Telegram app should not be built in hermes mode")

        async def send_grouped_notification(self, *, chat_id: int, signals: list, label: str) -> None:
            return None

    class FakeScheduler:
        instances = []

        def __init__(self, db, analyze_fn, **kwargs):
            self.db = db
            self.analyze_fn = analyze_fn
            self.kwargs = kwargs
            self.started = False
            self.stopped = False
            self.reload_called = False
            FakeScheduler.instances.append(self)

        def start(self):
            self.started = True

        async def reload_jobs(self):
            self.reload_called = True

        def stop(self):
            self.stopped = True

    class FakeEvent:
        async def wait(self):
            scheduler = FakeScheduler.instances[-1]
            assert scheduler.kwargs["digest_fn"] is not None
            return None

    monkeypatch.setattr(main, "Database", FakeDB)
    monkeypatch.setattr(main, "RedditScraper", FakeScraper)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)
    monkeypatch.setattr(main, "Deduplicator", FakeDeduplicator)
    monkeypatch.setattr(main, "OpenRouterClient", FakeOpenRouterClient)
    monkeypatch.setattr(main, "Classifier", FakeClassifier)
    monkeypatch.setattr(main, "AnalysisPipeline", FakePipeline)
    monkeypatch.setattr(main, "MacroTrendClusterer", FakeClusterer)
    monkeypatch.setattr(main, "GTMGenerator", FakeGTMGenerator)
    monkeypatch.setattr(main, "HackerNewsScraper", FakeHNScraper)
    monkeypatch.setattr(main, "ReviewScraper", FakeReviewScraper)
    monkeypatch.setattr(main, "PainFinderBot", FakeBot)
    monkeypatch.setattr(main, "MonitoringScheduler", FakeScheduler)
    monkeypatch.setattr(main, "ExportService", FakeExportService)
    monkeypatch.setattr(main, "DailyDigestDocumentService", FakeDigestService)
    monkeypatch.setattr(main.asyncio, "Event", lambda: FakeEvent())

    await main.run()

    scheduler = FakeScheduler.instances[0]
    db = FakeDB.instances[0]
    assert scheduler.started is True
    assert scheduler.reload_called is True
    assert scheduler.stopped is True
    assert db.init_called is True
    assert db.close_called is True
    assert FakeDigestService.instances

