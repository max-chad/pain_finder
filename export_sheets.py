import asyncio
import csv
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

try:
    import gspread
except Exception:  # pragma: no cover - optional dependency at runtime
    gspread = None

from db import Database

logger = logging.getLogger(__name__)


@dataclass
class ExportResult:
    csv_path: str
    row_count: int
    sheet_url: str | None = None
    warning: str | None = None


class ExportService:
    def __init__(
        self,
        db: Database,
        reports_dir: str,
        min_wtp: int = 8,
        sheets_credentials_json: str = "",
        sheets_spreadsheet_id: str = "",
        sheets_worksheet_prefix: str = "pain_finder",
    ):
        self.db = db
        self.reports_dir = reports_dir
        self.min_wtp = min_wtp
        self.sheets_credentials_json = sheets_credentials_json
        self.sheets_spreadsheet_id = sheets_spreadsheet_id
        self.sheets_worksheet_prefix = sheets_worksheet_prefix

    async def export(self, *, subreddit: str | None = None) -> ExportResult:
        rows = await self.db.list_export_rows(
            subreddit=subreddit,
            min_wtp=self.min_wtp,
            include_favorites=True,
        )

        os.makedirs(self.reports_dir, exist_ok=True)
        scope = subreddit or "all"
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(self.reports_dir, f"export_{scope}_{timestamp}.csv")

        headers = [
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
        ]

        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "created_at": row.get("created_at", ""),
                    "subreddit": row.get("subreddit", ""),
                    "source": row.get("source", ""),
                    "post_id": row.get("post_id", ""),
                    "title": row.get("title", ""),
                    "summary": row.get("summary", ""),
                    "pain_level": row.get("pain_level", 0),
                    "willingness_to_pay": row.get("willingness_to_pay", 0),
                    "niche_category": row.get("niche_category", ""),
                    "competitor_tags": row.get("competitor_tags", "[]"),
                    "category": row.get("category", ""),
                    "severity": row.get("severity", ""),
                    "triage_status": row.get("triage_status", "new"),
                    "deep_dive_status": row.get("deep_dive_status", "not_requested"),
                    "deep_dive_summary": row.get("deep_dive_summary", ""),
                    "url": row.get("url", ""),
                })

        sheet_url = None
        warning = None
        if self.sheets_credentials_json and self.sheets_spreadsheet_id:
            try:
                sheet_url = await asyncio.to_thread(
                    self._upsert_google_sheet, rows=rows, headers=headers, subreddit=subreddit
                )
            except Exception as e:
                warning = f"Google Sheets export failed: {e}"
                logger.warning(warning)

        return ExportResult(
            csv_path=csv_path,
            row_count=len(rows),
            sheet_url=sheet_url,
            warning=warning,
        )

    def _upsert_google_sheet(
        self,
        *,
        rows: list[dict[str, Any]],
        headers: list[str],
        subreddit: str | None,
    ) -> str:
        if gspread is None:
            raise RuntimeError("gspread is not installed")

        creds = json.loads(self.sheets_credentials_json)
        client = gspread.service_account_from_dict(creds)
        spreadsheet = client.open_by_key(self.sheets_spreadsheet_id)

        worksheet_name = f"{self.sheets_worksheet_prefix}_{subreddit or 'all'}"
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
            worksheet.clear()
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=worksheet_name,
                rows=max(100, len(rows) + 10),
                cols=len(headers) + 2,
            )

        values = [headers]
        for row in rows:
            values.append([
                str(row.get("created_at", "")),
                str(row.get("subreddit", "")),
                str(row.get("source", "")),
                str(row.get("post_id", "")),
                str(row.get("title", "")),
                str(row.get("summary", "")),
                str(row.get("pain_level", 0)),
                str(row.get("willingness_to_pay", 0)),
                str(row.get("niche_category", "")),
                str(row.get("competitor_tags", "[]")),
                str(row.get("category", "")),
                str(row.get("severity", "")),
                str(row.get("triage_status", "new")),
                str(row.get("deep_dive_status", "not_requested")),
                str(row.get("deep_dive_summary", "")),
                str(row.get("url", "")),
            ])

        worksheet.update("A1", values)
        return f"https://docs.google.com/spreadsheets/d/{self.sheets_spreadsheet_id}"

