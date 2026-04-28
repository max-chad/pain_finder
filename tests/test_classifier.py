import asyncio
from unittest.mock import AsyncMock

from classifier import Classifier, extract_comment_market_signals
from openrouter import AnalysisResult, PainDetectionResult
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
    mock_llm.analyze_pain_detection.return_value = PainDetectionResult(
        is_pain=False,
        is_noise=True,
        post_type="advice_thread",
        operational_consequence="none",
        confidence=0.91,
    )
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
        pain_type="integration",
        expression_type="first_person_complaint",
        user_context="Shopify merchant operations",
        intensity=9,
        frequency=8,
        urgency=9,
        current_workaround="Manual order audit",
        incumbent_failure="Shopify integration drops orders",
        evidence_spans=["orders fail", "customers complain"],
        evidence_quality="multi_quote",
        opportunity_type="current_opportunity",
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
    assert result.pain_type == "integration"
    assert result.expression_type == "first_person_complaint"
    assert result.user_context == "Shopify merchant operations"
    assert result.intensity == 9
    assert result.frequency == 8
    assert result.urgency == 9
    assert result.current_workaround == "Manual order audit"
    assert result.incumbent_failure == "Shopify integration drops orders"
    assert result.opportunity_type == "current_opportunity"
    mock_llm.analyze_pain_detection.assert_not_awaited()


async def test_staged_pain_detection_can_skip_noise_before_primary():
    mock_llm = AsyncMock()
    mock_llm.analyze_pain_detection.return_value = PainDetectionResult(
        is_pain=False,
        is_noise=True,
        post_type="advice_thread",
        operational_consequence="none",
        confidence=0.88,
    )
    clf = Classifier(openrouter=mock_llm, mode="dual", staged_pain_detection_enabled=True)

    result = await clf.classify(make_post(title="Spreadsheet template giveaway", body="No workflow pain here, just sharing."))

    assert result is None
    mock_llm.analyze_pain_detection.assert_awaited_once()
    mock_llm.analyze_post.assert_not_called()
    mock_llm.analyze_legacy_post.assert_not_called()


async def test_staged_pain_detection_allows_pain_to_continue_and_attaches_gate_metadata():
    mock_llm = AsyncMock()
    mock_llm.analyze_pain_detection.return_value = PainDetectionResult(
        is_pain=True,
        is_noise=False,
        post_type="solution_request",
        operational_consequence="reconciliation",
        confidence=0.84,
    )
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint",
        summary="Payout reconciliation burns time",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="Finance Ops",
        post_type="solution_request",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        pain_type="billing_payout",
        expression_type="solution_request",
        user_context="Founder reconciling payouts",
        intensity=8,
        frequency=7,
        urgency=7,
        current_workaround="Export CSV and reconcile manually",
        incumbent_failure="Stripe and QuickBooks do not match payout records",
        evidence_spans=["Export CSV and reconcile manually"],
        evidence_quality="exact_quote",
        opportunity_type="billing_ops",
        confidence=0.8,
    )
    clf = Classifier(openrouter=mock_llm, mode="dual", staged_pain_detection_enabled=True)
    post = make_post(
        title="How do you handle payout reconciliation?",
        body="Export CSV and reconcile manually every week between Stripe and QuickBooks.",
    )

    result = await clf.classify(post)

    assert result is not None
    assert result.analysis_payload["pain_detection"]["schema_version"] == "pain_detection_v1"
    assert result.analysis_payload["pain_detection"]["operational_consequence"] == "reconciliation"
    assert result.analysis_payload["primary"]["summary"] == "Payout reconciliation burns time"
    mock_llm.analyze_pain_detection.assert_awaited_once()
    mock_llm.analyze_post.assert_awaited_once()


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
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="head_of_ops",
        pain_type="workflow",
        expression_type="first_person_complaint",
        user_context="RevOps team reconciling spreadsheets",
        intensity=8,
        frequency=8,
        urgency=7,
        current_workaround="Manual spreadsheet reconciliation",
        incumbent_failure="HubSpot workflow sync is brittle",
        evidence_spans=["can't keep reconciling this manually"],
        evidence_quality="exact_quote",
        opportunity_type="current_opportunity",
        confidence=0.82,
    )
    mock_llm = AsyncMock()
    clf = Classifier(openrouter=mock_llm, dspy_parser=dspy_parser, mode="dual")

    result = await clf.classify(make_post(title="I can't keep reconciling this manually"))

    assert result is not None
    assert result.summary == "Spreadsheet workflow is brittle"
    assert result.analysis_mode == "dspy_b2b"
    assert result.pain_type == "workflow"
    assert result.expression_type == "first_person_complaint"
    assert result.user_context == "RevOps team reconciling spreadsheets"
    assert result.opportunity_type == "current_opportunity"
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
    mock_llm.analyze_legacy_post.assert_awaited_once()
    assert mock_llm.analyze_legacy_post.await_args.kwargs["fallback_reason"] == "primary_unavailable"


