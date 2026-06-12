import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from budget import BudgetCapReachedError
from dspy_parser import DSPyRedditPainParser
from scraper import Post


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
async def test_analyze_post_propagates_budget_pause_before_dspy_call(monkeypatch):
    budget_guard = AsyncMock()
    budget_guard.ensure_can_spend.side_effect = BudgetCapReachedError("paused")
    parser = DSPyRedditPainParser(
        api_key="test-key",
        provider="codex",
        model="gpt-5.3-spark",
        budget_guard=budget_guard,
        pricing_map={"gpt-5.3-spark": {"prompt_per_1k": 0.002, "completion_per_1k": 0.004}},
    )
    ensure_program = AsyncMock()
    monkeypatch.setattr(parser, "_ensure_program", ensure_program)

    with pytest.raises(BudgetCapReachedError, match="paused"):
        await parser.analyze_post(_post())

    ensure_program.assert_not_called()


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


def _post() -> Post:
    return Post(
        post_id="reddit:one",
        subreddit="python",
        title="Manual invoice reconciliation hurts",
        body="We spend hours on this every week.",
        url="https://example.com/post",
        score=1,
    )
