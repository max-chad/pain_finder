import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from classifier import PainSignal
from db import Database
from openrouter import DeepDiveResult
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
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="DevTools",
        analysis_mode="b2b",
        analysis_payload={"sample": True},
    )

    scraper = AsyncMock()
    scraper.fetch_posts.return_value = [post]
    scraper.fetch_full_thread.return_value = ["comment"]

    openrouter = AsyncMock()
    openrouter.analyze_deep_dive.return_value = DeepDiveResult(
        workarounds=["manual reset"],
        competitors=["Tool A"],
        feature_wishlist=["auto retry"],
        buying_signals=["paying now"],
        icp_hypothesis="SMBs",
        actionable_summary="Build auto retry",
    )

    classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[signal]),
        openrouter=openrouter,
    )

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=8,
    )

    run = await pipeline.analyze_subreddit("python", limit=25)

    assert run.subreddit == "python"
    assert run.post_count == 1
    assert run.pain_count == 1
    assert run.monetizable_count == 1
    assert run.deep_dive_count == 1
    assert run.report_id > 0
    assert run.analysis_run_id > 0
    assert (tmp_path / "reports").exists()

    with open(run.json_path, "r", encoding="utf-8") as handle:
        report_payload = json.load(handle)
    assert report_payload[0]["post_id"] == "p1"

    latest = await db.get_latest_report(subreddit="python")
    assert latest is not None
    assert latest["json_path"] == run.json_path

    rows = await db.get_pain_points("python")
    assert len(rows) == 1
    assert rows[0]["post_id"] == "p1"
    assert rows[0]["deep_dive_status"] == "completed"


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
        is_monetizable=False,
        pain_level=2,
        willingness_to_pay=1,
        niche_category="Uncategorized",
        analysis_mode="legacy",
    )

    scraper = AsyncMock()
    scraper.fetch_posts.return_value = [post]
    classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[signal]),
        openrouter=AsyncMock(),
    )

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


async def test_run_deep_dive_manual_success(db, tmp_path):
    await db.insert_pain_point(
        subreddit="python",
        post_id="manual1",
        url="https://reddit.com/manual1",
        title="Need better billing sync",
        body="body",
        category="complaint",
        summary="billing sync pain",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=9,
        niche_category="FinOps",
    )

    scraper = AsyncMock()
    scraper.fetch_full_thread.return_value = ["comment A", "comment B"]

    openrouter = AsyncMock()
    openrouter.analyze_deep_dive.return_value = DeepDiveResult(
        workarounds=["manual spreadsheets"],
        competitors=["Tool B"],
        feature_wishlist=["real-time sync"],
        buying_signals=["ready to pay"],
        icp_hypothesis="SMB agencies",
        actionable_summary="Build real-time sync",
    )

    classifier = SimpleNamespace(classify_batch=AsyncMock(return_value=[]), openrouter=openrouter)
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    outcome = await pipeline.run_deep_dive(
        post_id="manual1",
        subreddit="python",
        source="manual",
        title="Need better billing sync",
        body="Body",
    )

    assert outcome.status == "completed"
    row = await db.get_pain_point("manual1")
    assert row is not None
    assert row["deep_dive_status"] == "completed"
    assert "real-time sync" in (row["deep_dive_summary"] or "")


async def test_generate_digest_returns_ranked_rows(db, tmp_path):
    await db.insert_pain_point(
        subreddit="python",
        post_id="d1",
        url="",
        title="t1",
        body="",
        category="complaint",
        summary="s1",
        severity="high",
        is_monetizable=True,
        pain_level=9,
        willingness_to_pay=8,
        niche_category="DevOps",
        deep_dive_summary="Need better alerts",
    )
    await db.insert_pain_point(
        subreddit="python",
        post_id="d2",
        url="",
        title="t2",
        body="",
        category="wish",
        summary="s2",
        severity="medium",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=7,
        niche_category="DevOps",
    )

    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    digest = await pipeline.generate_digest(subreddit="python", hours=24)
    assert digest["total"] == 2
    assert digest["top_items"][0]["post_id"] == "d1"
    assert digest["niche_counts"]["DevOps"] == 2
    assert "Need better alerts" in digest["recurring_blockers"]


async def test_analyze_external_posts_records_source(db, tmp_path):
    post = Post(
        post_id="hn:123",
        subreddit="hackernews",
        title="Internal tool pain",
        body="We built our own ETL tooling",
        url="https://news.ycombinator.com/item?id=123",
        score=12,
        source="hn",
    )
    signal = PainSignal(
        post=post,
        category="complaint",
        summary="HN complaint",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="Data",
        analysis_mode="b2b",
    )
    scraper = AsyncMock()
    classifier = SimpleNamespace(classify_batch=AsyncMock(return_value=[signal]), openrouter=AsyncMock())
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    run = await pipeline.analyze_external_posts(posts=[post], source="hn", run_scope="hackernews")

    assert run.source == "hn"
    assert run.subreddit == "hackernews"
    stored = await db.get_pain_point("hn:123")
    assert stored is not None
    assert stored["source"] == "hn"


async def test_analyze_posts_respects_llm_pause_without_budget_guard(db, tmp_path):
    await db.pause_llm(reason="cap hit")
    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(return_value=[]), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
        budget_guard=None,
    )
    with pytest.raises(RuntimeError):
        await pipeline.analyze_external_posts(posts=[], source="hn", run_scope="hn")

