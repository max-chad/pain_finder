import time as _time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import (
    ANALYZE_USAGE,
    DEEPDIVE_USAGE,
    DIGEST_USAGE,
    EXPORT_USAGE,
    GTM_USAGE,
    MONITOR_USAGE,
    UNMONITOR_USAGE,
    PainFinderBot,
    format_report,
    normalize_subreddit,
    parse_analyze_args,
    parse_deepdive_args,
    parse_digest_args,
    parse_monitor_args,
)
from classifier import PainSignal
from export_sheets import ExportResult
from scraper import Post


def _make_update():
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        message=AsyncMock(),
        callback_query=None,
    )


def _make_ctx(args):
    return SimpleNamespace(args=args)


def _make_signal(post_id: str, category: str, summary: str, *, monetizable: bool = True) -> PainSignal:
    return PainSignal(
        post=Post(post_id=post_id, subreddit="python", title="T", body="", url="https://reddit.com/p", score=1),
        category=category,
        summary=summary,
        severity="low",
        is_monetizable=monetizable,
        pain_level=8 if monetizable else 2,
        willingness_to_pay=9 if monetizable else 1,
        niche_category="DevTools",
        analysis_mode="b2b",
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


def test_parse_deepdive_args_requires_post_id():
    assert parse_deepdive_args("abc123") == "abc123"
    with pytest.raises(ValueError, match="Usage: /deepdive"):
        parse_deepdive_args("")


def test_parse_digest_args_variants():
    subreddit, hours = parse_digest_args("")
    assert subreddit is None and hours == 24

    subreddit, hours = parse_digest_args("r/python 12")
    assert subreddit == "python" and hours == 12

    subreddit, hours = parse_digest_args("36")
    assert subreddit is None and hours == 36

    with pytest.raises(ValueError, match="Usage: /digest"):
        parse_digest_args("r/python bad")


def test_format_report_empty():
    text = format_report("python", [])
    assert "r/python" in text
    assert "0 pain points" in text


def test_format_report_with_categories_and_monetizable_count():
    signals = [
        _make_signal("p1", "complaint", "Broken import path", monetizable=True),
        _make_signal("p2", "unsolved", "Cannot configure env", monetizable=False),
        _make_signal("p3", "wish", "Need export command", monetizable=True),
    ]
    text = format_report("python", signals)
    assert "Complaints" in text
    assert "Unsolved" in text
    assert "Wishes" in text
    assert "Monetizable: 2" in text


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
    update.message.reply_text.assert_awaited_once_with("Now monitoring r/python every 1h")


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
    update.message.reply_text.assert_awaited_once_with("Stopped monitoring r/rust")


async def test_cmd_unmonitor_usage_on_invalid_input():
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx([])
    await bot.cmd_unmonitor(update, ctx)

    update.message.reply_text.assert_awaited_once_with(UNMONITOR_USAGE)


async def test_cmd_analyze_uses_injected_pipeline_and_sends_cards(monkeypatch):
    run = SimpleNamespace(signals=[_make_signal("p1", "complaint", "Broken install")])
    analyze_fn = AsyncMock(return_value=run)
    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=AsyncMock(),
        analyze_fn=analyze_fn,
    )
    bot._is_authorized = lambda update: True

    send_cards = AsyncMock()
    monkeypatch.setattr(bot, "_send_top_signal_cards", send_cards)

    update = _make_update()
    ctx = _make_ctx(["r/python", "10"])
    await bot.cmd_analyze(update, ctx)

    analyze_fn.assert_awaited_once_with("python", 10)
    assert update.message.reply_text.await_count == 2
    send_cards.assert_awaited_once()


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


async def test_cmd_export_uses_export_service_with_warning(tmp_path):
    csv_path = tmp_path / "export.csv"
    csv_path.write_text("header\n", encoding="utf-8")

    export_service = AsyncMock()
    export_service.export.return_value = ExportResult(
        csv_path=str(csv_path),
        row_count=3,
        sheet_url=None,
        warning="Google Sheets export failed",
    )

    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=AsyncMock(),
        export_service=export_service,
    )
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python"])
    await bot.cmd_export(update, ctx)

    export_service.export.assert_awaited_once_with(subreddit="python")
    update.message.reply_document.assert_awaited_once()
    assert update.message.reply_text.await_count == 1


async def test_cmd_deepdive_runs_injected_function():
    db = AsyncMock()
    db.get_pain_point.return_value = {"subreddit": "python"}
    deep_dive_fn = AsyncMock(return_value=SimpleNamespace(status="completed", summary="Done", error=None))

    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=db,
        deep_dive_fn=deep_dive_fn,
    )
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["abc123"])
    await bot.cmd_deepdive(update, ctx)

    deep_dive_fn.assert_awaited_once_with("abc123", "python", "manual")
    assert update.message.reply_text.await_count == 2


