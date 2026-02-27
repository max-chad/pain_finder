from unittest.mock import AsyncMock

from classifier import Classifier
from openrouter import AnalysisResult
from scraper import Post


def make_post(title="", body="", post_id="p1"):
    return Post(
        post_id=post_id,
        subreddit="test",
        title=title,
        body=body,
        url="",
        score=10,
    )


def test_keyword_score_high_for_clear_complaint():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(title="I can't get this to work, so frustrated"))
    assert score >= 2


def test_keyword_score_zero_for_neutral():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(title="Cool new project announcement"))
    assert score == 0


def test_keyword_score_max_is_3():
    clf = Classifier(openrouter=None)
    score = clf.keyword_score(make_post(title="I can't do this, wish it worked, help me please"))
    assert score == 3


async def test_classify_skips_llm_for_zero_score():
    mock_llm = AsyncMock()
    clf = Classifier(openrouter=mock_llm, mode="dual")
    result = await clf.classify(make_post(title="Random announcement post"))
    mock_llm.analyze_post.assert_not_called()
    assert result is None


async def test_dual_mode_uses_primary_b2b_result():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint",
        summary="Users lose revenue",
        severity="high",
        is_monetizable=True,
        pain_level=9,
        willingness_to_pay=9,
        niche_category="E-commerce",
    )
    clf = Classifier(openrouter=mock_llm, mode="dual")
    result = await clf.classify(make_post(title="Shopify stock sync broken"))
    assert result is not None
    assert result.is_monetizable is True
    assert result.willingness_to_pay == 9
    assert result.analysis_mode == "b2b"


async def test_dual_mode_falls_back_to_legacy_llm():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = None
    mock_llm.analyze_legacy_post.return_value = AnalysisResult(
        category="wish",
        summary="Need exports",
        severity="low",
    )
    clf = Classifier(openrouter=mock_llm, mode="dual")
    result = await clf.classify(make_post(title="I wish this had export feature"))
    assert result is not None
    assert result.category == "wish"
    assert result.analysis_mode == "legacy_llm"


async def test_b2b_mode_returns_none_when_model_fails():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = None
    clf = Classifier(openrouter=mock_llm, mode="b2b")
    result = await clf.classify(make_post(title="I can't get this working"))
    assert result is None


async def test_legacy_mode_uses_keyword_fallback_without_llm():
    clf = Classifier(openrouter=None, mode="legacy")
    result = await clf.classify(make_post(title="I can't figure this out, stuck on it for days"))
    assert result is not None
    assert result.category == "complaint"
    assert result.analysis_mode == "legacy"


async def test_b2c_noise_is_rejected_as_non_monetizable():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint",
        summary="Lag in game",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=9,
        niche_category="Gaming",
    )
    clf = Classifier(openrouter=mock_llm, mode="b2b")
    result = await clf.classify(make_post(title="Fortnite game is broken and keeps lagging"))
    assert result is not None
    assert result.is_monetizable is False
    assert result.willingness_to_pay == 0


async def test_classify_batch_filters_nones():
    clf = Classifier(openrouter=None, mode="legacy")
    posts = [
        make_post(title="Cool announcement", post_id="p1"),
        make_post(title="I can't get this working", post_id="p2"),
        make_post(title="Wish this had dark mode", post_id="p3"),
    ]
    signals = await clf.classify_batch(posts)
    pain_ids = {signal.post.post_id for signal in signals}
    assert "p2" in pain_ids and "p3" in pain_ids
    assert "p1" not in pain_ids


async def test_competitor_tags_are_propagated_and_normalized():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint",
        summary="Shopify and Jira integration pain",
        severity="high",
        is_monetizable=True,
        pain_level=9,
        willingness_to_pay=8,
        niche_category="E-commerce",
        competitor_tags=[" Shopify ", "jira", "shopify"],
    )
    clf = Classifier(openrouter=mock_llm, mode="b2b")
    signal = await clf.classify(make_post(title="Shopify sync broken"))
    assert signal is not None
    assert signal.competitor_tags == ["shopify", "jira"]

