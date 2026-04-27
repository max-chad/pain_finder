import zipfile
from unittest.mock import AsyncMock

from digest_delivery import DailyDigestDocumentService


async def test_daily_digest_document_service_writes_grouped_docx(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "p1",
            "title": "Need better onboarding handoff",
            "summary": "Sales teams still stitch data together manually.",
            "pain_level": 8,
            "willingness_to_pay": 9,
            "niche_category": "RevOps",
            "competitor_tags": '["hubspot"]',
            "source": "reddit",
            "url": "https://reddit.com/p1",
            "subreddit": "sales",
            "deep_dive_summary": "CSV handoffs between teams keep breaking.",
            "verified_evidence_json": '[{"quote":"Sales teams still stitch data manually","source_type":"body","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.82,
            "needs_human_review": 0,
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
        },
        {
            "post_id": "p2",
            "title": "Forecasting still lives in spreadsheets",
            "summary": "Finance ops cannot trust the weekly rollup.",
            "pain_level": 7,
            "willingness_to_pay": 8,
            "niche_category": "FinOps",
            "competitor_tags": '["excel"]',
            "source": "reviews",
            "url": "https://example.com/p2",
            "subreddit": "finance",
            "deep_dive_summary": "Teams export data three times before review.",
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0,
            "confidence": 0,
            "needs_human_review": 0,
            "opportunity_bucket": "evergreen_pain",
        },
        {
            "post_id": "p3",
            "title": "Pipeline attribution is still fuzzy",
            "summary": "Marketing ops teams cannot connect spend to revenue cleanly.",
            "pain_level": 8,
            "willingness_to_pay": 8,
            "niche_category": "RevOps",
            "competitor_tags": '["salesforce", "hubspot"]',
            "source": "hn",
            "url": "https://news.ycombinator.com/item?id=3",
            "subreddit": "marketing",
            "deep_dive_summary": "Attribution breaks across CRM sync boundaries.",
            "opportunity_bucket": "current_opportunity",
        },
    ]

    db.get_latest_canonical_clusters.return_value = [
        {
            "canonical_key": "revops-handoff-breakage",
            "label": "RevOps handoff breakage",
            "summary": "Multiple ops teams still move onboarding data via CSV handoffs.",
            "fresh_post_count": 2,
            "evergreen_post_count": 0,
            "median_buyer_authority": 0.82,
            "incumbents": ["hubspot", "salesforce"],
            "avg_opportunity_score": 88.2,
            "latest_source_created_ts": 1713772800,
            "post_ids": ["p1", "p3"],
            "pain_mentions_per_1000_posts": 12.5,
            "pain_mentions_per_1000_comments": 2.5,
            "unique_authors_count": 2,
            "unique_threads_count": 2,
            "cluster_stability_score": 0.84,
            "verified_quote_count": 2,
            "independent_source_count": 2,
            "unique_author_count": 2,
            "representative_examples": [
                {
                    "post_id": "p1",
                    "title": "Need better onboarding handoff",
                    "verified_quotes": ["Sales teams still stitch data manually"],
                    "source": "reddit",
                    "url": "https://reddit.com/p1",
                }
            ],
            "normalized_frequency": {"pain_mentions_per_1000_posts": 12.5, "unique_authors_count": 2},
        }
    ]

    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))

    result = await service.build_document(hours=24, group_by="niche", min_wtp=8, max_items_per_group=5)

    assert result.total_items == 3
    assert result.group_count == 3
    assert result.docx_path is not None
    assert result.docx_path.endswith(".docx")

    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "Pain Finder Daily Digest" in xml
    assert "Canonical pain clusters" in xml
    assert "RevOps handoff breakage" in xml
    assert "Pain frequency 12.5/1k posts | 2.5/1k comments | Authors 2 | Threads 2" in xml
    assert "Cluster quality: Stability 0.84 | Verified quotes 2 | Sources 2 | Authors 2" in xml
    assert "Representative examples" in xml
    assert "Need better onboarding handoff" in xml
    assert "Sales teams still stitch data manually" in xml
    assert "Current opportunities" in xml
    assert "Needs Review / Weak signals" in xml
    assert "Evergreen pain index: 0" in xml
    assert "RevOps" in xml
    assert "FinOps" in xml
    assert "Need better onboarding handoff" in xml
    assert "Evidence: Sales teams still stitch data manually" in xml
    assert "Evidence quality: exact_quote | Match rate 1.00 | Confidence 0.82 | Human review no" in xml
    assert "Evidence rejection: no_verified_exact_quote" in xml
    assert "Pipeline attribution is still fuzzy" in xml
    assert "Forecasting still lives in spreadsheets" in xml


