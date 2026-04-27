from unittest.mock import AsyncMock

import pytest

from report_builder import ResearchReportBuilder


def test_renderable_clusters_use_all_promoted_post_ids_not_only_representatives(tmp_path):
    builder = ResearchReportBuilder(db=AsyncMock(), reports_dir=str(tmp_path))
    promoted_rows_by_id = {
        "p1": {
            "post_id": "p1",
            "title": "Representative approval pain",
            "source": "reddit",
            "url": "https://reddit.com/p1",
            "summary": "Representative row has exact evidence.",
            "current_workaround": "manual CSV reconciliation",
            "incumbent_failure": "CRM sync misses approvals",
            "opportunity_score": 80.0,
            "confidence": 0.8,
            "buyer_authority": "head_of_ops",
            "verified_evidence_json": '[{"quote":"CSV reconciliation blocks approvals","match_type":"exact"}]',
        },
        "p2": {
            "post_id": "p2",
            "title": "Promoted row omitted from representatives",
            "source": "hn",
            "url": "https://news.ycombinator.com/item?id=p2",
            "summary": "This row must still drive cluster evidence.",
            "current_workaround": "manual invoice queue audit",
            "incumbent_failure": "ERP approvals are delayed",
            "opportunity_score": 60.0,
            "confidence": 0.7,
            "buyer_authority": "manager",
            "verified_evidence_json": '[{"quote":"invoice queue audits are still manual","match_type":"exact"}]',
        },
    }

    renderable = builder._renderable_clusters(
        [
            {
                "label": "Approval handoffs",
                "avg_opportunity_score": 99.0,
                "post_ids": ["p1", "p2", "weak"],
                "representative_examples": [
                    {"post_id": "p1", "verified_quotes": ["CSV reconciliation blocks approvals"]},
                    {"post_id": "weak", "verified_quotes": ["unsupported weak quote"]},
                ],
            }
        ],
        promoted_rows_by_id=promoted_rows_by_id,
    )

    assert [example["post_id"] for example in renderable[0]["eligible_examples"]] == ["p1", "p2"]
    assert renderable[0]["avg_opportunity_score"] == pytest.approx(70.0)
    assert renderable[0]["opportunity_score"] == pytest.approx(70.0)
    assert set(renderable[0]["next_research_action"]["evidence_post_ids"]) == {"p1", "p2"}


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
            "source_families": ["reddit", "hn"],
            "source_family_counts": {"reddit": 1, "hn": 1},
            "source_diversity_score": 0.5,
            "triangulation_score": 0.62,
            "cluster_quality_score": 0.81,
            "score_components": {
                "factors": {"stability": 0.91, "source_diversity": 0.5, "triangulation": 0.62},
                "cluster_quality_score": 0.81,
                "diagnostic_only": True,
                "promotion_eligible_impact": "none",
            },
            "next_research_action": {
                "interview_questions": ["Ask only the unsupported weak row"],
                "icp_hypothesis": "Unsupported weak persona",
                "mvp_wedge": "Unsupported weak automation",
                "messaging_angle": "Unsupported weak messaging",
                "why_now": "Unsupported weak why now",
                "risks_unknowns": ["Unsupported weak risk"],
                "manual_validation_step": "Unsupported weak validation",
                "evidence_post_ids": ["w1"],
            },
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
                    "current_workaround": "stale representative workaround should not render",
                    "incumbent_failure": "stale representative incumbent failure should not render",
                    "user_context": {"persona": "Stale persona", "workflow": "stale workflow"},
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
    assert "Cluster quality 0.81" in html
    assert "Source diversity 0.50" in html
    assert "Triangulation 0.62" in html
    assert "Score breakdown" in html
    assert "source_diversity=0.50" in html
    assert "triangulation=0.62" in html
    assert "Next research action" in html
    assert "Interview questions" in html
    assert "ICP hypothesis" in html
    assert "MVP wedge" in html
    assert "Manual validation" in html
    assert "manual CSV reconciliation before approval" in html
    assert "stale representative" not in html
    assert "Stale persona" not in html
    assert "Unsupported weak" not in html


