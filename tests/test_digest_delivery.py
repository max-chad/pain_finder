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
            "opportunity_bucket": "current_opportunity",
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
        }
    ]

    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))

    result = await service.build_document(hours=24, group_by="niche", min_wtp=8, max_items_per_group=5)

    assert result.total_items == 3
    assert result.group_count == 2
    assert result.docx_path is not None
    assert result.docx_path.endswith(".docx")

    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "Pain Finder Daily Digest" in xml
    assert "Canonical pain clusters" in xml
    assert "RevOps handoff breakage" in xml
    assert "Current opportunities" in xml
    assert "Evergreen pain index" in xml
    assert "RevOps" in xml
    assert "FinOps" in xml
    assert "Need better onboarding handoff" in xml
    assert "Pipeline attribution is still fuzzy" in xml
    assert "Forecasting still lives in spreadsheets" in xml


async def test_daily_digest_document_service_returns_empty_result_without_rows(tmp_path):
    db = AsyncMock()
    db.get_recent_pain_points.return_value = []
    db.get_latest_canonical_clusters.return_value = []

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
        },
    ]

    db.get_latest_canonical_clusters.return_value = []
    service = DailyDigestDocumentService(db=db, reports_dir=str(tmp_path))
    result = await service.build_document(hours=24, group_by="niche", min_wtp=0, max_items_per_group=5)

    with zipfile.ZipFile(result.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert xml.index("Lower WTP but stronger consensus") < xml.index("Higher WTP but weaker score")
