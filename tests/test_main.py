import importlib
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_run_wires_components_and_teardown(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    main = importlib.import_module("main")
    main = importlib.reload(main)
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

    class FakeOpenRouterClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeClassifier:
        def __init__(self, openrouter, mode="dual"):
            self.openrouter = openrouter
            self.mode = mode

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
        ):
            self.scraper = scraper
            self.classifier = classifier
            self.db = db
            self.reports_dir = reports_dir
            self.budget_guard = budget_guard
            self.calls = []
            self.deep_dive_calls = []
            self.digest_calls = []
            FakePipeline.instances.append(self)

        async def analyze_subreddit(self, subreddit, limit=100):
            self.calls.append((subreddit, limit))
            return SimpleNamespace(signals=[])

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
            FakeBot.instances.append(self)

        def build_app(self):
            self.app = FakeTelegramApp()
            return self.app

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
    monkeypatch.setattr(main, "OpenRouterClient", FakeOpenRouterClient)
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
    assert len(telegram_app.bot.send_message.calls) == 1


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

    class FakeOpenRouterClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.gtm_model = "gpt-test"

    class FakeClassifier:
        def __init__(self, openrouter, mode="dual"):
            self.openrouter = openrouter
            self.mode = mode

    class FakePipeline:
        instances = []

        def __init__(self, **kwargs):
            self.calls = []
            self.external_calls = []
            FakePipeline.instances.append(self)

        async def analyze_subreddit(self, subreddit, limit=100):
            self.calls.append((subreddit, limit))
            return SimpleNamespace(signals=[], post_count=0, pain_count=0)

        async def analyze_external_posts(self, posts, source, run_scope):
            self.external_calls.append((source, run_scope, len(posts)))
            return SimpleNamespace(post_count=len(posts), pain_count=1)

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
            FakeBot.instances.append(self)

        def build_app(self):
            self.app = FakeTelegramApp()
            return self.app

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
    assert len(messages_sent) >= 3

