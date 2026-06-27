import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from budget import BudgetCapReachedError, BudgetGuard
from dspy_parser import DSPyRedditPainParser
from openrouter import OpenRouterUsageAccountingError
from scraper import Post


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


def test_is_available_reflects_installed_dspy_package():
    with patch("dspy_parser.importlib.util.find_spec", return_value=None):
        assert DSPyRedditPainParser.is_available() is False
    with patch("dspy_parser.importlib.util.find_spec", return_value=object()):
        assert DSPyRedditPainParser.is_available() is True


def test_model_name_for_codex_provider_uses_openai_prefix():
    parser = DSPyRedditPainParser(api_key="test-key", provider="codex", model="gpt-5.3-spark")

    assert parser._model_name_for_provider() == "openai/gpt-5.3-spark"


def test_lm_kwargs_include_timeout():
    parser = DSPyRedditPainParser(api_key="test-key", provider="codex", model="gpt-5.3-spark", timeout_seconds=12.5)

    assert parser._lm_kwargs()["timeout"] == 12.5


def test_coerce_prediction_normalizes_strings_into_analysis_result():
    parser = DSPyRedditPainParser(api_key="test-key", provider="codex", model="gpt-5.3-spark")
    prediction = SimpleNamespace(
        category="complaint",
        severity="high",
        summary="Teams are still reconciling invoices manually",
        is_monetizable="true",
        pain_level="9",
        willingness_to_pay="8",
        niche_category="Finance Ops",
        competitor_tags_csv=" QuickBooks , hubspot, quickbooks ",
    )

    result = parser._coerce_prediction(prediction)

    assert result is not None
    assert result.category == "complaint"
    assert result.severity == "high"
    assert result.is_monetizable is True
    assert result.pain_level == 9
    assert result.willingness_to_pay == 8
    assert result.niche_category == "Finance Ops"
    assert result.competitor_tags == ["quickbooks", "hubspot"]


@pytest.mark.asyncio
async def test_analyze_post_checks_budget_guard_before_dspy_call(monkeypatch):
    budget_guard = AsyncMock()
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        budget_guard=budget_guard,
        pricing_map={"gpt-5.3-spark": {"prompt_per_1k": 0.002, "completion_per_1k": 0.004}},
    )
    parser._dspy = SimpleNamespace(settings=SimpleNamespace(context=lambda lm: _NullContext()))
    parser._lm = object()

    def fake_program(**kwargs):
        return SimpleNamespace(
            category="complaint",
            severity="high",
            summary="Teams reconcile invoices manually",
            is_monetizable="true",
            pain_level="9",
            willingness_to_pay="8",
            niche_category="Finance Ops",
            competitor_tags_csv="quickbooks",
        )

    monkeypatch.setattr(parser, "_ensure_program", lambda: fake_program)

    result = await parser.analyze_post(_post())

    assert result is not None
    budget_guard.ensure_can_spend.assert_awaited_once_with("dspy_analyze_post")
    budget_guard.record_usage.assert_awaited_once()
    usage_kwargs = budget_guard.record_usage.await_args.kwargs
    assert usage_kwargs["operation"] == "dspy_analyze_post"
    assert usage_kwargs["model"] == "gpt-5.3-spark"
    assert usage_kwargs["cost_usd"] > 0
    assert usage_kwargs["schema_version"] == "dspy_primary_v1"
    assert usage_kwargs["candidate_stage"] == "primary_dspy"


@pytest.mark.asyncio
async def test_analyze_post_serializes_concurrent_calls_until_usage_settles(monkeypatch):
    db = _InMemoryBudgetDb()
    budget_guard = BudgetGuard(db=db, daily_cap_usd=1.0)
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        budget_guard=budget_guard,
        pricing_map={"gpt-5.3-spark": {"prompt_per_1k": 100.0, "completion_per_1k": 0.0}},
    )
    parser._dspy = SimpleNamespace(settings=SimpleNamespace(context=lambda lm: _NullContext()))
    parser._lm = SimpleNamespace(history=[])
    first_started = asyncio.Event()
    release_first = threading.Event()
    provider_calls: list[str] = []
    loop = asyncio.get_running_loop()

    def fake_program(**kwargs):
        provider_calls.append(kwargs["title"])
        if len(provider_calls) == 1:
            loop.call_soon_threadsafe(first_started.set)
            release_first.wait()
        return SimpleNamespace(
            category="complaint",
            severity="high",
            summary="Teams reconcile invoices manually",
            is_monetizable="true",
            pain_level="9",
            willingness_to_pay="8",
            niche_category="Finance Ops",
            competitor_tags_csv="quickbooks",
        )

    monkeypatch.setattr(parser, "_ensure_program", lambda: fake_program)

    first_task = asyncio.create_task(parser.analyze_post(_post(post_id="reddit:first", title="First miss", body="Body one")))
    await asyncio.wait_for(first_started.wait(), timeout=1)

    second_task = asyncio.create_task(
        parser.analyze_post(_post(post_id="reddit:second", title="Second miss", body="Body two"))
    )
    for _ in range(3):
        await asyncio.sleep(0)
    assert provider_calls == ["First miss"]
    assert not second_task.done()

    release_first.set()
    try:
        first_result, second_result = await asyncio.wait_for(
            asyncio.gather(first_task, second_task, return_exceptions=True),
            timeout=1,
        )
    finally:
        release_first.set()
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(first_task, second_task, return_exceptions=True)

    assert first_result is not None
    assert first_result.summary == "Teams reconcile invoices manually"
    assert isinstance(second_result, BudgetCapReachedError)
    assert provider_calls == ["First miss"]
    assert len(db.recorded_usage) == 1
    assert db.recorded_usage[0]["post_id"] == "reddit:first"
    assert db.spent_today_usd >= 1.0