async def test_cmd_deepdive_usage_on_bad_args():
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx([])
    await bot.cmd_deepdive(update, ctx)

    update.message.reply_text.assert_awaited_once_with(DEEPDIVE_USAGE)


async def test_cmd_digest_formats_result():
    digest_fn = AsyncMock(
        return_value={
            "total": 2,
            "hours": 24,
            "subreddit": "python",
            "top_items": [
                {"post_id": "p1", "weighted_score": 9, "willingness_to_pay": 9, "pain_level": 9, "summary": "Need better sync"}
            ],
            "niche_counts": {"DevOps": 2},
            "recurring_blockers": ["Need better sync"],
        }
    )

    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=AsyncMock(),
        digest_fn=digest_fn,
    )
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python", "24"])
    await bot.cmd_digest(update, ctx)

    digest_fn.assert_awaited_once_with("python", 24)
    update.message.reply_text.assert_awaited_once()


async def test_cmd_digest_usage_on_bad_args():
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python", "bad"])
    await bot.cmd_digest(update, ctx)

    update.message.reply_text.assert_awaited_once_with(DIGEST_USAGE)


async def test_callback_query_updates_triage_status():
    db = AsyncMock()
    db.update_triage_status.return_value = True

    query = SimpleNamespace(
        data="triage:favorite:abc123",
        answer=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), callback_query=query)

    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=db)
    bot._is_authorized = lambda update: True

    await bot.on_callback_query(update, None)

    db.update_triage_status.assert_awaited_once_with("abc123", "favorite")
    query.answer.assert_awaited_once()


async def test_callback_query_runs_deep_dive():
    db = AsyncMock()
    deep_dive_fn = AsyncMock(return_value=SimpleNamespace(status="completed", summary="Done", error=None))

    query = SimpleNamespace(
        data="deepdive:abc123:python",
        answer=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), callback_query=query)

    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=db,
        deep_dive_fn=deep_dive_fn,
    )
    bot._is_authorized = lambda update: True

    await bot.on_callback_query(update, None)

    deep_dive_fn.assert_awaited_once_with("abc123", "python", "callback")
    assert query.message.reply_text.await_count == 1


async def test_cmd_macro_triggers_injected_clusterer():
    macro_fn = AsyncMock(
        return_value=SimpleNamespace(
            run_id=1,
            candidate_count=10,
            clusters=[
                SimpleNamespace(
                    label="QuickBooks API",
                    item_count=5,
                    estimated_monetization_signal="high",
                    aggregate_wtp=41.0,
                    summary="Integration failures across SMB tooling",
                )
            ],
        )
    )
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock(), macro_fn=macro_fn)
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["14"])
    await bot.cmd_macro(update, ctx)

    macro_fn.assert_awaited_once_with(14)
    assert update.message.reply_text.await_count == 2


async def test_cmd_budget_reports_status():
    status = SimpleNamespace(
        daily_cap_usd=2.0,
        spent_today_usd=1.125,
        llm_paused=True,
        pause_reason="budget_cap_reached",
        resume_override_until=None,
    )
    budget_status_fn = AsyncMock(return_value=status)
    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=AsyncMock(),
        budget_status_fn=budget_status_fn,
    )
    bot._is_authorized = lambda update: True

    update = _make_update()
    await bot.cmd_budget(update, _make_ctx([]))

    budget_status_fn.assert_awaited_once()
    update.message.reply_text.assert_awaited_once()
    assert "Daily cap: $2.00" in update.message.reply_text.await_args.args[0]
    assert "LLM paused: yes" in update.message.reply_text.await_args.args[0]


async def test_cmd_resume_calls_reload():
    from datetime import UTC, datetime, timedelta

    reload_jobs = AsyncMock()
    resume_budget_fn = AsyncMock(return_value=datetime.now(UTC) + timedelta(hours=3))
    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=AsyncMock(),
        resume_budget_fn=resume_budget_fn,
        reload_jobs_fn=reload_jobs,
    )
    bot._is_authorized = lambda update: True

    update = _make_update()
    await bot.cmd_resume(update, _make_ctx([]))

    resume_budget_fn.assert_awaited_once()
    reload_jobs.assert_awaited_once()
    update.message.reply_text.assert_awaited_once()