async def test_dual_mode_falls_back_with_dspy_schema_failure_reason():
    dspy_parser = AsyncMock()
    dspy_parser.analyze_post.return_value = None
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = None
    mock_llm.analyze_legacy_post.return_value = AnalysisResult(
        category="complaint",
        summary="Need reliable sync",
        severity="high",
    )
    clf = Classifier(openrouter=mock_llm, dspy_parser=dspy_parser, mode="dual")

    result = await clf.classify(make_post(title="I can't keep QuickBooks sync working"))

    assert result is not None
    assert result.analysis_mode == "legacy_llm"
    mock_llm.analyze_legacy_post.assert_awaited_once()
    assert mock_llm.analyze_legacy_post.await_args.kwargs["fallback_reason"] == "dspy_empty_primary_unavailable"


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


def test_prescreen_posts_filters_low_signal_and_caps_candidates():
    clf = Classifier(
        openrouter=None,
        mode="legacy",
        screen_min_rule_score=2,
        screen_max_llm_candidates_per_run=2,
    )
    posts = [
        make_post(title="Cool launch announcement", body="Just sharing progress", post_id="drop"),
        make_post(title="Need better approval workflow", body="Manual process every week", post_id="keep1"),
        make_post(title="Spreadsheet workaround is painful", body="We export CSVs daily", post_id="keep2"),
        make_post(title="Wish there was a Jira sync", body="Manual handoff between teams", post_id="keep3"),
    ]

    shortlisted, stats = clf.prescreen_posts(posts)

    assert {post.post_id for post in shortlisted} == {"keep1", "keep2"}
    assert stats["screen_rule_dropped_count"] == 1
    assert stats["screen_kept_count"] == 3
    assert stats["screen_capped_count"] == 1
    assert stats["screen_high_recall_candidate_count"] >= 3


def test_prescreen_keeps_hidden_operational_pain_without_complaint_words():
    clf = Classifier(openrouter=None, mode="legacy", screen_min_rule_score=1)
    post = make_post(
        title="How are you handling Stripe payout reconciliation?",
        body="We export CSVs every week, copy paste invoices into QuickBooks, and need a sane way to sync this.",
        post_id="ops-hidden",
    )

    assert clf.keyword_score(post) == 0
    assert clf.operational_consequence_score(post) >= 3
    shortlisted, stats = clf.prescreen_posts([post])

    assert [item.post_id for item in shortlisted] == ["ops-hidden"]
    assert stats["screen_high_recall_candidate_count"] == 1


async def test_semantic_candidate_retrieval_can_rescue_below_rule_threshold():
    class FakeEmbedder:
        async def embed_many(self, texts):
            return [[1.0, 0.0] for _ in texts]

        async def embed(self, text):
            if "expense approval routing" in text.lower():
                return [1.0, 0.0]
            return [0.0, 1.0]

    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="wish",
        summary="Expense approvals need automation",
        severity="medium",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=7,
        niche_category="Finance Ops",
        post_type="buying_question",
        first_handness="first_hand",
        buyer_authority="team_lead",
        evidence_spans=["expense approval routing"],
        confidence=0.74,
    )
    clf = Classifier(
        openrouter=mock_llm,
        mode="b2b",
        screen_min_rule_score=10,
        semantic_candidate_queries=["expense approval routing workflow pain"],
    )
    rescued = make_post(
        title="Expense approval routing",
        body="Expense approval routing takes days for our finance team.",
        post_id="semantic-rescue",
    )
    unrelated = make_post(title="Team offsite photos", body="Nice week", post_id="drop")

    selected, stats = await clf.select_candidates(
        [unrelated, rescued],
        semantic_embedder=FakeEmbedder(),
        semantic_max_candidates=1,
        semantic_min_similarity=0.9,
    )
    signal = await clf.classify(rescued)

    assert [post.post_id for post in selected] == ["semantic-rescue"]
    assert stats["screen_semantic_rescued_count"] == 1
    assert stats["screen_rule_dropped_count"] == 1
    assert signal is not None
    mock_llm.analyze_post.assert_awaited_once()


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


