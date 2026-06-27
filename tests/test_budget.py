import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from budget import BudgetCapReachedError, BudgetGuard


class _InMemoryBudgetDb:
    def __init__(self, *, spent_today_usd: float = 0.0):
        self.spent_today_usd = spent_today_usd
        self.paused = False
        self.runtime_flags = {"pause_reason": None, "resume_override_until": None}
        self.recorded_usage: list[dict[str, object]] = []

    async def get_runtime_flags(self):
        return dict(self.runtime_flags)

    async def get_daily_spend_usd(self, *_args):
        return self.spent_today_usd

    async def is_llm_paused(self, *_args):
        return self.paused

    async def pause_llm(self, *, reason: str, pause_day):
        self.paused = True
        self.runtime_flags["pause_reason"] = reason
        self.runtime_flags["paused_on"] = pause_day.isoformat()

    async def record_llm_usage(self, **kwargs):
        self.recorded_usage.append(dict(kwargs))
        self.spent_today_usd += float(kwargs["cost_usd"])

    async def set_resume_override_until(self, resume_until):
        self.runtime_flags["resume_override_until"] = resume_until.isoformat()


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


async def test_admit_serializes_concurrent_calls_until_usage_settles():
    db = _InMemoryBudgetDb()
    guard = BudgetGuard(db=db, daily_cap_usd=1.0)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    events: list[str] = []

    async def first_call():
        async with await guard.admit("classify_primary"):
            events.append("first_entered")
            first_entered.set()
            await release_first.wait()
            await guard.record_usage(
                model="m1",
                operation="classify_primary",
                prompt_tokens=1000,
                completion_tokens=0,
                cost_usd=1.0,
                post_id="reddit:first",
            )
            events.append("first_recorded")

    async def second_call():
        await first_entered.wait()
        with pytest.raises(BudgetCapReachedError):
            async with await guard.admit("classify_primary"):
                events.append("second_entered")
        events.append("second_rejected")

    first_task = asyncio.create_task(first_call())
    second_task = asyncio.create_task(second_call())
    wait_first_entered = asyncio.create_task(first_entered.wait())

    try:
        done, _pending = await asyncio.wait(
            {wait_first_entered, first_task},
            timeout=1,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if first_task in done:
            await first_task
        assert wait_first_entered in done, "first admission did not enter before timeout"

        await asyncio.sleep(0)
        assert events == ["first_entered"]

        release_first.set()
        await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=1)
    finally:
        release_first.set()
        for task in (wait_first_entered, first_task, second_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(wait_first_entered, first_task, second_task, return_exceptions=True)

    assert events == ["first_entered", "first_recorded", "second_rejected"]
    assert db.spent_today_usd == pytest.approx(1.0)
    assert db.recorded_usage[0]["post_id"] == "reddit:first"