async def test_research_report_renders_competitor_failure_radar_from_verified_rows_and_clusters(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "radar-1",
            "title": "HubSpot renewal pricing and lock-in hurt RevOps",
            "summary": "RevOps wants to switch after the renewal doubled.",
            "pain_level": 9,
            "willingness_to_pay": 9,
            "opportunity_score": 93.0,
            "niche_category": "RevOps",
            "source": "reddit",
            "subreddit": "salesops",
            "url": "https://reddit.com/r/salesops/comments/radar-1",
            "pain_type": "pricing_pain",
            "opportunity_bucket": "current_opportunity",
            "first_handness": "first_hand",
            "buyer_authority": "head_of_ops",
            "buyer_authority_score": 0.94,
            "confidence": 0.91,
            "current_workaround": "exporting CSVs for offline review",
            "incumbent_failure": "HubSpot renewal pricing doubled and contract lock-in blocks switching",
            "competitor_tags": '["hubspot"]',
            "verified_evidence_json": '[{"quote":"HubSpot renewal doubled and we cannot export workflows","match_type":"exact","url":"https://reddit.com/r/salesops/comments/radar-1"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "score_components_json": '{"promotion_eligible": true}',
        },
        {
            "post_id": "radar-2",
            "title": "HubSpot missing approvals keeps stalling",
            "summary": "Ops teams route approvals through Airtable because HubSpot support keeps stalling.",
            "pain_level": 8,
            "willingness_to_pay": 8,
            "opportunity_score": 86.0,
            "niche_category": "RevOps",
            "source": "hn",
            "subreddit": "hn",
            "url": "https://news.ycombinator.com/item?id=radar-2",
            "pain_type": "missing_feature",
            "opportunity_bucket": "current_opportunity",
            "first_handness": "first_hand",
            "buyer_authority": "manager",
            "buyer_authority_score": 0.82,
            "confidence": 0.87,
            "current_workaround": "Airtable approval workaround",
            "incumbent_failure": "HubSpot is missing approval routing and support keeps stalling",
            "competitor_tags": '["hubspot", "airtable"]',
            "comment_tool_mentions_json": '["airtable"]',
            "verified_evidence_json": '[{"quote":"HubSpot is missing approval routing so we use Airtable","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "score_components_json": '{"promotion_eligible": true}',
        },
        {
            "post_id": "radar-weak",
            "title": "Unsupported high-score HubSpot complaint",
            "summary": "No exact evidence backs this competitor complaint.",
            "pain_level": 10,
            "willingness_to_pay": 10,
            "opportunity_score": 99.0,
            "niche_category": "RevOps",
            "source": "reddit",
            "subreddit": "salesops",
            "opportunity_bucket": "current_opportunity",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "buyer_authority_score": 1.0,
            "current_workaround": "unknown",
            "incumbent_failure": "HubSpot support is allegedly awful",
            "competitor_tags": '["hubspot"]',
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0.0,
            "score_components_json": '{"promotion_eligible": true}',
        },
    ]
    db.get_latest_canonical_clusters.return_value = [
        {
            "canonical_key": "crm-billing-sync-failures",
            "label": "CRM billing and sync failures",
            "summary": "Verified HubSpot complaints recur around renewal pricing, missing approvals, and switching friction.",
            "avg_opportunity_score": 91.0,
            "post_ids": ["radar-1", "radar-2", "radar-weak"],
            "incumbents": ["hubspot", "airtable"],
            "representative_examples": [
                {"post_id": "radar-1", "verified_quotes": ["HubSpot renewal doubled and we cannot export workflows"]},
                {"post_id": "radar-2", "verified_quotes": ["HubSpot is missing approval routing so we use Airtable"]},
                {"post_id": "radar-weak", "verified_quotes": ["unsupported weak quote"]},
            ],
        }
    ]
    db.list_source_coverage_runs.return_value = []

    builder = ResearchReportBuilder(db=db, reports_dir=str(tmp_path))
    result = await builder.build_report(hours=24)

    assert result.top_opportunity_count == 2
    assert result.weak_signal_count == 1
    html = result.html_path and open(result.html_path, encoding="utf-8").read()
    assert "Competitor failures" in html
    assert "hubspot" in html
    assert "2 verified mentions" in html
    assert "Pricing pain (1)" in html
    assert "Missing feature (1)" in html
    assert "Switching/lock-in/churn (1)" in html
    assert "Reliability/support failure (1)" in html
    assert "Workaround (2)" in html
    assert "Alternative-tool mentions (1)" in html
    assert "HubSpot renewal doubled and we cannot export workflows" in html
    assert "HubSpot is missing approval routing so we use Airtable" in html
    assert 'href="#cluster-crm-billing-and-sync-failures"' in html
    assert "Cluster: CRM billing and sync failures" in html
    assert "unsupported weak quote" not in html
    assert "Unsupported high-score HubSpot complaint" in html