async def test_daily_digest_document_renders_rich_cluster_cards_as_primary_surface(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "p1",
            "title": "RevOps CSV handoff keeps breaking onboarding",
            "summary": "Ops owners manually reconcile onboarding data before approvals.",
            "pain_level": 9,
            "willingness_to_pay": 9,
            "opportunity_score": 91.3,
            "niche_category": "RevOps",
            "competitor_tags": '["hubspot", "salesforce"]',
            "source": "reddit",
            "url": "https://reddit.com/p1",
            "subreddit": "sales",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "head_of_ops",
            "buyer_authority_score": 0.94,
            "verified_evidence_json": '[{"quote":"we still reconcile onboarding CSVs by hand before approvals","source_type":"body","match_type":"exact","url":"https://reddit.com/p1"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.86,
            "score_components_json": '{"factors":{"intensity":0.18,"frequency":0.14,"wtp":0.14},"penalties":{"noise":0.0}}',
        }
    ]
    db.get_latest_canonical_clusters.return_value = [
        {
            "canonical_key": "revops-csv-approvals",
            "label": "RevOps CSV approval handoffs",
            "summary": "RevOps teams lose time reconciling onboarding CSV handoffs before approval workflows.",
            "estimated_monetization_signal": "high",
            "item_count": 4,
            "fresh_post_count": 3,
            "evergreen_post_count": 1,
            "avg_opportunity_score": 91.3,
            "aggregate_wtp": 35.0,
            "median_buyer_authority": 0.94,
            "incumbents": ["hubspot", "salesforce"],
            "cluster_stability_score": 0.91,
            "verified_quote_count": 4,
            "independent_source_count": 2,
            "unique_author_count": 3,
            "pain_mentions_per_1000_posts": 12.5,
            "pain_mentions_per_1000_comments": 3.2,
            "normalized_frequency": {"pain_mentions_per_1000_posts": 12.5, "unique_authors_count": 3},
            "representative_examples": [
                {
                    "post_id": "p1",
                    "title": "RevOps CSV handoff keeps breaking onboarding",
                    "summary": "Ops owners manually reconcile onboarding data before approvals.",
                    "source": "reddit",
                    "url": "https://reddit.com/p1",
                    "verified_quotes": ["we still reconcile onboarding CSVs by hand before approvals"],
                    "current_workaround": "manual CSV reconciliation before approval",
                    "incumbent_failure": "CRM sync misses approval status changes",
                    "user_context": {"persona": "RevOps manager", "workflow": "customer onboarding approvals"},
                    "pain_level": 9,
                    "willingness_to_pay": 9,
                    "intensity_score": 0.9,
                    "urgency": "high",
                    "buyer_authority": "head_of_ops",
                    "buyer_authority_score": 0.94,
                    "confidence": 0.86,
                    "score_components": {"factors": {"intensity": 0.18, "frequency": 0.14, "wtp": 0.14}, "penalties": {"noise": 0.0}},
                }
            ],
        }
    ]

    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))
    result = await service.build_document(hours=24, group_by="niche", min_wtp=0, max_items_per_group=5)

    db.get_latest_canonical_clusters.assert_awaited_once_with(limit=20, post_ids=["p1"])
    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert xml.index("Top pain clusters") < xml.index("<w:t>Current opportunities</w:t>")
    assert "#1 RevOps CSV approval handoffs" in xml
    assert "Opportunity score 91.3 | Confidence 0.86 | Intensity 9.0/10 | WTP 9.0/10 | Urgency high | Buyer authority 0.94" in xml
    assert "Why it matters: high monetization signal across 1 eligible verified post; RevOps teams lose time reconciling onboarding CSV handoffs before approval workflows." in xml
    assert "Verified evidence: we still reconcile onboarding CSVs by hand before approvals" in xml
    assert "Affected users/personas: RevOps manager; customer onboarding approvals" in xml
    assert "Current workarounds: manual CSV reconciliation before approval" in xml
    assert "Competitors/tools mentioned: hubspot, salesforce" in xml
    assert "Suggested wedge: Replace manual CSV reconciliation before approval with an auditable workflow focused on RevOps manager." in xml
    assert "Risks: Validate that CRM sync misses approval status changes is painful across more than 2 independent sources." in xml
    assert "Score breakdown: factors intensity=0.18, frequency=0.14, wtp=0.14; penalties noise=0.00" in xml
    assert "Coverage/confidence: Stability 0.91 | Verified quotes 4 | Sources 2 | Authors 3 | Frequency 12.5/1k posts, 3.2/1k comments" in xml
    assert "Link: https://reddit.com/p1" in xml


