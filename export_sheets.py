import asyncio
import csv
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

try:
    import gspread
except Exception:  # pragma: no cover - optional dependency at runtime
    gspread = None

from db import Database

logger = logging.getLogger(__name__)


SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@")
ARTIFACT_STEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")
MAX_WORKSHEET_TITLE_LENGTH = 100


def _safe_artifact_stem(raw: str, *, default: str = "scope") -> str:
    stem = ARTIFACT_STEM_RE.sub("_", str(raw or "").strip())
    stem = stem.strip("._-")
    return stem or default


def _safe_spreadsheet_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped.startswith(SPREADSHEET_FORMULA_PREFIXES):
        return "'" + value
    return value


def _analysis_payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("analysis_payload_json") or row.get("analysis_payload") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _promotion_value(row: dict[str, Any], key: str) -> Any:
    if key in row and row.get(key) is not None:
        return row.get(key)
    return _analysis_payload(row).get(key)


def _promotion_text(row: dict[str, Any], key: str) -> str:
    value = _promotion_value(row, key)
    return "" if value is None else str(value)


def _safe_worksheet_name(prefix: str, scope: str | None) -> str:
    safe_prefix = _safe_artifact_stem(prefix, default="pain_finder")
    safe_scope = _safe_artifact_stem(scope or "all", default="all")
    name = f"{safe_prefix}_{safe_scope}"
    return name[:MAX_WORKSHEET_TITLE_LENGTH].rstrip("._-") or "pain_finder"


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
        scope = _safe_artifact_stem(subreddit or "all", default="all")
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        csv_path = os.path.join(self.reports_dir, f"export_{scope}_{timestamp}.csv")
        tmp_path = f"{csv_path}.tmp"

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
            "opportunity_score",
            "promotion_eligible",
            "evidence_rejection_reason",
            "triage_status",
            "deep_dive_status",
            "deep_dive_summary",
            "url",
        ]

        try:
            with open(tmp_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                for row in rows:
                    writer.writerow({
                        "created_at": _safe_spreadsheet_cell(row.get("created_at", "")),
                        "subreddit": _safe_spreadsheet_cell(row.get("subreddit", "")),
                        "source": _safe_spreadsheet_cell(row.get("source", "")),
                        "post_id": _safe_spreadsheet_cell(row.get("post_id", "")),
                        "title": _safe_spreadsheet_cell(row.get("title", "")),
                        "summary": _safe_spreadsheet_cell(row.get("summary", "")),
                        "pain_level": row.get("pain_level", 0),
                        "willingness_to_pay": row.get("willingness_to_pay", 0),
                        "niche_category": _safe_spreadsheet_cell(row.get("niche_category", "")),
                        "competitor_tags": _safe_spreadsheet_cell(row.get("competitor_tags", "[]")),
                        "category": _safe_spreadsheet_cell(row.get("category", "")),
                        "severity": _safe_spreadsheet_cell(row.get("severity", "")),
                        "opportunity_score": row.get("opportunity_score", ""),
                        "promotion_eligible": _safe_spreadsheet_cell(_promotion_text(row, "promotion_eligible")),
                        "evidence_rejection_reason": _safe_spreadsheet_cell(
                            _promotion_text(row, "evidence_rejection_reason")
                        ),
                        "triage_status": _safe_spreadsheet_cell(row.get("triage_status", "new")),
                        "deep_dive_status": _safe_spreadsheet_cell(row.get("deep_dive_status", "not_requested")),
                        "deep_dive_summary": _safe_spreadsheet_cell(row.get("deep_dive_summary", "")),
                        "url": _safe_spreadsheet_cell(row.get("url", "")),
                    })
            os.replace(tmp_path, csv_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

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

        worksheet_name = _safe_worksheet_name(self.sheets_worksheet_prefix, subreddit)
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
                str(_safe_spreadsheet_cell(str(row.get("created_at", "")))),
                str(_safe_spreadsheet_cell(str(row.get("subreddit", "")))),
                str(_safe_spreadsheet_cell(str(row.get("source", "")))),
                str(_safe_spreadsheet_cell(str(row.get("post_id", "")))),
                str(_safe_spreadsheet_cell(str(row.get("title", "")))),
                str(_safe_spreadsheet_cell(str(row.get("summary", "")))),
                str(_safe_spreadsheet_cell(str(row.get("pain_level", 0)))),
                str(_safe_spreadsheet_cell(str(row.get("willingness_to_pay", 0)))),
                str(_safe_spreadsheet_cell(str(row.get("niche_category", "")))),
                str(_safe_spreadsheet_cell(str(row.get("competitor_tags", "[]")))),
                str(_safe_spreadsheet_cell(str(row.get("category", "")))),
                str(_safe_spreadsheet_cell(str(row.get("severity", "")))),
                str(_safe_spreadsheet_cell(str(row.get("opportunity_score", "")))),
                str(_safe_spreadsheet_cell(_promotion_text(row, "promotion_eligible"))),
                str(_safe_spreadsheet_cell(_promotion_text(row, "evidence_rejection_reason"))),
                str(_safe_spreadsheet_cell(str(row.get("triage_status", "new")))),
                str(_safe_spreadsheet_cell(str(row.get("deep_dive_status", "not_requested")))),
                str(_safe_spreadsheet_cell(str(row.get("deep_dive_summary", "")))),
                str(_safe_spreadsheet_cell(str(row.get("url", "")))),
            ])

        worksheet.update("A1", values)
        return f"https://docs.google.com/spreadsheets/d/{self.sheets_spreadsheet_id}"