async def test_research_report_cluster_cards_show_buyer_wtp_intelligence_for_verified_examples_only(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "buyer-ops",
            "title": "Ops team pays to patch invoice approvals",
            "summary": "Head of ops has budget for invoice approval fixes.",
            "pain_level": 9,
            "willingness_to_pay": 9,
            "opportunity_score": 91.0,
            "niche_category": "FinOps",
            "source": "reddit",
            "subreddit": "financeops",
            "url": "https://example.com/buyer-ops",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "head_of_ops",
            "buyer_authority_score": 0.94,
            "current_workaround": "paid Zapier subscription plus contractor spreadsheet cleanup",
            "incumbent_failure": "ERP approval sync misses invoice status changes",
            "verified_evidence_json": '[{"quote":"I own ops budget and would pay to stop invoice approvals breaking","source_type":"body","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.91,
            "uncertainty_reason": "budget is explicit but seat count is unknown",
            "score_components_json": '{"promotion_eligible": true}',
            "user_context_json": '{"role":"head_of_ops","persona":"Head of Ops"}',
        },
        {
            "post_id": "buyer-founder",
            "title": "Founder pays for billing reconciliation workaround",
            "summary": "Founder runs a paid Airtable workaround for billing reconciliation.",
            "pain_level": 8,
            "willingness_to_pay": 8,
            "opportunity_score": 87.0,
            "niche_category": "FinOps",
            "source": "hn",
            "subreddit": "hn",
            "url": "https://news.ycombinator.com/item?id=buyer-founder",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "buyer_authority_score": 1.0,
            "current_workaround": "monthly Airtable license workaround for reconciliation",
            "incumbent_failure": "Billing export drops paid invoices",
            "verified_evidence_json": '[{"quote":"as founder I pay for Airtable because billing reconciliation still breaks","source_type":"body","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.86,
            "score_components_json": '{"promotion_eligible": true}',
            "user_context_json": '{"role":"founder_owner","persona":"Founder"}',
        },
        {
            "post_id": "buyer-weak",
            "title": "Unsupported noisy buyer claim",
            "summary": "Looks like budget, but no exact evidence backs it.",
            "pain_level": 10,
            "willingness_to_pay": 10,
            "opportunity_score": 99.0,
            "niche_category": "FinOps",
            "source": "reddit",
            "subreddit": "financeops",
            "url": "https://example.com/buyer-weak",
            "opportunity_bucket": "current_opportunity",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "buyer_authority_score": 1.0,
            "current_workaround": "unsupported paid Zapier claim",
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0.0,
            "confidence": 0.2,
            "score_components_json": '{"promotion_eligible": true}',
        },
    ]
    db.get_latest_canonical_clusters.return_value = [
        {
            "canonical_key": "invoice-approval-budget",
            "label": "Invoice approval budget pain",
            "summary": "Verified buyers are paying for workarounds around invoice approval and billing reconciliation.",
            "avg_opportunity_score": 92.0,
            "post_ids": ["buyer-ops", "buyer-founder", "buyer-weak"],
            "representative_examples": [
                {
                    "post_id": "buyer-ops",
                    "verified_quotes": ["unsupported would pay paraphrase"],
                    "exact_verified_quotes": ["unsupported would pay paraphrase"],
                },
                {"post_id": "buyer-founder", "verified_quotes": ["as founder I pay for Airtable because billing reconciliation still breaks"]},
                {"post_id": "buyer-weak", "verified_quotes": ["unsupported buyer budget quote"]},
            ],
        }
    ]
    db.list_source_coverage_runs.return_value = []

    builder = ResearchReportBuilder(db=db, reports_dir=str(tmp_path))
    result = await builder.build_report(hours=24)

    html = result.html_path and open(result.html_path, encoding="utf-8").read()
    cluster_html = html[: html.index("Top opportunities")]
    assert "Buyer/WTP intelligence" in cluster_html
    assert "Buyer roles: head_of_ops (1) | founder_owner (1)" in cluster_html
    assert "Avg buyer authority 0.97" in cluster_html
    assert "Avg WTP 8.5/10" in cluster_html
    assert "WTP evidence" in cluster_html
    assert "I own ops budget and would pay to stop invoice approvals breaking" in cluster_html
    assert "Paid workaround evidence" in cluster_html
    assert "paid Zapier subscription plus contractor spreadsheet cleanup" in cluster_html
    assert "monthly Airtable license workaround for reconciliation" in cluster_html
    assert "Uncertainty" in cluster_html
    assert "budget is explicit but seat count is unknown" in cluster_html
    assert "unsupported would pay paraphrase" not in cluster_html
    assert "unsupported buyer budget quote" not in cluster_html
    assert "unsupported paid Zapier claim" not in cluster_html


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


