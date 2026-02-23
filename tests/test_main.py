# tests/test_main.py
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

    class FakeScraper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeOpenRouterClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeClassifier:
        def __init__(self, openrouter):
            self.openrouter = openrouter

    class FakePipeline:
        instances = []

        def __init__(self, scraper, classifier, db, reports_dir):
            self.scraper = scraper
            self.classifier = classifier
            self.db = db
            self.reports_dir = reports_dir
            self.calls = []
            FakePipeline.instances.append(self)

        async def analyze_subreddit(self, subreddit, limit=100):
            self.calls.append((subreddit, limit))
            return SimpleNamespace(signals=[])

    class FakeUpdater:
        def __init__(self):
            self.start_polling_called = False
            self.stop_called = False

        async def start_polling(self):
            self.start_polling_called = True

        async def stop(self):
            self.stop_called = True

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

    class _AsyncRecorder:
        def __init__(self):
            self.calls = []

        async def __call__(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    class FakeBot:
        instances = []

        def __init__(self, scraper, classifier, db, reload_jobs_fn=None, analyze_fn=None):
            self.scraper = scraper
            self.classifier = classifier
            self.db = db
            self.reload_jobs_fn = reload_jobs_fn
            self.analyze_fn = analyze_fn
            self.app = None
            FakeBot.instances.append(self)

        def build_app(self):
            self.app = FakeTelegramApp()
            return self.app

    class FakeScheduler:
        instances = []

        def __init__(self, db, analyze_fn):
            self.db = db
            self.analyze_fn = analyze_fn
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
    assert telegram_app.start_called is True
    assert telegram_app.updater.start_polling_called is True
    assert telegram_app.updater.stop_called is True
    assert telegram_app.stop_called is True
    assert pipeline.calls[-1] == ("python", 100)
    assert len(telegram_app.bot.send_message.calls) == 1