@pytest.mark.asyncio
async def test_analyze_post_raises_on_budget_recording_failure(monkeypatch):
    budget_guard = AsyncMock()
    budget_guard.record_usage.side_effect = RuntimeError("write failed")
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        budget_guard=budget_guard,
        pricing_map={"gpt-5.3-spark": {"prompt_per_1k": 0.002, "completion_per_1k": 0.004}},
    )
    parser._dspy = SimpleNamespace(settings=SimpleNamespace(context=lambda lm: _NullContext()))
    parser._lm = object()

    def fake_program(**kwargs):
        return SimpleNamespace(
            category="complaint",
            severity="high",
            summary="Teams reconcile invoices manually",
            is_monetizable="true",
            pain_level="9",
            willingness_to_pay="8",
            niche_category="Finance Ops",
            competitor_tags_csv="quickbooks",
        )

    monkeypatch.setattr(parser, "_ensure_program", lambda: fake_program)

    with pytest.raises(OpenRouterUsageAccountingError, match="llm_usage_record_failed"):
        await parser.analyze_post(_post())

    budget_guard.record_usage.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_post_propagates_budget_pause_before_dspy_call(monkeypatch):
    budget_guard = BudgetGuard(db=_InMemoryBudgetDb(spent_today_usd=1.0), daily_cap_usd=1.0)
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        budget_guard=budget_guard,
        pricing_map={"gpt-5.3-spark": {"prompt_per_1k": 0.002, "completion_per_1k": 0.004}},
    )
    parser._dspy = SimpleNamespace(settings=SimpleNamespace(context=lambda lm: _NullContext()))
    parser._lm = SimpleNamespace(history=[])
    program_called = False

    def fake_program(**kwargs):
        nonlocal program_called
        program_called = True
        return SimpleNamespace(
            category="complaint",
            severity="high",
            summary="Teams reconcile invoices manually",
            is_monetizable="true",
            pain_level="9",
            willingness_to_pay="8",
            niche_category="Finance Ops",
            competitor_tags_csv="quickbooks",
        )

    monkeypatch.setattr(parser, "_ensure_program", lambda: fake_program)

    with pytest.raises(BudgetCapReachedError, match="Daily budget cap reached"):
        await parser.analyze_post(_post())

    assert program_called is False


@pytest.mark.asyncio
async def test_analyze_post_records_dspy_lm_history_usage(monkeypatch):
    budget_guard = AsyncMock()
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        budget_guard=budget_guard,
        pricing_map={"gpt-5.3-spark": {"prompt_per_1k": 0.002, "completion_per_1k": 0.004}},
    )
    parser._dspy = SimpleNamespace(settings=SimpleNamespace(context=lambda lm: _NullContext()))
    parser._lm = SimpleNamespace(history=[])

    def fake_program(**kwargs):
        parser._lm.history.append({"usage": {"prompt_tokens": 50, "completion_tokens": 12}})
        return SimpleNamespace(
            category="complaint",
            severity="high",
            summary="Teams reconcile invoices manually",
            is_monetizable="true",
            pain_level="9",
            willingness_to_pay="8",
            niche_category="Finance Ops",
            competitor_tags_csv="quickbooks",
        )

    monkeypatch.setattr(parser, "_ensure_program", lambda: fake_program)

    result = await parser.analyze_post(_post())

    assert result is not None
    usage_kwargs = budget_guard.record_usage.await_args.kwargs
    assert usage_kwargs["prompt_tokens"] == 50
    assert usage_kwargs["completion_tokens"] == 12
    assert usage_kwargs["cost_usd"] == 0.000148


@pytest.mark.asyncio
async def test_analyze_post_skips_dspy_when_budget_guard_has_no_pricing(monkeypatch):
    budget_guard = AsyncMock()
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        budget_guard=budget_guard,
        pricing_map={},
    )
    ensure_program = AsyncMock()
    monkeypatch.setattr(parser, "_ensure_program", ensure_program)

    result = await parser.analyze_post(_post())

    assert result is None
    budget_guard.ensure_can_spend.assert_not_awaited()
    budget_guard.record_usage.assert_not_called()
    ensure_program.assert_not_called()


def test_usage_from_object_tolerates_overflow_token_counts():
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        pricing_map={"gpt-5.3-spark": {"prompt_per_1k": 0.001, "completion_per_1k": 0.002}},
    )

    assert parser._usage_from_object({"prompt_tokens": float("inf"), "completion_tokens": 12}) == {
        "prompt_tokens": 0,
        "completion_tokens": 12,
    }


@pytest.mark.asyncio
async def test_analyze_post_times_out_slow_dspy_program(monkeypatch):
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        timeout_seconds=0.1,
    )
    parser._dspy = SimpleNamespace(settings=SimpleNamespace(context=lambda lm: _NullContext()))
    parser._lm = object()

    def slow_program(**kwargs):
        time.sleep(0.25)
        return SimpleNamespace(
            category="complaint",
            severity="high",
            summary="Teams reconcile invoices manually",
            is_monetizable="true",
            pain_level="9",
            willingness_to_pay="8",
            niche_category="Finance Ops",
            competitor_tags_csv="quickbooks",
        )

    monkeypatch.setattr(parser, "_ensure_program", lambda: slow_program)

    result = await parser.analyze_post(_post())

    assert result is None


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


def _post(
    *,
    post_id: str = "reddit:one",
    title: str = "Manual invoice reconciliation hurts",
    body: str = "We spend hours on this every week.",
) -> Post:
    return Post(
        post_id=post_id,
        subreddit="python",
        title=title,
        body=body,
        url="https://example.com/post",
        score=1,
    )
