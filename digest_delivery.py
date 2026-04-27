from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from docx import Document

PROMOTION_BUYER_AUTHORITY_MIN_SCORE = 0.82
BUYER_AUTHORITY_SCORES = {
    "intern": 0.35,
    "ic": 0.6,
    "engineer": 0.72,
    "manager": 0.82,
    "head_of_ops": 0.94,
    "founder_owner": 1.0,
    "agency_operator": 0.88,
    "unknown": 0.55,
}


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

        filtered_post_ids = [str(row.get("post_id")) for row in filtered_rows if row.get("post_id")]
        canonical_clusters = await self.db.get_latest_canonical_clusters(limit=6, post_ids=filtered_post_ids)

        promotion_rows = [row for row in filtered_rows if self._promotion_eligible(row)]
        weak_rows = [row for row in filtered_rows if not self._promotion_eligible(row)]
        current_rows = [row for row in promotion_rows if self._opportunity_bucket(row) == "current_opportunity"]
        evergreen_rows = [row for row in promotion_rows if self._opportunity_bucket(row) == "evergreen_pain"]
        unknown_rows = [row for row in promotion_rows if self._opportunity_bucket(row) == "unknown_age"]
        current_groups = self._order_groups(self._group_rows(current_rows, group_by=group_by)) if current_rows else []
        evergreen_groups = self._order_groups(self._group_rows(evergreen_rows, group_by=group_by)) if evergreen_rows else []
        unknown_groups = self._order_groups(self._group_rows(unknown_rows, group_by=group_by)) if unknown_rows else []
        weak_groups = self._order_groups(self._group_rows(weak_rows, group_by=group_by)) if weak_rows else []

        document = Document()
        document.add_heading("Pain Finder Daily Digest", level=0)
        document.add_paragraph(
            (
                f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"Window: last {hours}h\n"
                f"Grouping: {group_by}\n"
                f"Current opportunities: {sum(len(items) for _, items in current_groups)}\n"
                f"Evergreen pain index: {sum(len(items) for _, items in evergreen_groups)}\n"
                f"Unknown age review queue: {sum(len(items) for _, items in unknown_groups)}\n"
                f"Needs review / weak signals: {sum(len(items) for _, items in weak_groups)}"
            )
        )

        overview = document.add_paragraph()
        overview.add_run("Current opportunity groups: ").bold = True
        overview.add_run(", ".join(f"{label} ({len(items)})" for label, items in current_groups[:8]) or "none")

        evergreen_overview = document.add_paragraph()
        evergreen_overview.add_run("Evergreen groups: ").bold = True
        evergreen_overview.add_run(", ".join(f"{label} ({len(items)})" for label, items in evergreen_groups[:8]) or "none")

        unknown_overview = document.add_paragraph()
        unknown_overview.add_run("Unknown-age groups: ").bold = True
        unknown_overview.add_run(", ".join(f"{label} ({len(items)})" for label, items in unknown_groups[:8]) or "none")

        weak_overview = document.add_paragraph()
        weak_overview.add_run("Needs-review / weak-signal groups: ").bold = True
        weak_overview.add_run(", ".join(f"{label} ({len(items)})" for label, items in weak_groups[:8]) or "none")

        blockers = self._recurring_blockers(filtered_rows)
        if blockers:
            blockers_paragraph = document.add_paragraph()
            blockers_paragraph.add_run("Recurring blockers: ").bold = True
            blockers_paragraph.add_run(" | ".join(blockers))

        if canonical_clusters:
            document.add_heading("Canonical pain clusters", level=1)
            self._render_cluster_section(document, canonical_clusters)

        if current_groups:
            document.add_heading("Current opportunities", level=1)
            self._render_grouped_section(document, current_groups, max_items_per_group=max_items_per_group)
        if evergreen_groups:
            document.add_heading("Evergreen pain index", level=1)
            self._render_grouped_section(document, evergreen_groups, max_items_per_group=max_items_per_group)
        if unknown_groups:
            document.add_heading("Unknown age review queue", level=1)
            self._render_grouped_section(document, unknown_groups, max_items_per_group=max_items_per_group)
        if weak_groups:
            document.add_heading("Needs Review / Weak signals", level=1)
            self._render_grouped_section(document, weak_groups, max_items_per_group=max_items_per_group)

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

        all_groups = current_groups + evergreen_groups + unknown_groups + weak_groups
        return DigestDocumentResult(
            docx_path=final_path,
            total_items=sum(len(items[:max_items_per_group]) for _, items in all_groups),
            group_count=len(all_groups),
            group_sizes={label: len(items) for label, items in all_groups},
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
    def _opportunity_bucket(row: dict[str, Any]) -> str:
        bucket = str(row.get("opportunity_bucket") or "").strip().lower()
        if bucket == "current_opportunity":
            return "current_opportunity"
        if bucket == "evergreen_pain":
            return "evergreen_pain"
        return "unknown_age"

    def _render_cluster_section(self, document: Document, clusters: list[dict[str, Any]]) -> None:
        for cluster in clusters:
            label = (str(cluster.get("label") or "Recurring pain cluster").strip() or "Recurring pain cluster")
            summary = (str(cluster.get("summary") or "No summary available.").strip() or "No summary available.")
            avg_score = float(cluster.get("avg_opportunity_score") or 0.0)
            fresh_post_count = int(cluster.get("fresh_post_count") or 0)
            evergreen_post_count = int(cluster.get("evergreen_post_count") or 0)
            incumbents = cluster.get("incumbents") or []
            incumbents_text = ", ".join(str(item) for item in incumbents[:4]) or "none"

            document.add_heading(label, level=2)
            metrics = document.add_paragraph(
                f"Avg opp {avg_score:.1f} | Fresh {fresh_post_count} | Evergreen {evergreen_post_count}"
            )
            metrics.style = "Intense Quote"
            document.add_paragraph(summary)
            posts_frequency = float(cluster.get("pain_mentions_per_1000_posts") or 0.0)
            comments_frequency = float(cluster.get("pain_mentions_per_1000_comments") or 0.0)
            authors_count = int(cluster.get("unique_authors_count") or 0)
            threads_count = int(cluster.get("unique_threads_count") or 0)
            if posts_frequency or comments_frequency or authors_count or threads_count:
                document.add_paragraph(
                    "Pain frequency "
                    f"{posts_frequency:.1f}/1k posts | {comments_frequency:.1f}/1k comments | "
                    f"Authors {authors_count} | Threads {threads_count}"
                )
            stability = float(cluster.get("cluster_stability_score") or 0.0)
            verified_quote_count = int(cluster.get("verified_quote_count") or 0)
            independent_source_count = int(cluster.get("independent_source_count") or 0)
            quality_author_count = int(cluster.get("unique_author_count") or cluster.get("unique_authors_count") or 0)
            if stability or verified_quote_count or independent_source_count or quality_author_count:
                document.add_paragraph(
                    f"Cluster quality: Stability {stability:.2f} | Verified quotes {verified_quote_count} | "
                    f"Sources {independent_source_count} | Authors {quality_author_count}"
                )
            representative_examples = cluster.get("representative_examples") or []
            if representative_examples:
                examples_header = document.add_paragraph()
                examples_header.add_run("Representative examples").bold = True
                for example in representative_examples[:3]:
                    if not isinstance(example, dict):
                        continue
                    title = str(example.get("title") or "Untitled").strip() or "Untitled"
                    source = str(example.get("source") or "unknown").strip() or "unknown"
                    document.add_paragraph(f"- {title} ({source})")
                    quotes = example.get("verified_quotes") or []
                    if quotes:
                        document.add_paragraph(f"  Evidence: {str(quotes[0])}")
                    url = str(example.get("url") or "").strip()
                    if url:
                        document.add_paragraph(f"  Link: {url}")
            document.add_paragraph(f"Dominant incumbents: {incumbents_text}")

    def _render_grouped_section(
        self,
        document: Document,
        ordered_groups: list[tuple[str, list[dict[str, Any]]]],
        *,
        max_items_per_group: int,
    ) -> None:
        for label, items in ordered_groups:
            document.add_heading(f"{label} ({len(items)})", level=2)
            for row in items[:max_items_per_group]:
                title = (row.get("title") or "Untitled").strip() or "Untitled"
                summary = (row.get("summary") or "No summary available.").strip() or "No summary available."
                source = (row.get("source") or "unknown").strip() or "unknown"
                subreddit = (row.get("subreddit") or "n/a").strip() or "n/a"
                url = (row.get("url") or "").strip()
                wtp = int(row.get("willingness_to_pay") or 0)
                pain_level = int(row.get("pain_level") or 0)
                opportunity_score = self._row_opportunity_score(row)
                competitors = ", ".join(self._competitor_tags(row)) or "none"
                deep_dive_summary = (row.get("deep_dive_summary") or "").strip()

                header = document.add_paragraph()
                header.add_run(title).bold = True
                metrics = document.add_paragraph(
                    f"Opp {opportunity_score:.1f} | WTP {wtp}/10 | Pain {pain_level}/10 | Source {source} | Scope {subreddit}"
                )
                metrics.style = "Intense Quote"
                document.add_paragraph(summary)
                evidence = self._verified_evidence(row)
                if evidence:
                    document.add_paragraph(f"Evidence: {evidence[0].get('quote', '')}")
                evidence_meta = self._evidence_metadata(row)
                if evidence_meta:
                    document.add_paragraph(evidence_meta)
                document.add_paragraph(f"Competitors/tags: {competitors}")
                if deep_dive_summary:
                    document.add_paragraph(f"Deep dive: {deep_dive_summary}")
                if url:
                    document.add_paragraph(f"Link: {url}")

    @classmethod
    def _order_groups(cls, grouped: dict[str, list[dict[str, Any]]]) -> list[tuple[str, list[dict[str, Any]]]]:
        def _group_score(item: tuple[str, list[dict[str, Any]]]) -> tuple[float, int, str]:
            label, rows = item
            best_score = max(cls._row_opportunity_score(row) for row in rows)
            return (-best_score, -len(rows), label.lower())

        ordered_groups = sorted(grouped.items(), key=_group_score)
        for _, rows in ordered_groups:
            rows.sort(
                key=lambda row: (
                    cls._row_opportunity_score(row),
                    int(row.get("source_created_ts") or 0),
                    int(row.get("willingness_to_pay") or 0),
                    int(row.get("pain_level") or 0),
                ),
                reverse=True,
            )
        return ordered_groups

    @staticmethod
    def _row_opportunity_score(row: dict[str, Any]) -> float:
        raw = row.get("opportunity_score")
        try:
            if raw is not None:
                return float(raw)
        except (TypeError, ValueError):
            pass
        return float(int(row.get("willingness_to_pay") or 0))

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
    def _verified_evidence(row: dict[str, Any]) -> list[dict[str, Any]]:
        raw = row.get("verified_evidence")
        if isinstance(raw, list):
            parsed = raw
        else:
            raw = row.get("verified_evidence_json")
            if not isinstance(raw, str) or not raw.strip():
                return []
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return []
        if not isinstance(parsed, list):
            return []
        evidence = [
            item
            for item in parsed
            if isinstance(item, dict)
            and str(item.get("quote") or "").strip()
            and str(item.get("match_type") or "none").lower() in {"exact", "fuzzy"}
        ]
        return sorted(evidence, key=lambda item: 0 if str(item.get("match_type") or "") == "exact" else 1)

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return False

    @staticmethod
    def _score_components(row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("score_components")
        if isinstance(raw, dict):
            return raw
        raw = row.get("score_components_json")
        if not isinstance(raw, str) or not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _buyer_authority_score(row: dict[str, Any]) -> float:
        try:
            return float(row.get("buyer_authority_score"))
        except (TypeError, ValueError):
            authority = str(row.get("buyer_authority") or "unknown").strip().lower()
            return float(BUYER_AUTHORITY_SCORES.get(authority, BUYER_AUTHORITY_SCORES["unknown"]))

    @staticmethod
    def _exact_evidence_count(row: dict[str, Any]) -> int:
        return sum(1 for item in DailyDigestDocumentService._verified_evidence(row) if item.get("match_type") == "exact")

    @staticmethod
    def _evidence_rejection_reason(row: dict[str, Any]) -> str:
        components = DailyDigestDocumentService._score_components(row)
        reason = str(components.get("evidence_rejection_reason") or "").strip()
        if reason:
            return reason
        if DailyDigestDocumentService._exact_evidence_count(row) <= 0:
            return "no_verified_exact_quote"
        if DailyDigestDocumentService._coerce_bool(row.get("needs_human_review")):
            return "needs_human_review"
        first_handness = str(row.get("first_handness") or "unknown").strip().lower()
        authority_score = DailyDigestDocumentService._buyer_authority_score(row)
        if first_handness != "first_hand" and authority_score < PROMOTION_BUYER_AUTHORITY_MIN_SCORE:
            return "missing_first_hand_or_buyer_signal"
        return ""

    @staticmethod
    def _promotion_eligible(row: dict[str, Any]) -> bool:
        return not DailyDigestDocumentService._evidence_rejection_reason(row)

    @staticmethod
    def _evidence_metadata(row: dict[str, Any]) -> str:
        quality = str(row.get("evidence_quality") or "").strip()
        if not quality:
            return ""
        try:
            match_rate = float(row.get("evidence_match_rate") or 0.0)
        except (TypeError, ValueError):
            match_rate = 0.0
        try:
            confidence = float(row.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        needs_review = DailyDigestDocumentService._coerce_bool(row.get("needs_human_review"))
        uncertainty_reason = str(row.get("uncertainty_reason") or "").strip()
        rejection_reason = DailyDigestDocumentService._evidence_rejection_reason(row)
        if (
            quality == "no_quote"
            and match_rate == 0.0
            and confidence == 0.0
            and not needs_review
            and not uncertainty_reason
            and not rejection_reason
            and not DailyDigestDocumentService._verified_evidence(row)
        ):
            return ""
        human_review = "yes" if needs_review else "no"
        metadata = (
            f"Evidence quality: {quality} | Match rate {match_rate:.2f} | "
            f"Confidence {confidence:.2f} | Human review {human_review}"
        )
        if uncertainty_reason:
            metadata = f"{metadata} | Reason: {uncertainty_reason}"
        if rejection_reason:
            metadata = f"{metadata} | Evidence rejection: {rejection_reason}"
        return metadata

    @staticmethod
    def _recurring_blockers(rows: list[dict[str, Any]]) -> list[str]:
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            summary = str(row.get("deep_dive_summary") or "").strip()
            if summary:
                counts[summary] += 1
        return [summary for summary, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]]