async def test_daily_digest_document_renders_competitor_failure_radar_from_verified_rows_and_clusters(tmp_path):
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
            "competitor_tags": '["hubspot"]',
            "source": "reddit",
            "url": "https://reddit.com/r/salesops/comments/radar-1",
            "subreddit": "salesops",
            "pain_type": "pricing_pain",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "head_of_ops",
            "buyer_authority_score": 0.94,
            "verified_evidence_json": '[{"quote":"HubSpot renewal doubled and we cannot export workflows","match_type":"exact","url":"https://reddit.com/r/salesops/comments/radar-1"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.91,
            "current_workaround": "exporting CSVs for offline review",
            "incumbent_failure": "HubSpot renewal pricing doubled and contract lock-in blocks switching",
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
            "competitor_tags": '["hubspot", "airtable"]',
            "comment_tool_mentions_json": '["airtable"]',
            "source": "hn",
            "url": "https://news.ycombinator.com/item?id=radar-2",
            "subreddit": "hn",
            "pain_type": "missing_feature",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "manager",
            "buyer_authority_score": 0.82,
            "verified_evidence_json": '[{"quote":"HubSpot is missing approval routing so we use Airtable","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.87,
            "current_workaround": "Airtable approval workaround",
            "incumbent_failure": "HubSpot is missing approval routing and support keeps stalling",
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
            "competitor_tags": '["hubspot"]',
            "source": "reddit",
            "url": "https://reddit.com/r/salesops/comments/radar-weak",
            "subreddit": "salesops",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "buyer_authority_score": 1.0,
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0.0,
            "confidence": 0.2,
            "current_workaround": "unknown",
            "incumbent_failure": "HubSpot support is allegedly awful",
            "score_components_json": '{"promotion_eligible": true}',
        },
    ]
    db.get_latest_canonical_clusters.return_value = [
        {
            "canonical_key": "crm-billing-sync-failures",
            "label": "CRM billing and sync failures",
            "summary": "Verified HubSpot complaints recur around renewal pricing, missing approvals, and switching friction.",
            "estimated_monetization_signal": "high",
            "post_ids": ["radar-1", "radar-2", "radar-weak"],
            "incumbents": ["hubspot", "airtable"],
            "representative_examples": [
                {"post_id": "radar-1", "verified_quotes": ["HubSpot renewal doubled and we cannot export workflows"]},
                {"post_id": "radar-2", "verified_quotes": ["HubSpot is missing approval routing so we use Airtable"]},
                {"post_id": "radar-weak", "verified_quotes": ["unsupported weak quote"]},
            ],
        }
    ]

    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))
    result = await service.build_document(hours=24, group_by="niche", min_wtp=0, max_items_per_group=5)

    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert xml.index("Competitor failures") < xml.index("<w:t>Current opportunities</w:t>")
    assert "hubspot (2 verified mentions)" in xml
    assert "Failure signals: Pricing pain (1) | Missing feature (1) | Switching/lock-in/churn (1) | Reliability/support failure (1) | Workaround (2) | Alternative-tool mentions (1)" in xml
    assert "Verified evidence: HubSpot renewal doubled and we cannot export workflows" in xml
    assert "Verified evidence: HubSpot is missing approval routing so we use Airtable" in xml
    assert "Cluster: CRM billing and sync failures" in xml
    assert "unsupported weak quote" not in xml
    assert "Unsupported high-score HubSpot complaint" in xml


