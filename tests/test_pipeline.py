# tests/test_pipeline.py
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from classifier import PainSignal
from db import Database
from pipeline import AnalysisPipeline
from scraper import Post


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test_pipeline.db"))
    await database.init()
    yield database
    await database.close()


async def test_analyze_subreddit_persists_report_and_rows(db, tmp_path):
    post = Post(
        post_id="p1",
        subreddit="python",
        title="I can't make this work",
        body="Still broken",
        url="https://reddit.com/p1",
        score=10,
    )
    signal = PainSignal(
        post=post,
        category="complaint",
        summary="User reports failure",
        severity="high",
    )

    scraper = AsyncMock()
    scraper.fetch_posts.return_value = [post]
    classifier = AsyncMock()
    classifier.classify_batch.return_value = [signal]

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    run = await pipeline.analyze_subreddit("python", limit=25)

    assert run.subreddit == "python"
    assert run.post_count == 1
    assert run.pain_count == 1
    assert run.report_id > 0
    assert len(run.signals) == 1
    assert (tmp_path / "reports").exists()
    assert run.json_path.endswith(".json")

    with open(run.json_path, "r", encoding="utf-8") as handle:
        report_payload = json.load(handle)
    assert report_payload[0]["post_id"] == "p1"

    latest = await db.get_latest_report(subreddit="python")
    assert latest is not None
    assert latest["json_path"] == run.json_path

    rows = await db.get_pain_points("python")
    assert len(rows) == 1
    assert rows[0]["post_id"] == "p1"


async def test_analyze_subreddit_cleans_tmp_file_on_atomic_write_error(db, tmp_path, monkeypatch):
    post = Post(
        post_id="p2",
        subreddit="python",
        title="Wish this existed",
        body="Need feature",
        url="https://reddit.com/p2",
        score=4,
    )
    signal = PainSignal(
        post=post,
        category="wish",
        summary="Feature request",
        severity="low",
    )

    scraper = AsyncMock()
    scraper.fetch_posts.return_value = [post]
    classifier = AsyncMock()
    classifier.classify_batch.return_value = [signal]

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    def fail_replace(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr("pipeline.os.replace", fail_replace)

    with pytest.raises(OSError):
        await pipeline.analyze_subreddit("python", limit=5)

    tmp_files = list((tmp_path / "reports").glob("*.tmp"))
    assert tmp_files == []