async def test_cmd_gtm_success():
    gtm_payload = SimpleNamespace(
        name_options=["SyncPilot", "LedgerFlow", "ReconMate"],
        hero_h1="Stop losing revenue to failed sync jobs",
        hero_h2="Fix accounting and commerce data flows in minutes",
        mvp_features=["Retry queue", "Alert routing", "Audit trail"],
        pricing_tier="$49/mo Starter",
        positioning_rationale="Built for small finance teams",
    )
    gtm_fn = AsyncMock(return_value=SimpleNamespace(post_id="reddit:abc123", payload=gtm_payload))
    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=AsyncMock(),
        gtm_fn=gtm_fn,
    )
    bot._is_authorized = lambda update: True

    update = _make_update()
    await bot.cmd_gtm(update, _make_ctx(["reddit:abc123"]))

    gtm_fn.assert_awaited_once_with("reddit:abc123")
    assert update.message.reply_text.await_count == 2
    assert "GTM package for reddit:abc123" in update.message.reply_text.await_args.args[0]


async def test_cmd_gtm_usage_on_bad_args():
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock(), gtm_fn=AsyncMock())
    bot._is_authorized = lambda update: True

    update = _make_update()
    await bot.cmd_gtm(update, _make_ctx([]))

    update.message.reply_text.assert_awaited_once_with(GTM_USAGE)


async def test_callback_query_runs_gtm():
    gtm_payload = SimpleNamespace(
        name_options=["A", "B", "C"],
        hero_h1="H1",
        hero_h2="H2",
        mvp_features=["f1", "f2", "f3"],
        pricing_tier="$19",
        positioning_rationale="why",
    )
    gtm_fn = AsyncMock(return_value=SimpleNamespace(post_id="reddit:abc123", payload=gtm_payload))

    query = SimpleNamespace(
        data="gtm:reddit:abc123:reddit",
        answer=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), callback_query=query)

    bot = PainFinderBot(
        scraper=AsyncMock(),
        classifier=AsyncMock(),
        db=AsyncMock(),
        gtm_fn=gtm_fn,
    )
    bot._is_authorized = lambda update: True

    await bot.on_callback_query(update, None)

    gtm_fn.assert_awaited_once_with("reddit:abc123")
    query.answer.assert_awaited()
    query.message.reply_text.assert_awaited_once()


async def test_cmd_monitor_usage_on_bad_args():
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True

    update = _make_update()
    ctx = _make_ctx(["r/python", "12"])
    await bot.cmd_monitor(update, ctx)

    update.message.reply_text.assert_awaited_once_with(MONITOR_USAGE)


async def test_send_top_signal_cards_calls_get_pain_points_by_ids_with_correct_ids(monkeypatch):
    """_send_top_signal_cards must batch-fetch DB rows using the post_ids from
    the top monetizable candidate signals (not mocked away)."""
    from unittest.mock import MagicMock

    # Stub out the telegram keyboard classes imported inside the method.
    monkeypatch.setattr("telegram.InlineKeyboardButton", MagicMock(), raising=False)
    monkeypatch.setattr("telegram.InlineKeyboardMarkup", MagicMock(return_value=MagicMock()), raising=False)

    db = AsyncMock()
    # get_pain_points_by_ids returns a dict keyed by post_id.
    db.get_pain_points_by_ids.return_value = {
        "p1": {"triage_status": "new"},
        "p2": {"triage_status": "new"},
    }

    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=db)

    signals = [
        _make_signal("p1", "complaint", "Summary one", monetizable=True),
        _make_signal("p2", "unsolved", "Summary two", monetizable=True),
    ]

    update = _make_update()
    await bot._send_top_signal_cards(update, signals)

    # The method must have called get_pain_points_by_ids with the post_ids of
    # the candidate signals in the order they appear after sorting.
    db.get_pain_points_by_ids.assert_awaited_once()
    called_ids = db.get_pain_points_by_ids.await_args.args[0]
    assert set(called_ids) == {"p1", "p2"}

    # Both non-discarded signals should have produced a card message.
    assert update.message.reply_text.await_count == 2


async def test_send_top_signal_cards_skips_discarded_signals(monkeypatch):
    """Signals whose DB row has triage_status=='discarded' must not produce a card."""
    from unittest.mock import MagicMock

    monkeypatch.setattr("telegram.InlineKeyboardButton", MagicMock(), raising=False)
    monkeypatch.setattr("telegram.InlineKeyboardMarkup", MagicMock(return_value=MagicMock()), raising=False)

    db = AsyncMock()
    # p1 is discarded; p2 is active.
    db.get_pain_points_by_ids.return_value = {
        "p1": {"triage_status": "discarded"},
        "p2": {"triage_status": "favorite"},
    }

    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=db)

    signals = [
        _make_signal("p1", "complaint", "Should be filtered out", monetizable=True),
        _make_signal("p2", "unsolved", "Should appear", monetizable=True),
    ]

    update = _make_update()
    await bot._send_top_signal_cards(update, signals)

    # get_pain_points_by_ids must still be called with both IDs.
    db.get_pain_points_by_ids.assert_awaited_once()
    called_ids = db.get_pain_points_by_ids.await_args.args[0]
    assert set(called_ids) == {"p1", "p2"}

    # Only the non-discarded signal (p2) should produce a card.
    assert update.message.reply_text.await_count == 1
    sent_text = update.message.reply_text.await_args.args[0]
    assert "p2" in sent_text
    assert "p1" not in sent_text


