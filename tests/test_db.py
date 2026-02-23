# tests/test_db.py
import pytest
import pytest_asyncio
import aiosqlite
from db import Database

@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.init()
    yield d
    await d.close()

async def test_insert_and_fetch_pain_point(db):
    await db.insert_pain_point(
        subreddit="python",
        post_id="abc123",
        url="https://reddit.com/r/python/abc123",
        title="Why is X so broken",
        body="I can't get X to work",
        category="complaint",
        summary="User frustrated with X",
        severity="medium",
    )
    results = await db.get_pain_points(subreddit="python")
    assert len(results) == 1
    assert results[0]["post_id"] == "abc123"
    assert results[0]["category"] == "complaint"

async def test_duplicate_post_id_ignored(db):
    for _ in range(2):
        await db.insert_pain_point(
            subreddit="python", post_id="dup1", url="", title="T", body="",
            category="complaint", summary="s", severity="low",
        )
    results = await db.get_pain_points(subreddit="python")
    assert len(results) == 1

async def test_monitor_subreddit_crud(db):
    await db.add_monitored_subreddit("webdev", interval_hours=6)
    subs = await db.get_monitored_subreddits()
    assert any(s["name"] == "webdev" for s in subs)

    await db.remove_monitored_subreddit("webdev")
    subs = await db.get_monitored_subreddits()
    assert not any(s["name"] == "webdev" for s in subs)

async def test_update_last_checked(db):
    await db.add_monitored_subreddit("python", interval_hours=12)
    await db.update_last_checked("python")
    subs = await db.get_monitored_subreddits()
    sub = next(s for s in subs if s["name"] == "python")
    assert sub["last_checked"] is not None

async def test_save_report(db):
    report_id = await db.save_report(
        subreddit="python", post_count=50, pain_count=12, json_path="reports/r.json"
    )
    assert report_id > 0


async def test_get_latest_report_for_subreddit(db):
    await db.save_report(
        subreddit="python", post_count=1, pain_count=1, json_path="reports/old.json"
    )
    await db.save_report(
        subreddit="python", post_count=2, pain_count=2, json_path="reports/new.json"
    )
    latest = await db.get_latest_report(subreddit="python")
    assert latest is not None
    assert latest["json_path"] == "reports/new.json"


async def test_get_latest_report_global(db):
    await db.save_report(
        subreddit="python", post_count=1, pain_count=1, json_path="reports/py.json"
    )
    await db.save_report(
        subreddit="rust", post_count=1, pain_count=1, json_path="reports/rust.json"
    )
    latest = await db.get_latest_report()
    assert latest is not None
    assert latest["subreddit"] == "rust"