async def test_classifier_verifies_model_evidence_against_post_and_comments():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint",
        summary="Shopify sync creates daily manual work",
        severity="high",
        is_monetizable=True,
        pain_level=9,
        willingness_to_pay=9,
        niche_category="E-commerce",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        evidence_spans=[
            "stock sync lags",
            "Manual workaround is an export CSV",
            "invented quote that is not in the source",
        ],
        confidence=0.84,
    )
    post = make_post(
        title="Shopify stock sync broken",
        body="We lose sales when stock sync lags every day.",
        post_id="p-evidence",
    )
    post.top_comments = ["Same here. Manual workaround is an export CSV."]

    clf = Classifier(openrouter=mock_llm, mode="b2b")
    signal = await clf.classify(post)

    assert signal is not None
    assert [item.match_type for item in signal.verified_evidence] == ["exact", "exact", "none"]
    assert signal.verified_evidence[1].source_type == "comment"
    assert signal.evidence_quality == "multi_quote"
    assert signal.evidence_match_rate == 0.667
    assert signal.confidence == 0.84
    assert signal.needs_human_review is False


async def test_classifier_keeps_fuzzy_only_multi_evidence_weak():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint",
        summary="Manual approvals still block deals",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="RevOps",
        evidence_spans=["manual approvals still block deals", "revops exports csv nightly"],
        confidence=0.7,
    )
    post = make_post(
        title="Manual approvals still block deals",
        body="RevOps exports CSV nightly to keep customers moving.",
        post_id="p-fuzzy",
    )

    clf = Classifier(openrouter=mock_llm, mode="b2b")
    signal = await clf.classify(post)

    assert signal is not None
    assert [item.match_type for item in signal.verified_evidence] == ["fuzzy", "fuzzy"]
    assert signal.evidence_quality == "weak_quote"
    assert signal.evidence_match_rate == 1.0


async def test_classifier_marks_unverified_evidence_for_human_review():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint",
        summary="Claims unsupported pain",
        severity="high",
        is_monetizable=True,
        pain_level=9,
        willingness_to_pay=9,
        niche_category="DevOps",
        evidence_spans=["invented quote that is not in the source"],
        confidence=0.91,
    )

    clf = Classifier(openrouter=mock_llm, mode="b2b")
    signal = await clf.classify(make_post(title="Deployment tooling is broken", body="Our release workflow is painfully slow."))

    assert signal is not None
    assert signal.evidence_quality == "no_quote"
    assert signal.evidence_match_rate == 0.0
    assert signal.needs_human_review is True
    assert "No verified evidence" in signal.uncertainty_reason


async def test_classifier_does_not_synthesize_model_evidence_when_analyzer_returns_none():
    mock_llm = AsyncMock()
    mock_llm.analyze_post.return_value = AnalysisResult(
        category="complaint",
        summary="Deployment workflow is slow",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="DevOps",
        evidence_spans=[],
        confidence=0.72,
    )

    clf = Classifier(openrouter=mock_llm, mode="b2b")
    signal = await clf.classify(make_post(title="Deployment tooling is broken", body="Our release workflow is painfully slow."))

    assert signal is not None
    assert signal.evidence_spans == []
    assert signal.verified_evidence == []
    assert signal.evidence_quality == "no_quote"
    assert signal.evidence_match_rate == 0.0
    assert signal.needs_human_review is True
    assert "No evidence spans" in signal.uncertainty_reason


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