async def test_daily_digest_cluster_cards_show_buyer_wtp_intelligence_for_verified_examples_only(tmp_path):
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

    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))
    result = await service.build_document(hours=24, group_by="niche", min_wtp=0, max_items_per_group=5)

    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    cluster_xml = xml[: xml.index("<w:t>Current opportunities</w:t>")]
    assert "Buyer/WTP intelligence" in cluster_xml
    assert "Buyer roles: head_of_ops (1) | founder_owner (1)" in cluster_xml
    assert "Avg buyer authority 0.97" in cluster_xml
    assert "Avg WTP 8.5/10" in cluster_xml
    assert "WTP evidence" in cluster_xml
    assert "I own ops budget and would pay to stop invoice approvals breaking" in cluster_xml
    assert "Paid workaround evidence" in cluster_xml
    assert "paid Zapier subscription plus contractor spreadsheet cleanup" in cluster_xml
    assert "monthly Airtable license workaround for reconciliation" in cluster_xml
    assert "Uncertainty" in cluster_xml
    assert "budget is explicit but seat count is unknown" in cluster_xml
    assert "unsupported would pay paraphrase" not in cluster_xml
    assert "unsupported buyer budget quote" not in cluster_xml
    assert "unsupported paid Zapier claim" not in cluster_xml


async def test_daily_digest_document_filters_mixed_cluster_cards_to_promoted_evidence(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "good-1",
            "title": "Verified RevOps workflow pain",
            "summary": "RevOps managers reconcile CSV handoffs before approvals.",
            "pain_level": 9,
            "willingness_to_pay": 9,
            "opportunity_score": 92.0,
            "niche_category": "RevOps",
            "competitor_tags": '["hubspot"]',
            "source": "reddit",
            "url": "https://reddit.com/good-1",
            "subreddit": "sales",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "head_of_ops",
            "buyer_authority_score": 0.94,
            "verified_evidence_json": '[{"quote":"I reconcile CSV handoffs by hand before approvals","source_type":"body","match_type":"exact","url":"https://reddit.com/good-1"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.88,
            "current_workaround": "manual CSV reconciliation before approval",
            "incumbent_failure": "CRM approval sync misses status changes",
            "user_context_json": '{"persona":"RevOps manager"}',
            "score_components_json": '{"factors":{"intensity":0.18},"penalties":{"noise":0.0}}',
        },
        {
            "post_id": "weak-1",
            "title": "Unsupported high-WTP RevOps claim",
            "summary": "Looks lucrative, but no exact source quote backs the claim.",
            "pain_level": 10,
            "willingness_to_pay": 10,
            "opportunity_score": 99.0,
            "niche_category": "RevOps",
            "competitor_tags": '["salesforce"]',
            "source": "reddit",
            "url": "https://reddit.com/weak-1",
            "subreddit": "sales",
            "opportunity_bucket": "current_opportunity",
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0,
            "confidence": 0.1,
            "score_components_json": '{"promotion_eligible":false,"evidence_rejection_reason":"no_verified_exact_quote"}',
        },
    ]
    db.get_latest_canonical_clusters.return_value = [
        {
            "canonical_key": "mixed-revops-claim",
            "label": "Mixed RevOps workflow cluster",
            "summary": "Cluster contains one verified workflow pain and one unsupported claim.",
            "estimated_monetization_signal": "high",
            "item_count": 2,
            "post_ids": ["good-1", "weak-1"],
            "avg_opportunity_score": 95.5,
            "aggregate_wtp": 19.0,
            "incumbents": ["hubspot", "salesforce"],
            "representative_examples": [
                {
                    "post_id": "weak-1",
                    "title": "Unsupported high-WTP RevOps claim",
                    "verified_quotes": [],
                    "source": "reddit",
                    "url": "https://reddit.com/weak-1",
                },
                {
                    "post_id": "good-1",
                    "title": "Verified RevOps workflow pain",
                    "verified_quotes": ["I reconcile CSV handoffs by hand before approvals"],
                    "source": "reddit",
                    "url": "https://reddit.com/good-1",
                    "current_workaround": "manual CSV reconciliation before approval",
                    "user_context": {"persona": "RevOps manager"},
                    "confidence": 0.88,
                    "intensity_score": 0.9,
                    "willingness_to_pay": 9,
                    "buyer_authority_score": 0.94,
                    "score_components": {"factors": {"intensity": 0.18}, "penalties": {"noise": 0.0}},
                },
            ],
        }
    ]

    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))
    result = await service.build_document(hours=24, group_by="niche", min_wtp=0, max_items_per_group=5)

    db.get_latest_canonical_clusters.assert_awaited_once_with(limit=20, post_ids=["good-1"])
    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "Top pain clusters" in xml
    assert "Mixed RevOps workflow cluster" in xml
    assert "Why it matters: high monetization signal across 1 eligible verified post;" in xml
    assert "Verified evidence: I reconcile CSV handoffs by hand before approvals" in xml
    assert "- Verified RevOps workflow pain (reddit)" in xml
    assert "Unsupported high-WTP RevOps claim (reddit)" not in xml[: xml.index("Needs Review / Weak signals")]
    assert "Evidence rejection: no_verified_exact_quote" in xml


