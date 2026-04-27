import csv
from unittest.mock import AsyncMock, MagicMock, patch

from export_sheets import ExportService


async def test_export_service_writes_csv_and_returns_warning_when_sheets_fails(tmp_path):
    db = AsyncMock()
    db.list_export_rows.return_value = [
        {
            "created_at": "2026-02-24T00:00:00",
            "subreddit": "python",
            "post_id": "abc",
            "title": "Need better sync",
            "summary": "Summary",
            "pain_level": 8,
            "willingness_to_pay": 9,
            "niche_category": "DevOps",
            "category": "complaint",
            "severity": "high",
            "triage_status": "new",
            "deep_dive_status": "not_requested",
            "deep_dive_summary": "",
            "url": "https://reddit.com/abc",
        }
    ]

    service = ExportService(
        db=db,
        reports_dir=str(tmp_path),
        min_wtp=8,
        sheets_credentials_json="{\"invalid\": true}",
        sheets_spreadsheet_id="sheet-id",
    )

    result = await service.export(subreddit="python")

    assert result.row_count == 1
    assert result.csv_path.endswith(".csv")
    assert result.warning is not None
    assert result.sheet_url is None


async def test_export_service_writes_verified_evidence_fields_to_csv(tmp_path):
    db = AsyncMock()
    db.list_export_rows.return_value = [
        {
            "created_at": "2026-02-24T00:00:00",
            "subreddit": "shopify",
            "source": "reddit",
            "post_id": "verified-csv",
            "title": "Need better inventory sync",
            "summary": "Inventory sync keeps lagging.",
            "pain_level": 8,
            "willingness_to_pay": 9,
            "niche_category": "E-commerce",
            "competitor_tags": '["shopify"]',
            "category": "complaint",
            "severity": "high",
            "triage_status": "new",
            "deep_dive_status": "not_requested",
            "deep_dive_summary": "",
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.82,
            "needs_human_review": 0,
            "verified_evidence_json": '[{"quote":"stock sync lags","match_type":"exact"}]',
            "url": "https://reddit.com/verified-csv",
        }
    ]

    service = ExportService(db=db, reports_dir=str(tmp_path), min_wtp=8)
    result = await service.export(subreddit="shopify")

    with open(result.csv_path, newline="", encoding="utf-8") as handle:
        exported_rows = list(csv.DictReader(handle))

    assert exported_rows[0]["evidence_quality"] == "exact_quote"
    assert exported_rows[0]["evidence_match_rate"] == "1.0"
    assert exported_rows[0]["confidence"] == "0.82"
    assert exported_rows[0]["needs_human_review"] == "0"
    assert "stock sync lags" in exported_rows[0]["verified_evidence_json"]


async def test_export_service_writes_wave5_taxonomy_and_score_fields_to_csv(tmp_path):
    db = AsyncMock()
    db.list_export_rows.return_value = [
        {
            "created_at": "2026-04-26T00:00:00",
            "subreddit": "shopify",
            "source": "reddit",
            "post_id": "wave5-export",
            "title": "Inventory sync blocks fulfillment",
            "summary": "Inventory reconciliation blocks fulfillment.",
            "pain_level": 8,
            "willingness_to_pay": 9,
            "niche_category": "E-commerce",
            "competitor_tags": '["netsuite"]',
            "category": "complaint",
            "severity": "high",
            "triage_status": "new",
            "deep_dive_status": "not_requested",
            "deep_dive_summary": "",
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.88,
            "needs_human_review": 0,
            "verified_evidence_json": '[{"quote":"reconcile inventory in spreadsheets","match_type":"exact"}]',
            "pain_type": "integration_gap",
            "expression_type": "feature_request",
            "user_context_json": '{"role":"ops_lead","industry":"ecommerce"}',
            "intensity_score": 0.82,
            "frequency_signal": "thread_consensus",
            "urgency": "active_blocker",
            "current_workaround": "spreadsheet",
            "wtp_score": 0.91,
            "incumbent_failure": "explicit_competitor_failure",
            "opportunity_type": "automation",
            "opportunity_score": 71.2,
            "score_components_json": '{"weights":{"intensity":0.18},"raw_score":71.2}',
            "url": "https://reddit.com/wave5-export",
        }
    ]

    service = ExportService(db=db, reports_dir=str(tmp_path), min_wtp=8)
    result = await service.export(subreddit="shopify")

    with open(result.csv_path, newline="", encoding="utf-8") as handle:
        exported_rows = list(csv.DictReader(handle))

    row = exported_rows[0]
    assert row["pain_type"] == "integration_gap"
    assert row["expression_type"] == "feature_request"
    assert row["user_context_json"] == '{"role":"ops_lead","industry":"ecommerce"}'
    assert row["intensity_score"] == "0.82"
    assert row["frequency_signal"] == "thread_consensus"
    assert row["urgency"] == "active_blocker"
    assert row["current_workaround"] == "spreadsheet"
    assert row["wtp_score"] == "0.91"
    assert row["incumbent_failure"] == "explicit_competitor_failure"
    assert row["opportunity_type"] == "automation"
    assert row["opportunity_score"] == "71.2"
    assert '"raw_score":71.2' in row["score_components_json"]


