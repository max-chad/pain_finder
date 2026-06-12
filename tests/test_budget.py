from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from budget import BudgetCapReachedError, BudgetGuard


async def test_get_status_reads_db_values():
    db = AsyncMock()
    db.get_runtime_flags.return_value = {
        "pause_reason": "cap",
        "resume_override_until": "2026-02-24T12:00:00+00:00",
    }
    db.get_daily_spend_usd.return_value = 1.25
    db.is_llm_paused.return_value = True

    guard = BudgetGuard(db=db, daily_cap_usd=2.0)
    status = await guard.get_status()

    assert status.daily_cap_usd == 2.0
    assert status.spent_today_usd == 1.25
    assert status.llm_paused is True
    assert status.pause_reason == "cap"


async def test_ensure_can_spend_allows_with_resume_override():
    now = datetime.now(UTC)
    db = AsyncMock()
    db.get_runtime_flags.return_value = {
        "resume_override_until": (now + timedelta(hours=2)).isoformat(),
    }
    guard = BudgetGuard(db=db, daily_cap_usd=1.0)

    await guard.ensure_can_spend("classify")

    db.get_daily_spend_usd.assert_not_awaited()


async def test_ensure_can_spend_pauses_on_cap_and_invokes_callback():
    db = AsyncMock()
    db.get_runtime_flags.return_value = {"resume_override_until": None}
    db.get_daily_spend_usd.return_value = 2.5
    db.is_llm_paused.return_value = False

    callback = AsyncMock()
    guard = BudgetGuard(db=db, daily_cap_usd=2.0)
    guard.set_on_pause_callback(callback)

    with pytest.raises(BudgetCapReachedError):
        await guard.ensure_can_spend("deep_dive")

    db.pause_llm.assert_awaited_once()
    callback.assert_awaited_once()


async def test_ensure_can_spend_raises_when_runtime_paused():
    db = AsyncMock()
    db.get_runtime_flags.return_value = {"resume_override_until": None}
    db.get_daily_spend_usd.return_value = 0.1
    db.is_llm_paused.return_value = True
    guard = BudgetGuard(db=db, daily_cap_usd=2.0)

    with pytest.raises(BudgetCapReachedError):
        await guard.ensure_can_spend("cluster_label")


async def test_record_usage_writes_and_triggers_pause_if_crossed():
    db = AsyncMock()
    db.get_runtime_flags.return_value = {"pause_reason": None, "resume_override_until": None}
    db.get_daily_spend_usd.return_value = 2.1
    db.is_llm_paused.return_value = False
    callback = AsyncMock()

    guard = BudgetGuard(db=db, daily_cap_usd=2.0)
    guard.set_on_pause_callback(callback)
    await guard.record_usage(
        model="m",
        operation="classify_primary",
        prompt_tokens=100,
        completion_tokens=30,
        cost_usd=0.2,
        post_id="reddit:abc",
    )

    db.record_llm_usage.assert_awaited_once()
    db.pause_llm.assert_awaited_once()
    callback.assert_awaited_once()


async def test_record_usage_respects_active_resume_override_when_cap_is_crossed():
    now = datetime.now(UTC)
    db = AsyncMock()
    db.get_runtime_flags.return_value = {
        "pause_reason": None,
        "resume_override_until": (now + timedelta(hours=2)).isoformat(),
    }
    db.get_daily_spend_usd.return_value = 2.1
    db.is_llm_paused.return_value = False
    callback = AsyncMock()

    guard = BudgetGuard(db=db, daily_cap_usd=2.0)
    guard.set_on_pause_callback(callback)
    await guard.record_usage(
        model="m",
        operation="classify_primary",
        prompt_tokens=100,
        completion_tokens=30,
        cost_usd=0.2,
        post_id="reddit:abc",
    )

    db.record_llm_usage.assert_awaited_once()
    db.pause_llm.assert_not_awaited()
    callback.assert_not_awaited()


async def test_resume_until_next_utc_day_sets_override():
    db = AsyncMock()
    guard = BudgetGuard(db=db, daily_cap_usd=2.0)

    resume_until = await guard.resume_until_next_utc_day()

    assert resume_until.tzinfo == UTC
    assert resume_until.hour == 0
    assert resume_until.minute == 0
    db.set_resume_override_until.assert_awaited_once()