async def test_daily_digest_document_does_not_promote_weak_rows_through_cluster_cards(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "weak-1",
            "title": "Unsupported high-WTP RevOps claim",
            "summary": "Looks lucrative, but no exact source quote backs the claim.",
            "pain_level": 10,
            "willingness_to_pay": 10,
            "opportunity_score": 94.0,
            "niche_category": "RevOps",
            "competitor_tags": '["salesforce"]',
            "source": "reddit",
            "url": "https://reddit.com/weak-1",
            "subreddit": "sales",
            "opportunity_bucket": "current_opportunity",
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0,
            "confidence": 0.22,
            "score_components_json": '{"promotion_eligible":false,"evidence_rejection_reason":"no_verified_exact_quote"}',
        }
    ]
    db.get_latest_canonical_clusters.return_value = [
        {
            "canonical_key": "unsupported-revops-claim",
            "label": "Unsupported RevOps claim cluster",
            "summary": "This should not be promoted as a top pain cluster without exact evidence.",
            "avg_opportunity_score": 94.0,
            "item_count": 1,
            "verified_quote_count": 0,
            "representative_examples": [
                {
                    "post_id": "weak-1",
                    "title": "Unsupported high-WTP RevOps claim",
                    "verified_quotes": [],
                    "source": "reddit",
                    "url": "https://reddit.com/weak-1",
                }
            ],
        }
    ]

    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))
    result = await service.build_document(hours=24, group_by="niche", min_wtp=0, max_items_per_group=5)

    db.get_latest_canonical_clusters.assert_not_awaited()
    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "Top pain clusters" not in xml
    assert "Unsupported RevOps claim cluster" not in xml
    assert "Needs Review / Weak signals" in xml
    assert "Unsupported high-WTP RevOps claim" in xml
    assert "Evidence rejection: no_verified_exact_quote" in xml


async def test_daily_digest_document_renders_bounded_rejected_noise_examples_with_reasons(tmp_path):
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
            "url": "https://example.com/eligible",
            "subreddit": "finance",
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
            "url": f"https://example.com/{post_id}",
            "subreddit": "finance",
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0,
            "confidence": 0.2,
            "score_components_json": f'{{"promotion_eligible": false, "evidence_rejection_reason": "{reason}"}}',
        }
        for index, (post_id, title, reason) in enumerate(rejected_rows)
    ]

    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))
    result = await service.build_document(hours=24, group_by="niche", min_wtp=0, max_items_per_group=5)

    db.get_recent_rejected_noise_candidates.assert_awaited_once_with(hours=24, limit=50)
    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "Rejected/noise examples" in xml
    for label in [
        "generic question",
        "consumer rant",
        "low context",
        "no evidence",
        "solved issue",
        "shill risk",
        "duplicate",
    ]:
        assert f"Reason: {label}" in xml
    assert "Duplicate of existing invoice thread" in xml
    assert "Overflow rejected item 5" not in xml
    assert "Verified invoice reconciliation pain" in xml[: xml.index("Rejected/noise examples")]