async def test_export_service_sanitizes_spreadsheet_formula_prefixes(tmp_path):
    db = AsyncMock()
    db.list_export_rows.return_value = [
        {
            "created_at": "2026-02-24T00:00:00",
            "subreddit": "shopify",
            "post_id": "formula-row",
            "title": "=IMPORTXML(\"https://example.com\",\"//title\")",
            "summary": "+SUM(1,2)",
            "pain_level": 8,
            "willingness_to_pay": 9,
            "niche_category": "E-commerce",
            "category": "complaint",
            "severity": "high",
            "triage_status": "new",
            "deep_dive_status": "not_requested",
            "uncertainty_reason": "@needs review",
            "url": "https://reddit.com/formula-row",
        }
    ]

    service = ExportService(db=db, reports_dir=str(tmp_path), min_wtp=8)
    result = await service.export(subreddit="shopify")

    with open(result.csv_path, newline="", encoding="utf-8") as handle:
        exported_rows = list(csv.DictReader(handle))

    assert exported_rows[0]["title"].startswith("'=")
    assert exported_rows[0]["summary"].startswith("'+")
    assert exported_rows[0]["uncertainty_reason"].startswith("'@")


def test_spreadsheet_safe_sanitizes_formula_prefix_after_leading_whitespace():
    assert ExportService._spreadsheet_safe(" =IMPORTXML('x')") == "' =IMPORTXML('x')"
    assert ExportService._spreadsheet_safe("\n+SUM(1,2)") == "'\n+SUM(1,2)"
    assert ExportService._spreadsheet_safe("\t@evil") == "'\t@evil"
    assert ExportService._spreadsheet_safe("\x00=CMD()") == "'\x00=CMD()"
    assert ExportService._spreadsheet_safe("\x1f+SUM(1,2)") == "'\x1f+SUM(1,2)"
    assert ExportService._spreadsheet_safe("plain text") == "plain text"


async def test_export_service_works_without_sheets_config(tmp_path):
    db = AsyncMock()
    db.list_export_rows.return_value = []

    service = ExportService(
        db=db,
        reports_dir=str(tmp_path),
        min_wtp=8,
    )

    result = await service.export(subreddit=None)
    assert result.row_count == 0
    assert result.warning is None
    assert result.sheet_url is None


async def test_export_service_returns_sheet_url_on_success(tmp_path):
    """Happy path: _upsert_google_sheet runs in asyncio.to_thread and returns URL."""
    db = AsyncMock()
    db.list_export_rows.return_value = [
        {
            "created_at": "2026-02-24T00:00:00",
            "subreddit": "python",
            "post_id": "xyz",
            "title": "Pain point title",
            "summary": "Some summary",
            "pain_level": 9,
            "willingness_to_pay": 10,
            "niche_category": "SaaS",
            "source": "reddit",
            "competitor_tags": "[]",
            "category": "complaint",
            "severity": "high",
            "triage_status": "new",
            "deep_dive_status": "not_requested",
            "deep_dive_summary": "",
            "url": "https://reddit.com/xyz",
        }
    ]

    expected_url = "https://docs.google.com/spreadsheets/d/sheet-id-123"

    service = ExportService(
        db=db,
        reports_dir=str(tmp_path),
        min_wtp=8,
        sheets_credentials_json='{"type": "service_account"}',
        sheets_spreadsheet_id="sheet-id-123",
    )

    # Patch asyncio.to_thread so _upsert_google_sheet is never actually invoked,
    # and verify the awaitable path is used (non-blocking).
    with patch("export_sheets.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = expected_url
        result = await service.export(subreddit="python")

    assert result.sheet_url == expected_url
    assert result.warning is None
    assert result.row_count == 1
    # Confirm to_thread was called with the sync method (not a direct call)
    mock_to_thread.assert_called_once()
    call_args = mock_to_thread.call_args
    assert call_args.args[0] == service._upsert_google_sheet


async def test_upsert_google_sheet_is_sync_method(tmp_path):
    """_upsert_google_sheet must remain a regular (non-async) method."""
    import asyncio as _asyncio

    db = MagicMock()
    service = ExportService(
        db=db,
        reports_dir=str(tmp_path),
        min_wtp=8,
    )
    assert not _asyncio.iscoroutinefunction(service._upsert_google_sheet), (
        "_upsert_google_sheet must stay synchronous"
    )
