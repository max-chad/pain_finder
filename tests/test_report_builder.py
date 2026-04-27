from unittest.mock import AsyncMock

from report_builder import ResearchReportBuilder


async def test_research_report_renders_required_static_sections_from_fixture_data(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "p1",
            "title": "RevOps CSV handoff <script>alert(1)</script>",
            "summary": "Ops owners reconcile onboarding CSVs before approvals.",
            "pain_level": 9,
            "willingness_to_pay": 9,
            "opportunity_score": 92.4,
            "niche_category": "RevOps",
            "category": "complaint",
            "source": "reddit",
            "subreddit": "salesops",
            "url": "https://reddit.com/r/salesops/comments/p1",
            "pain_type": "workflow_breakage",
            "expression_type": "first_hand_complaint",
            "opportunity_type": "current_opportunity",
            "opportunity_bucket": "current_opportunity",
            "first_handness": "first_hand",
            "buyer_authority": "head_of_ops",
            "buyer_authority_score": 0.94,
            "confidence": 0.88,
            "intensity_score": 0.9,
            "urgency": "high",
            "current_workaround": "manual CSV reconciliation before approval",
            "incumbent_failure": "HubSpot sync misses approval status changes",
            "competitor_tags": '["hubspot", "salesforce"]',
            "verified_evidence_json": '[{"quote":"we still reconcile onboarding CSVs by hand before approvals","match_type":"exact","url":"https://reddit.com/r/salesops/comments/p1"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "score_components_json": '{"factors":{"intensity":0.18,"frequency":0.14,"wtp":0.14},"penalties":{"noise":0.0}}',
            "pain_mentions_per_1000_posts": 12.5,
            "pain_mentions_per_1000_comments": 3.2,
            "unique_authors_count": 3,
            "unique_threads_count": 2,
        },
        {
            "post_id": "p2",
            "title": "Customers ask for invoice approval API",
            "summary": "Teams want approval API hooks before invoices are paid.",
            "pain_level": 8,
            "willingness_to_pay": 8,
            "opportunity_score": 84.0,
            "niche_category": "FinOps",
            "category": "feature_request",
            "source": "hn",
            "subreddit": "hn",
            "url": "javascript:alert(1)",
            "pain_type": "missing_feature",
            "opportunity_type": "feature_request",
            "opportunity_bucket": "evergreen_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "buyer_authority_score": 1.0,
            "confidence": 0.81,
            "intensity_score": 0.8,
            "urgency": "medium",
            "current_workaround": "Zapier plus spreadsheet review",
            "incumbent_failure": "Stripe lacks the approval workflow they need",
            "competitor_tags": '["stripe"]',
            "verified_evidence_json": '[{"quote":"we need an approval API before vendor invoices are paid","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "score_components_json": '{"factors":{"intensity":0.16,"wtp":0.12},"penalties":{"noise":0.0}}',
        },
        {
            "post_id": "w1",
            "title": "Generic CRM automation question",
            "summary": "Could be useful, but no exact evidence yet.",
            "pain_level": 10,
            "willingness_to_pay": 10,
            "opportunity_score": 99.0,
            "niche_category": "RevOps",
            "category": "question",
            "source": "reddit",
            "subreddit": "sales",
            "url": "https://reddit.com/r/sales/comments/w1",
            "pain_type": "generic_question",
            "opportunity_bucket": "current_opportunity",
            "first_handness": "unknown",
            "buyer_authority": "unknown",
            "confidence": 0.44,
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0.0,
            "evidence_rejection_reason": "no_verified_exact_quote",
            "score_components_json": '{"promotion_eligible": true}',
        },
    ]
    db.get_latest_canonical_clusters.return_value = [
        {
            "canonical_key": "revops-csv-approvals",
            "label": "RevOps CSV approval handoffs",
            "summary": "RevOps teams lose time reconciling onboarding CSV handoffs before approval workflows.",
            "estimated_monetization_signal": "high",
            "avg_opportunity_score": 91.3,
            "cluster_stability_score": 0.91,
            "verified_quote_count": 2,
            "independent_source_count": 2,
            "unique_author_count": 3,
            "incumbents": ["hubspot", "salesforce"],
            "pain_mentions_per_1000_posts": 12.5,
            "pain_mentions_per_1000_comments": 3.2,
            "post_ids": ["p1", "w1"],
            "representative_examples": [
                {
                    "post_id": "p1",
                    "title": "RevOps CSV handoff",
                    "source": "reddit",
                    "url": "https://reddit.com/r/salesops/comments/p1",
                    "verified_quotes": ["we still reconcile onboarding CSVs by hand before approvals"],
                    "current_workaround": "manual CSV reconciliation before approval",
                    "incumbent_failure": "HubSpot sync misses approval status changes",
                    "user_context": {"persona": "RevOps manager", "workflow": "customer onboarding approvals"},
                    "pain_level": 9,
                    "willingness_to_pay": 9,
                    "confidence": 0.88,
                },
                {
                    "post_id": "w1",
                    "title": "Generic CRM automation question",
                    "verified_quotes": ["unsupported weak quote should not render"],
                },
            ],
        }
    ]
    db.list_source_coverage_runs.return_value = [
        {
            "source": "reddit",
            "scope": "salesops",
            "fetched_posts": 120,
            "fetched_comments": 640,
            "skipped_deleted": 2,
            "skipped_duplicates": 3,
            "failed_requests": 1,
            "source_method_used": "public_json",
            "duration_ms": 250,
        }
    ]

    builder = ResearchReportBuilder(db=db, reports_dir=str(tmp_path))
    result = await builder.build_report(hours=48)

    db.get_recent_pain_points.assert_awaited_once_with(hours=48, limit=1000)
    db.get_latest_canonical_clusters.assert_awaited_once_with(limit=50, post_ids=["p1", "p2"])
    db.list_source_coverage_runs.assert_awaited_once_with(limit=10)
    assert result.html_path is not None
    assert result.cluster_count == 1
    assert result.top_opportunity_count == 2
    assert result.weak_signal_count == 1

    html = result.html_path and open(result.html_path, encoding="utf-8").read()
    assert "Pain Finder Research Report" in html
    assert html.index("Trending pains") < html.index("Top opportunities")
    for section in [
        "Top opportunities",
        "Trending pains",
        "Competitor failures",
        "Unmet feature requests",
        "High-WTP signals",
        "Weak signals to watch",
        "Rejected/noise examples",
        "Coverage and confidence report",
    ]:
        assert section in html
    for filter_label in [
        "Source",
        "Subreddit/source",
        "Time range",
        "Pain type",
        "Industry/persona",
        "Intensity",
        "WTP",
        "Urgency",
        "Confidence",
        "First-hand only",
        "Buyer authority",
        "Competitor/tool",
        "Opportunity bucket",
        "Evidence quality",
    ]:
        assert filter_label in html
    assert 'data-source="reddit"' in html
    assert 'data-pain-type="workflow_breakage"' in html
    assert "RevOps CSV handoff &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert 'href="javascript:alert(1)"' not in html
    assert 'href="https://reddit.com/r/salesops/comments/p1"' in html
    assert "revops-csv-approvals" not in html
    assert "RevOps CSV approval handoffs" in html
    assert "we still reconcile onboarding CSVs by hand before approvals" in html
    assert "unsupported weak quote should not render" not in html
    assert "HubSpot sync misses approval status changes" in html
    assert "approval API hooks before invoices are paid" in html
    assert "Generic CRM automation question" in html
    assert "Evidence rejection: no_verified_exact_quote" in html
    assert "Fetched posts: 120" in html
    assert "Source method: public_json" in html


