# tests/test_bot.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import (
    ANALYZE_USAGE,
    EXPORT_USAGE,
    MONITOR_USAGE,
    UNMONITOR_USAGE,
    PainFinderBot,
    format_report,
    normalize_subreddit,
    parse_analyze_args,
    parse_monitor_args,
)
from classifier import PainSignal
from scraper import Post


def _make_update():
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        message=AsyncMock(),
    )


def _make_ctx(args):
    return SimpleNamespace(args=args)


def _make_signal(post_id: str, category: str, summary: str) -> PainSignal:
    return PainSignal(
        post=Post(post_id=post_id, subreddit="python", title="T", body="", url="", score=1),
        category=category,
        summary=summary,
        severity="low",
    )


def test_normalize_subreddit_handles_r_prefix_and_case():
    assert normalize_subreddit("r/Python") == "python"
    assert normalize_subreddit("rust") == "rust"


def test_normalize_subreddit_rejects_invalid_values():
    with pytest.raises(ValueError):
        normalize_subreddit("")
    with pytest.raises(ValueError):
        normalize_subreddit("r/py-thon!")


def test_parse_analyze_args_defaults_limit():
    subreddit, limit = parse_analyze_args("r/python")
    assert subreddit == "python"
    assert limit == 100


def test_parse_analyze_args_keeps_rust_intact():
    subreddit, limit = parse_analyze_args("rust")
    assert subreddit == "rust"
    assert limit == 100


def test_parse_analyze_args_rejects_invalid_limit():
    with pytest.raises(ValueError, match="Usage: /analyze"):
        parse_analyze_args("python 0")
    with pytest.raises(ValueError, match="Usage: /analyze"):
        parse_analyze_args("python 101")
    with pytest.raises(ValueError, match="Usage: /analyze"):
        parse_analyze_args("python ten")


def test_parse_monitor_args_defaults_interval():
    subreddit, hours = parse_monitor_args("r/python")
    assert subreddit == "python"
    assert hours == 24


def test_parse_monitor_args_rejects_invalid_interval_format_or_range():
    with pytest.raises(ValueError, match="Usage: /monitor"):
        parse_monitor_args("r/python 12")
    with pytest.raises(ValueError, match="Usage: /monitor"):
        parse_monitor_args("r/python 0h")
    with pytest.raises(ValueError, match="Usage: /monitor"):
        parse_monitor_args("r/python 999h")


def test_format_report_empty():
    text = format_report("python", [])
    assert "r/python" in text
    assert "0 pain points" in text


def test_format_report_with_categories():
    signals = [
        _make_signal("p1", "complaint", "Broken import path"),
        _make_signal("p2", "unsolved", "Cannot configure env"),
        _make_signal("p3", "wish", "Need export command"),
    ]
    text = format_report("python", signals)
    assert "🔴 Complaints (1)" in text
    assert "🟡 Unsolved (1)" in text
    assert "🟢 Wishes (1)" in text
    assert "/export" in text


async def test_cmd_monitor_reload_jobs_called_once():
    db = AsyncMock()
    reload_jobs = AsyncMock()
    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=db,
        reload_jobs_fn=reload_jobs,
    )
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python", "1h"])
    await bot.cmd_monitor(update, ctx)

    db.add_monitored_subreddit.assert_awaited_once_with("python", interval_hours=1)
    reload_jobs.assert_awaited_once()
    update.message.reply_text.assert_awaited_once_with("✅ Now monitoring r/python every 1h")


async def test_cmd_unmonitor_reload_jobs_called_once():
    db = AsyncMock()
    reload_jobs = AsyncMock()
    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=db,
        reload_jobs_fn=reload_jobs,
    )
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["rust"])
    await bot.cmd_unmonitor(update, ctx)

    db.remove_monitored_subreddit.assert_awaited_once_with("rust")
    reload_jobs.assert_awaited_once()
    update.message.reply_text.assert_awaited_once_with("🗑 Stopped monitoring r/rust")


async def test_cmd_unmonitor_usage_on_invalid_input():
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx([])
    await bot.cmd_unmonitor(update, ctx)

    update.message.reply_text.assert_awaited_once_with(UNMONITOR_USAGE)


async def test_cmd_analyze_uses_injected_pipeline():
    run = SimpleNamespace(signals=[_make_signal("p1", "complaint", "Broken install")])
    analyze_fn = AsyncMock(return_value=run)
    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=AsyncMock(),
        analyze_fn=analyze_fn,
    )
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python", "10"])
    await bot.cmd_analyze(update, ctx)

    analyze_fn.assert_awaited_once_with("python", 10)
    assert update.message.reply_text.await_count == 2
    first_message = update.message.reply_text.await_args_list[0].args[0]
    second_message = update.message.reply_text.await_args_list[1].args[0]
    assert first_message.startswith("⏳ Analyzing r/python")
    assert second_message.startswith("📊 r/python")


async def test_cmd_analyze_returns_usage_on_parse_error():
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python", "999"])
    await bot.cmd_analyze(update, ctx)

    update.message.reply_text.assert_awaited_once_with(ANALYZE_USAGE)


async def test_cmd_export_usage_for_too_many_args():
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python", "extra"])
    await bot.cmd_export(update, ctx)

    update.message.reply_text.assert_awaited_once_with(EXPORT_USAGE)


async def test_cmd_export_handles_no_reports():
    db = AsyncMock()
    db.get_latest_report.return_value = None
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=db)
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx([])
    await bot.cmd_export(update, ctx)

    db.get_latest_report.assert_awaited_once_with(subreddit=None)
    update.message.reply_text.assert_awaited_once_with("No reports found yet.")


async def test_cmd_export_sends_document(tmp_path):
    report_path = tmp_path / "python_report.json"
    report_path.write_text("{}", encoding="utf-8")

    db = AsyncMock()
    db.get_latest_report.return_value = {
        "subreddit": "python",
        "json_path": str(report_path),
    }
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=db)
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python"])
    await bot.cmd_export(update, ctx)

    db.get_latest_report.assert_awaited_once_with(subreddit="python")
    update.message.reply_document.assert_awaited_once()


async def test_cmd_monitor_usage_on_bad_args():
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python", "12"])
    await bot.cmd_monitor(update, ctx)

    update.message.reply_text.assert_awaited_once_with(MONITOR_USAGE)