def _make_bot() -> PainFinderBot:
    """Minimal PainFinderBot for unit tests (no Telegram app)."""
    bot = PainFinderBot(scraper=AsyncMock(), classifier=AsyncMock(), db=AsyncMock())
    bot._is_authorized = lambda update: True
    return bot


def test_sessions_dict_initialized_empty():
    bot = _make_bot()
    assert bot._sessions == {}


def test_create_session_returns_8char_token_and_stores_session():
    bot = _make_bot()
    signals = [_make_signal("p1", "complaint", "Something is broken")]
    token = bot._create_session(signals, "r/python")
    assert len(token) == 8
    assert token in bot._sessions
    session = bot._sessions[token]
    assert session["label"] == "r/python"
    assert len(session["signals"]) == 1
    assert session["shown_count"] == 1  # min(5, 1)


def test_create_session_sorts_signals_by_wtp_desc():
    bot = _make_bot()
    low = _make_signal("p_low", "complaint", "Low WTP")
    high = _make_signal("p_high", "complaint", "High WTP")
    low.willingness_to_pay = 3
    high.willingness_to_pay = 9
    token = bot._create_session([low, high], "r/python")
    assert bot._sessions[token]["signals"][0].post.post_id == "p_high"


def test_evict_old_sessions_removes_expired():
    bot = _make_bot()
    signals = [_make_signal("p1", "complaint", "x")]
    token = bot._create_session(signals, "r/python")
    # Backdate the session
    bot._sessions[token]["created_at"] = _time.time() - 86401
    # Trigger eviction by creating a new session
    bot._create_session(signals, "r/python")
    assert token not in bot._sessions


def test_evict_old_sessions_keeps_recent():
    bot = _make_bot()
    signals = [_make_signal("p1", "complaint", "x")]
    token = bot._create_session(signals, "r/python")
    bot._create_session(signals, "r/python")  # trigger eviction
    assert token in bot._sessions  # recent session kept


def test_render_list_view_contains_label_and_items():
    bot = _make_bot()
    signals = [_make_signal(f"p{i}", "complaint", f"Issue number {i}") for i in range(7)]
    for i, s in enumerate(signals):
        s.willingness_to_pay = 9 - i
    token = bot._create_session(signals, "r/python")
    session = bot._sessions[token]
    text, keyboard = bot._render_list_view(token, session)
    assert "r/python" in text
    assert "7 pain points" in text
    assert "1." in text
    assert "5." in text
    assert "6." not in text  # only 5 shown initially
    # Load more button present
    buttons_flat = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert any("Load more" in b for b in buttons_flat)
    # 5 numbered buttons
    assert any(b == "1" for b in buttons_flat)
    assert any(b == "5" for b in buttons_flat)


def test_render_list_view_no_load_more_when_all_shown():
    bot = _make_bot()
    signals = [_make_signal(f"p{i}", "complaint", f"Issue {i}") for i in range(3)]
    token = bot._create_session(signals, "HN")
    session = bot._sessions[token]
    text, keyboard = bot._render_list_view(token, session)
    buttons_flat = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert not any("Load more" in b for b in buttons_flat)


def test_render_card_view_contains_post_details():
    bot = _make_bot()
    signal = _make_signal("post_abc", "complaint", "Really annoying bug")
    signal.willingness_to_pay = 8
    signal.pain_level = 9
    token = bot._create_session([signal], "r/python")
    session = bot._sessions[token]
    text, keyboard = bot._render_card_view(token, session, 0)
    assert "Really annoying bug" in text
    assert "WTP: 8/10" in text
    assert "Pain: 9/10" in text
    # Back button present
    buttons_flat = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert any("Back" in b for b in buttons_flat)
    # Favorite and Discard buttons present
    assert any("Favorite" in b for b in buttons_flat)
    assert any("Discard" in b for b in buttons_flat)
    assert any("Deep Dive" in b for b in buttons_flat)
    assert any("GTM" in b for b in buttons_flat)


def test_sel_callback_data_format():
    """sel: callback_data stays within Telegram's 64-byte limit."""
    bot = _make_bot()
    signal = _make_signal("p1", "complaint", "x")
    token = bot._create_session([signal], "r/python")
    session = bot._sessions[token]
    _, keyboard = bot._render_list_view(token, session)
    cb = keyboard.inline_keyboard[0][0].callback_data
    assert cb.startswith("sel:")
    assert len(cb.encode()) <= 64