async def test_research_report_does_not_fetch_or_render_clusters_for_all_weak_rows(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "weak-high-score",
            "title": "Unsupported high score automation idea",
            "summary": "Looks attractive but has no exact evidence.",
            "pain_level": 10,
            "willingness_to_pay": 10,
            "opportunity_score": 99.0,
            "source": "reddit",
            "subreddit": "sales",
            "url": "https://reddit.com/weak",
            "pain_type": "generic_question",
            "opportunity_bucket": "current_opportunity",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "confidence": 0.9,
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0.0,
            "evidence_rejection_reason": "no_verified_exact_quote",
            "score_components_json": '{"promotion_eligible": true}',
        }
    ]
    db.get_latest_canonical_clusters.return_value = [
        {
            "label": "Leaky weak cluster",
            "summary": "This should not be rendered when all rows are weak.",
            "representative_examples": [{"post_id": "weak-high-score", "verified_quotes": ["not exact"]}],
        }
    ]
    db.list_source_coverage_runs.return_value = []

    builder = ResearchReportBuilder(db=db, reports_dir=str(tmp_path))
    result = await builder.build_report(hours=24)

    db.get_latest_canonical_clusters.assert_not_awaited()
    html = result.html_path and open(result.html_path, encoding="utf-8").read()
    assert result.cluster_count == 0
    assert result.top_opportunity_count == 0
    assert result.weak_signal_count == 1
    assert "Leaky weak cluster" not in html
    assert "Unsupported high score automation idea" in html
    assert "Evidence rejection: no_verified_exact_quote" in html
    assert "Top opportunities" in html
    assert "No verified opportunities in this window." in html
