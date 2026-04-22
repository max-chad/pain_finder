import asyncio
from unittest.mock import AsyncMock

from classifier import Classifier, extract_comment_market_signals
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
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        evidence_spans=["orders fail", "customers complain"],
    )
    clf = Classifier(openrouter=mock_llm, mode="dual")
    result = await clf.classify(make_post(title="Shopify stock sync broken"))
    assert result is not None
    assert result.is_monetizable is True
    assert result.willingness_to_pay == 9
    assert result.analysis_mode == "b2b"
    assert result.post_type == "first_person_pain"
    assert result.first_handness == "first_hand"
    assert result.buyer_authority == "founder_owner"
    assert result.evidence_spans == ["orders fail", "customers complain"]


async def test_dual_mode_prefers_dspy_parser_before_openrouter_primary():
    dspy_parser = AsyncMock()
    dspy_parser.analyze_post.return_value = AnalysisResult(
        category="complaint",
        summary="Spreadsheet workflow is brittle",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="RevOps",
        competitor_tags=["hubspot"],
    )
    mock_llm = AsyncMock()
    clf = Classifier(openrouter=mock_llm, dspy_parser=dspy_parser, mode="dual")

    result = await clf.classify(make_post(title="I can't keep reconciling this manually"))

    assert result is not None
    assert result.summary == "Spreadsheet workflow is brittle"
    dspy_parser.analyze_post.assert_awaited_once()
    mock_llm.analyze_post.assert_not_called()


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


async def test_legacy_llm_backfills_unknown_authority_and_first_handness_from_post():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = None
    mock_llm.analyze_legacy_post.return_value = AnalysisResult(
        category="complaint",
        summary="QuickBooks keeps failing",
        severity="high",
    )
    clf = Classifier(openrouter=mock_llm, mode="dual")
    result = await clf.classify(make_post(title="As founder, QuickBooks keeps failing and I'm stuck"))
    assert result is not None
    assert result.analysis_mode == "legacy_llm"
    assert result.first_handness == "first_hand"
    assert result.buyer_authority == "founder_owner"
    assert result.evidence_spans


async def test_b2b_mode_returns_none_when_model_fails():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = None
    clf = Classifier(openrouter=mock_llm, mode="b2b")
    result = await clf.classify(make_post(title="I can't get this working"))
    assert result is None


async def test_legacy_mode_uses_keyword_fallback_without_llm():
    clf = Classifier(openrouter=None, mode="legacy")
    result = await clf.classify(
        make_post(title="As the founder, I can't figure this out and I'm stuck on it for days")
    )
    assert result is not None
    assert result.category == "complaint"
    assert result.analysis_mode == "legacy"
    assert result.post_type == "first_person_pain"
    assert result.first_handness == "first_hand"
    assert result.buyer_authority == "founder_owner"
    assert result.evidence_spans


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


async def test_classify_batch_respects_max_concurrency():
    clf = Classifier(openrouter=None, mode="legacy", max_concurrency=2)
    posts = [make_post(title="I can't do this", post_id=f"p{i}") for i in range(6)]

    in_flight = 0
    peak_in_flight = 0

    async def classify_stub(post):
        nonlocal in_flight, peak_in_flight
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return None

    clf.classify = classify_stub  # type: ignore[assignment]

    signals = await clf.classify_batch(posts)

    assert signals == []
    assert peak_in_flight <= 2


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


def test_extract_comment_market_signals_detects_consensus_workarounds_tools_and_shill_risk():
    post = make_post(
        title="Jira approvals are still painful",
        body="We keep exporting CSVs and stitching steps manually",
    )
    post.top_comments = [
        "Same here — we still hit this every week.",
        "Manual workaround here too: export CSV, clean it in Sheets, and re-upload.",
        "Try our tool at https://promo.example, book a demo and we will fix Jira for you.",
    ]

    signals = extract_comment_market_signals(post, competitor_tags=["jira"])

    assert signals["comment_same_here_count"] == 1
    assert signals["comment_consensus_count"] >= 2
    assert signals["comment_workaround_count"] == 1
    assert signals["comment_tool_mentions"] == ["jira"]
    assert signals["comment_shill_risk"] > 0