async def test_research_report_renders_bounded_rejected_noise_examples_with_normalized_reasons(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "eligible",
            "title": "Verified invoice reconciliation pain",
            "summary": "Founder has exact evidence for weekly reconciliation breakage.",
            "pain_level": 8,
            "willingness_to_pay": 8,
            "opportunity_score": 82.0,
            "niche_category": "FinOps",
            "source": "reddit",
            "subreddit": "finance",
            "url": "https://example.com/eligible",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "verified_evidence_json": '[{"quote":"invoice reconciliation breaks payroll","source_type":"body","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.9,
            "score_components_json": '{"promotion_eligible": true, "evidence_rejection_reason": ""}',
        }
    ]
    db.get_latest_canonical_clusters.return_value = []
    db.list_source_coverage_runs.return_value = []
    rejected_rows = [
        ("generic", "Generic CRM automation question", "generic_question"),
        ("consumer", "Consumer app rant", "consumer_rant"),
        ("low-context", "Too little context to evaluate", "low_context"),
        ("no-evidence", "High score but no exact quote", "no_verified_exact_quote"),
        ("solved", "Solved issue after switching tools", "solved_issue"),
        ("shill", "Looks like vendor promotion", "shill_risk"),
        ("duplicate", "Duplicate of existing invoice thread", "duplicate"),
        *[(f"overflow-{index}", f"Overflow rejected item {index}", "no_verified_exact_quote") for index in range(6)],
    ]
    db.get_recent_rejected_noise_candidates.return_value = [
        {
            "post_id": post_id,
            "title": title,
            "summary": title,
            "pain_level": 4,
            "willingness_to_pay": 0,
            "opportunity_score": 70 - index,
            "niche_category": "Rejected",
            "source": "reddit",
            "subreddit": "finance",
            "url": f"https://example.com/{post_id}",
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0,
            "confidence": 0.2,
            "score_components_json": f'{{"promotion_eligible": false, "evidence_rejection_reason": "{reason}"}}',
        }
        for index, (post_id, title, reason) in enumerate(rejected_rows)
    ]

    builder = ResearchReportBuilder(db=db, reports_dir=str(tmp_path))
    result = await builder.build_report(hours=24)

    db.get_recent_rejected_noise_candidates.assert_awaited_once_with(hours=24, limit=50)
    html = result.html_path and open(result.html_path, encoding="utf-8").read()
    assert result.top_opportunity_count == 1
    assert result.weak_signal_count == 0
    assert result.rejected_noise_count == 12
    assert "Rejected/noise examples" in html
    for label in [
        "generic question",
        "consumer rant",
        "low context",
        "no evidence",
        "solved issue",
        "shill risk",
        "duplicate",
    ]:
        assert f"Reason: {label}" in html
    assert "Duplicate of existing invoice thread" in html
    assert "Overflow rejected item 5" not in html
    assert html.index("Verified invoice reconciliation pain") < html.index("Rejected/noise examples")
