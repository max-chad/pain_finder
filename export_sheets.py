import asyncio
import csv
import json
import logging
import os
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

try:
    import gspread
except Exception:  # pragma: no cover - optional dependency at runtime
    gspread = None

from db import Database

logger = logging.getLogger(__name__)


EXPORT_HEADERS = [
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
    "evidence_quality",
    "evidence_match_rate",
    "confidence",
    "uncertainty_reason",
    "needs_human_review",
    "pain_type",
    "expression_type",
    "user_context_json",
    "intensity_score",
    "frequency_signal",
    "urgency",
    "current_workaround",
    "wtp_score",
    "incumbent_failure",
    "opportunity_type",
    "opportunity_score",
    "score_breakdown_json",
    "score_components_json",
    "verified_evidence_json",
    "canonical_cluster_key",
    "cluster_key",
    "cluster_label",
    "cluster_stability_score",
    "cluster_verified_quote_count",
    "cluster_independent_source_count",
    "cluster_similarity",
    "pain_mentions_per_1000_posts",
    "pain_mentions_per_1000_comments",
    "unique_authors_count",
    "unique_threads_count",
    "weekly_delta",
    "source_activity_baseline_json",
    "feedback_status",
    "feedback_total",
    "feedback_counts_json",
    "latest_feedback_value",
    "latest_feedback_at",
    "url",
]


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

        headers = self._headers()

        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                record = self._export_record(row)
                writer.writerow({key: self._spreadsheet_safe(record.get(key, "")) for key in headers})

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

    @staticmethod
    def _headers() -> list[str]:
        return list(EXPORT_HEADERS)

    @classmethod
    def _export_record(cls, row: dict[str, Any]) -> dict[str, Any]:
        score_components = cls._json_text(row.get("score_components_json", "{}"), default="{}")
        return {
            "created_at": row.get("created_at", ""),
            "subreddit": row.get("subreddit", ""),
            "source": row.get("source", ""),
            "post_id": row.get("post_id", ""),
            "title": row.get("title", ""),
            "summary": row.get("summary", ""),
            "pain_level": row.get("pain_level", 0),
            "willingness_to_pay": row.get("willingness_to_pay", 0),
            "niche_category": row.get("niche_category", ""),
            "competitor_tags": cls._json_text(row.get("competitor_tags", "[]"), default="[]"),
            "category": row.get("category", ""),
            "severity": row.get("severity", ""),
            "triage_status": row.get("triage_status", "new"),
            "deep_dive_status": row.get("deep_dive_status", "not_requested"),
            "deep_dive_summary": row.get("deep_dive_summary", ""),
            "evidence_quality": row.get("evidence_quality", "no_quote"),
            "evidence_match_rate": row.get("evidence_match_rate", 0),
            "confidence": row.get("confidence", 0),
            "uncertainty_reason": row.get("uncertainty_reason", ""),
            "needs_human_review": row.get("needs_human_review", 0),
            "pain_type": row.get("pain_type", "unknown"),
            "expression_type": row.get("expression_type", "unknown"),
            "user_context_json": cls._json_text(row.get("user_context_json", "{}"), default="{}"),
            "intensity_score": row.get("intensity_score", 0),
            "frequency_signal": row.get("frequency_signal", "single"),
            "urgency": row.get("urgency", "none"),
            "current_workaround": row.get("current_workaround", ""),
            "wtp_score": row.get("wtp_score", 0),
            "incumbent_failure": row.get("incumbent_failure", ""),
            "opportunity_type": row.get("opportunity_type", "unknown"),
            "opportunity_score": row.get("opportunity_score", 0),
            "score_breakdown_json": cls._json_text(row.get("score_breakdown_json") or score_components, default="{}"),
            "score_components_json": score_components,
            "verified_evidence_json": cls._json_text(row.get("verified_evidence_json", "[]"), default="[]"),
            "canonical_cluster_key": row.get("canonical_cluster_key", ""),
            "cluster_key": row.get("cluster_key", ""),
            "cluster_label": row.get("cluster_label", ""),
            "cluster_stability_score": row.get("cluster_stability_score", 0),
            "cluster_verified_quote_count": row.get("cluster_verified_quote_count", 0),
            "cluster_independent_source_count": row.get("cluster_independent_source_count", 0),
            "cluster_similarity": row.get("cluster_similarity", 0),
            "pain_mentions_per_1000_posts": row.get("pain_mentions_per_1000_posts", 0),
            "pain_mentions_per_1000_comments": row.get("pain_mentions_per_1000_comments", 0),
            "unique_authors_count": row.get("unique_authors_count", 0),
            "unique_threads_count": row.get("unique_threads_count", 0),
            "weekly_delta": row.get("weekly_delta", 0),
            "source_activity_baseline_json": cls._json_text(
                row.get("source_activity_baseline_json", "{}"), default="{}"
            ),
            "feedback_status": row.get("feedback_status", "none"),
            "feedback_total": row.get("feedback_total", 0),
            "feedback_counts_json": cls._json_text(row.get("feedback_counts_json", "{}"), default="{}"),
            "latest_feedback_value": row.get("latest_feedback_value", ""),
            "latest_feedback_at": row.get("latest_feedback_at", ""),
            "url": row.get("url", ""),
        }

    @staticmethod
    def _json_text(value: Any, *, default: str) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        if value is None:
            return default
        text = str(value).strip()
        return text if text else default

    @staticmethod
    def _spreadsheet_safe(value: Any) -> Any:
        if not isinstance(value, str) or not value:
            return value
        first_visible_index = 0
        while first_visible_index < len(value):
            char = value[first_visible_index]
            if not char.isspace() and unicodedata.category(char)[0] != "C":
                break
            first_visible_index += 1
        if first_visible_index < len(value) and value[first_visible_index] in {"=", "+", "-", "@"}:
            return f"'{value}"
        return value

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
            record = self._export_record(row)
            values.append([self._spreadsheet_safe(record.get(header, "")) for header in headers])

        worksheet.update("A1", values)
        return f"https://docs.google.com/spreadsheets/d/{self.sheets_spreadsheet_id}"