async def test_daily_digest_document_service_returns_empty_result_without_rows(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = []
    db.get_latest_canonical_clusters.return_value = []
    db.get_recent_rejected_noise_candidates.return_value = []

    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))

    result = await service.build_document(hours=24, group_by="niche", min_wtp=8, max_items_per_group=5)

    assert result.total_items == 0
    assert result.group_count == 0
    assert result.docx_path is None


async def test_daily_digest_document_orders_rows_by_opportunity_score_within_group(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "p-high",
            "title": "Lower WTP but stronger consensus",
            "summary": "Ops teams keep repeating the same manual workaround.",
            "pain_level": 7,
            "willingness_to_pay": 7,
            "opportunity_score": 92.0,
            "niche_category": "RevOps",
            "competitor_tags": '["hubspot"]',
            "source": "reddit",
            "url": "https://reddit.com/p-high",
            "subreddit": "sales",
            "deep_dive_summary": "CSV handoffs between teams keep breaking.",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "verified_evidence_json": '[{"quote":"Ops teams keep repeating the same manual workaround","source_type":"body","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "score_components_json": '{"promotion_eligible": true}',
        },
        {
            "post_id": "p-low",
            "title": "Higher WTP but weaker score",
            "summary": "Pain exists but consensus is weak.",
            "pain_level": 9,
            "willingness_to_pay": 9,
            "opportunity_score": 51.0,
            "niche_category": "RevOps",
            "competitor_tags": '["salesforce"]',
            "source": "reddit",
            "url": "https://reddit.com/p-low",
            "subreddit": "sales",
            "deep_dive_summary": "Single-team complaint.",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "verified_evidence_json": '[{"quote":"Pain exists but consensus is weak","source_type":"body","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "score_components_json": '{"promotion_eligible": true}',
        },
    ]

    db.get_latest_canonical_clusters.return_value = []
    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))
    result = await service.build_document(hours=24, group_by="niche", min_wtp=0, max_items_per_group=5)

    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert xml.index("Lower WTP but stronger consensus") < xml.index("Higher WTP but weaker score")


async def test_daily_digest_document_routes_weak_rows_out_of_current_opportunities(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = [
        {
            "post_id": "eligible",
            "title": "Verified RevOps workflow pain",
            "summary": "Ops owner quotes the exact recurring workflow breakage.",
            "pain_level": 7,
            "willingness_to_pay": 7,
            "opportunity_score": 72.0,
            "niche_category": "RevOps",
            "competitor_tags": '["hubspot"]',
            "source": "reddit",
            "url": "https://reddit.com/eligible",
            "subreddit": "sales",
            "opportunity_bucket": "current_opportunity",
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "verified_evidence_json": '[{"quote":"workflow breakage","source_type":"body","match_type":"exact"}]',
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "score_components_json": '{"promotion_eligible": true}',
        },
        {
            "post_id": "weak",
            "title": "Unsupported high-WTP RevOps claim",
            "summary": "Looks attractive but the analyzer supplied no quote.",
            "pain_level": 10,
            "willingness_to_pay": 10,
            "opportunity_score": 95.0,
            "niche_category": "RevOps",
            "competitor_tags": "[]",
            "source": "reddit",
            "url": "https://reddit.com/weak",
            "subreddit": "sales",
            "opportunity_bucket": "current_opportunity",
            "verified_evidence_json": "[]",
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0.0,
            "score_components_json": '{"promotion_eligible": true}',
        },
    ]

    db.get_latest_canonical_clusters.return_value = []
    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))
    result = await service.build_document(hours=24, group_by="niche", min_wtp=0, max_items_per_group=5)

    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "Current opportunities" in xml
    assert "Needs Review / Weak signals" in xml
    assert xml.index("Verified RevOps workflow pain") < xml.index("Needs Review / Weak signals")
    assert xml.index("Needs Review / Weak signals") < xml.index("Unsupported high-WTP RevOps claim")
    assert "Evidence rejection: no_verified_exact_quote" in xml
