from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from docx import Document


@dataclass
class DigestDocumentResult:
    docx_path: str | None
    total_items: int
    group_count: int
    group_sizes: dict[str, int]


class DailyDigestDocumentService:
    def __init__(self, *, db, reports_dir: str):
        self.db = db
        self.reports_dir = reports_dir

    async def build_document(
        self,
        *,
        hours: int = 24,
        group_by: str = "niche",
        min_wtp: int = 8,
        max_items_per_group: int = 10,
    ) -> DigestDocumentResult:
        rows = await self.db.get_recent_pain_points(hours=hours, limit=500)
        filtered_rows = [row for row in rows if self._include_row(row, min_wtp=min_wtp)]
        if not filtered_rows:
            return DigestDocumentResult(docx_path=None, total_items=0, group_count=0, group_sizes={})

        grouped = self._group_rows(filtered_rows, group_by=group_by)
        ordered_groups = self._order_groups(grouped)

        document = Document()
        document.add_heading("Pain Finder Daily Digest", level=0)
        document.add_paragraph(
            (
                f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"Window: last {hours}h\n"
                f"Grouping: {group_by}\n"
                f"Included items: {sum(len(items) for _, items in ordered_groups)}"
            )
        )

        overview = document.add_paragraph()
        overview.add_run("Groups: ").bold = True
        overview.add_run(", ".join(f"{label} ({len(items)})" for label, items in ordered_groups[:8]))

        blockers = self._recurring_blockers(filtered_rows)
        if blockers:
            blockers_paragraph = document.add_paragraph()
            blockers_paragraph.add_run("Recurring blockers: ").bold = True
            blockers_paragraph.add_run(" | ".join(blockers))

        for label, items in ordered_groups:
            document.add_heading(f"{label} ({len(items)})", level=1)
            for row in items[:max_items_per_group]:
                title = (row.get("title") or "Untitled").strip() or "Untitled"
                summary = (row.get("summary") or "No summary available.").strip() or "No summary available."
                source = (row.get("source") or "unknown").strip() or "unknown"
                subreddit = (row.get("subreddit") or "n/a").strip() or "n/a"
                url = (row.get("url") or "").strip()
                wtp = int(row.get("willingness_to_pay") or 0)
                pain_level = int(row.get("pain_level") or 0)
                competitors = ", ".join(self._competitor_tags(row)) or "none"
                deep_dive_summary = (row.get("deep_dive_summary") or "").strip()

                header = document.add_paragraph()
                header.add_run(title).bold = True
                metrics = document.add_paragraph(
                    f"WTP {wtp}/10 | Pain {pain_level}/10 | Source {source} | Scope {subreddit}"
                )
                metrics.style = "Intense Quote"
                document.add_paragraph(summary)
                document.add_paragraph(f"Competitors/tags: {competitors}")
                if deep_dive_summary:
                    document.add_paragraph(f"Deep dive: {deep_dive_summary}")
                if url:
                    document.add_paragraph(f"Link: {url}")

        os.makedirs(self.reports_dir, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        final_path = os.path.join(self.reports_dir, f"daily_digest_{timestamp}.docx")
        tmp_path = f"{final_path}.tmp"
        try:
            document.save(tmp_path)
            os.replace(tmp_path, final_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        return DigestDocumentResult(
            docx_path=final_path,
            total_items=sum(len(items[:max_items_per_group]) for _, items in ordered_groups),
            group_count=len(ordered_groups),
            group_sizes={label: len(items) for label, items in ordered_groups},
        )

    @staticmethod
    def _include_row(row: dict[str, Any], *, min_wtp: int) -> bool:
        triage_status = str(row.get("triage_status") or "new").strip().lower()
        if triage_status == "favorite":
            return True
        return int(row.get("willingness_to_pay") or 0) >= min_wtp

    @staticmethod
    def _group_label(row: dict[str, Any], *, group_by: str) -> str:
        if group_by == "source":
            return (str(row.get("source") or "unknown").strip() or "unknown").title()
        if group_by == "category":
            return (str(row.get("category") or "Uncategorized").strip() or "Uncategorized").title()
        return str(row.get("niche_category") or "Uncategorized").strip() or "Uncategorized"

    def _group_rows(self, rows: list[dict[str, Any]], *, group_by: str) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[self._group_label(row, group_by=group_by)].append(row)
        return grouped

    @staticmethod
    def _order_groups(grouped: dict[str, list[dict[str, Any]]]) -> list[tuple[str, list[dict[str, Any]]]]:
        def _group_score(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, int, str]:
            label, rows = item
            best_wtp = max(int(row.get("willingness_to_pay") or 0) for row in rows)
            return (-best_wtp, -len(rows), label.lower())

        ordered_groups = sorted(grouped.items(), key=_group_score)
        for _, rows in ordered_groups:
            rows.sort(
                key=lambda row: (
                    int(row.get("willingness_to_pay") or 0),
                    int(row.get("pain_level") or 0),
                    str(row.get("created_at") or ""),
                ),
                reverse=True,
            )
        return ordered_groups

    @staticmethod
    def _competitor_tags(row: dict[str, Any]) -> list[str]:
        raw = row.get("competitor_tags") or []
        if isinstance(raw, list):
            return [str(item) for item in raw if str(item).strip()]
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = [raw]
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
            if parsed:
                return [str(parsed)]
        return []

    @staticmethod
    def _recurring_blockers(rows: list[dict[str, Any]]) -> list[str]:
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            summary = str(row.get("deep_dive_summary") or "").strip()
            if summary:
                counts[summary] += 1
        return [summary for summary, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]]
