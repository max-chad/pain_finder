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

        promotion_rows = [row for row in filtered_rows if self._promotion_eligible(row)]
        weak_rows = [row for row in filtered_rows if not self._promotion_eligible(row)]
        promoted_rows_by_id = {str(row.get("post_id")): row for row in promotion_rows if row.get("post_id")}
        promoted_post_ids = list(promoted_rows_by_id)
        canonical_clusters = (
            await self.db.get_latest_canonical_clusters(limit=20, post_ids=promoted_post_ids)
            if promoted_post_ids
            else []
        )

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
            document.add_heading("Top pain clusters", level=1)
            document.add_paragraph("Canonical pain clusters prioritized by opportunity score and verified evidence.")
            self._render_cluster_section(document, canonical_clusters, promoted_rows_by_id=promoted_rows_by_id)

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

    def _render_cluster_section(
        self,
        document: Document,
        clusters: list[dict[str, Any]],
        *,
        promoted_rows_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        for rank, cluster in enumerate(clusters[:20], start=1):
            label = (str(cluster.get("label") or "Recurring pain cluster").strip() or "Recurring pain cluster")
            summary = (str(cluster.get("summary") or "No summary available.").strip() or "No summary available.")
            raw_examples = self._cluster_examples(cluster)
            eligible_examples, eligible_post_ids = self._eligible_cluster_examples(
                cluster,
                raw_examples,
                promoted_rows_by_id=promoted_rows_by_id,
            )
            if promoted_rows_by_id is not None and not eligible_examples:
                continue
            examples = eligible_examples if promoted_rows_by_id is not None else raw_examples
            eligible_count = len(eligible_post_ids) if promoted_rows_by_id is not None else int(
                cluster.get("verified_quote_count") or len(examples) or cluster.get("item_count") or 0
            )
            avg_score = self._cluster_avg_opportunity_score(cluster, examples)
            fresh_post_count = int(cluster.get("fresh_post_count") or 0)
            evergreen_post_count = int(cluster.get("evergreen_post_count") or 0)
            item_count = eligible_count or int(cluster.get("item_count") or fresh_post_count + evergreen_post_count or len(examples))
            incumbents = [str(item).strip() for item in cluster.get("incumbents") or [] if str(item).strip()]
            incumbents_text = ", ".join(incumbents[:4]) or "none"

            document.add_heading(f"#{rank} {label}", level=2)
            metrics = document.add_paragraph(
                f"Opportunity score {avg_score:.1f} | Confidence {self._cluster_confidence(cluster, examples):.2f} | "
                f"Intensity {self._cluster_intensity(cluster, examples):.1f}/10 | "
                f"WTP {self._cluster_wtp(cluster, examples, item_count=item_count):.1f}/10 | "
                f"Urgency {self._cluster_urgency(cluster, examples)} | "
                f"Buyer authority {self._cluster_buyer_authority(cluster, examples):.2f}"
            )
            metrics.style = "Intense Quote"
            signal = str(cluster.get("estimated_monetization_signal") or "unknown").strip().lower() or "unknown"
            count_label = self._eligible_verified_post_count_label(item_count)
            document.add_paragraph(f"Why it matters: {signal} monetization signal across {count_label}; {summary}")
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
                document.add_paragraph(
                    f"Coverage/confidence: Stability {stability:.2f} | Verified quotes {verified_quote_count} | "
                    f"Sources {independent_source_count} | Authors {quality_author_count} | "
                    f"Frequency {posts_frequency:.1f}/1k posts, {comments_frequency:.1f}/1k comments"
                )
            evidence_quotes = self._cluster_verified_quotes(examples)
            for quote, url in evidence_quotes[:3]:
                document.add_paragraph(f"Verified evidence: {quote}")
                if url:
                    document.add_paragraph(f"Link: {url}")
            personas = self._cluster_personas(examples)
            if personas:
                document.add_paragraph(f"Affected users/personas: {'; '.join(personas[:6])}")
            workarounds = self._cluster_text_values(examples, "current_workaround")
            if workarounds:
                document.add_paragraph(f"Current workarounds: {'; '.join(workarounds[:4])}")
            document.add_paragraph(f"Competitors/tools mentioned: {incumbents_text}")
            wedge = self._cluster_suggested_wedge(cluster, examples, personas=personas, workarounds=workarounds)
            if wedge:
                document.add_paragraph(f"Suggested wedge: {wedge}")
            risks = self._cluster_risks(cluster, examples, independent_source_count=independent_source_count)
            if risks:
                document.add_paragraph(f"Risks: {risks}")
            score_breakdown = self._cluster_score_breakdown(cluster, examples)
            if score_breakdown:
                document.add_paragraph(f"Score breakdown: {score_breakdown}")
            if examples:
                examples_header = document.add_paragraph()
                examples_header.add_run("Representative examples").bold = True
                for example in examples[:3]:
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

    @staticmethod
    def _cluster_examples(cluster: dict[str, Any]) -> list[dict[str, Any]]:
        raw = cluster.get("representative_examples") or []
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    @staticmethod
    def _cluster_post_ids(cluster: dict[str, Any], examples: list[dict[str, Any]]) -> list[str]:
        raw_post_ids = cluster.get("post_ids") or []
        if isinstance(raw_post_ids, str):
            raw_post_ids = [item for item in raw_post_ids.split(",") if item]
        if not isinstance(raw_post_ids, list):
            raw_post_ids = []
        seen: set[str] = set()
        post_ids: list[str] = []
        for raw in [*raw_post_ids, *(example.get("post_id") for example in examples)]:
            post_id = str(raw or "").strip()
            if post_id and post_id not in seen:
                seen.add(post_id)
                post_ids.append(post_id)
        return post_ids

    @classmethod
    def _eligible_cluster_examples(
        cls,
        cluster: dict[str, Any],
        examples: list[dict[str, Any]],
        *,
        promoted_rows_by_id: dict[str, dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if promoted_rows_by_id is None:
            return examples, cls._cluster_post_ids(cluster, examples)
        cluster_post_ids = cls._cluster_post_ids(cluster, examples)
        eligible_post_ids = [post_id for post_id in cluster_post_ids if post_id in promoted_rows_by_id]
        if not eligible_post_ids:
            return [], []
        examples_by_post_id = {
            str(example.get("post_id") or "").strip(): example
            for example in examples
            if str(example.get("post_id") or "").strip()
        }
        eligible_examples: list[dict[str, Any]] = []
        for post_id in eligible_post_ids:
            row_example = cls._row_cluster_example(promoted_rows_by_id[post_id])
            existing_example = examples_by_post_id.get(post_id, {})
            merged = dict(row_example)
            for key, value in existing_example.items():
                if value not in (None, "", [], {}):
                    merged[key] = value
            merged["post_id"] = post_id
            eligible_examples.append(merged)
        return eligible_examples, eligible_post_ids

    @classmethod
    def _row_cluster_example(cls, row: dict[str, Any]) -> dict[str, Any]:
        context = row.get("user_context")
        if not isinstance(context, dict):
            context = cls._json_object(row.get("user_context_json"))
        return {
            "post_id": str(row.get("post_id") or ""),
            "title": str(row.get("title") or "Untitled").strip() or "Untitled",
            "summary": str(row.get("summary") or "").strip(),
            "source": str(row.get("source") or "").strip(),
            "url": str(row.get("url") or "").strip(),
            "verified_quotes": [str(item.get("quote") or "").strip() for item in cls._verified_evidence(row)],
            "current_workaround": str(row.get("current_workaround") or "").strip(),
            "incumbent_failure": str(row.get("incumbent_failure") or "").strip(),
            "user_context": context,
            "pain_level": int(row.get("pain_level") or 0),
            "willingness_to_pay": int(row.get("willingness_to_pay") or 0),
            "opportunity_score": cls._row_opportunity_score(row),
            "intensity_score": cls._coerce_float(row.get("intensity_score"), default=0.0),
            "urgency": row.get("urgency") or "",
            "buyer_authority": str(row.get("buyer_authority") or "unknown").strip() or "unknown",
            "buyer_authority_score": cls._buyer_authority_score(row),
            "confidence": cls._coerce_float(row.get("confidence"), default=0.0),
            "evidence_quality": str(row.get("evidence_quality") or "").strip(),
            "score_components": cls._score_components(row),
        }

    @staticmethod
    def _json_object(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _eligible_verified_post_count_label(count: int) -> str:
        if count == 1:
            return "1 eligible verified post"
        return f"{count} eligible verified posts"

    @classmethod
    def _cluster_avg_opportunity_score(cls, cluster: dict[str, Any], examples: list[dict[str, Any]]) -> float:
        values = [cls._coerce_float(example.get("opportunity_score"), default=0.0) for example in examples]
        values = [value for value in values if value]
        if values:
            return sum(values) / len(values)
        return float(cluster.get("avg_opportunity_score") or 0.0)

    @staticmethod
    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _cluster_confidence(cls, cluster: dict[str, Any], examples: list[dict[str, Any]]) -> float:
        direct = cls._coerce_float(cluster.get("confidence"), default=-1.0)
        if direct >= 0.0:
            return max(0.0, min(1.0, direct))
        values = [cls._coerce_float(example.get("confidence"), default=0.0) for example in examples]
        return max(values, default=0.0)

    @classmethod
    def _cluster_intensity(cls, cluster: dict[str, Any], examples: list[dict[str, Any]]) -> float:
        direct = cls._coerce_float(cluster.get("intensity_score"), default=0.0)
        if direct:
            return direct * 10 if 0 < direct <= 1 else min(10.0, direct)
        values = []
        for example in examples:
            value = cls._coerce_float(example.get("intensity_score"), default=0.0)
            if value:
                values.append(value * 10 if 0 < value <= 1 else min(10.0, value))
            elif example.get("pain_level") is not None:
                values.append(min(10.0, cls._coerce_float(example.get("pain_level"), default=0.0)))
        return sum(values) / len(values) if values else 0.0

    @classmethod
    def _cluster_wtp(cls, cluster: dict[str, Any], examples: list[dict[str, Any]], *, item_count: int) -> float:
        values = [cls._coerce_float(example.get("willingness_to_pay"), default=0.0) for example in examples]
        values = [value for value in values if value]
        if values:
            return min(10.0, sum(values) / len(values))
        direct = cls._coerce_float(cluster.get("wtp_score"), default=0.0)
        if direct:
            return direct * 10 if 0 < direct <= 1 else min(10.0, direct)
        aggregate = cls._coerce_float(cluster.get("aggregate_wtp"), default=0.0)
        if aggregate and item_count > 0:
            return min(10.0, aggregate / item_count)
        return 0.0

    @classmethod
    def _cluster_urgency(cls, cluster: dict[str, Any], examples: list[dict[str, Any]]) -> str:
        direct = str(cluster.get("urgency") or "").strip()
        if direct:
            return direct
        for example in examples:
            urgency = example.get("urgency")
            if isinstance(urgency, (int, float)):
                if urgency >= 8:
                    return "high"
                if urgency >= 4:
                    return "medium"
                return "low"
            rendered = str(urgency or "").strip()
            if rendered and rendered.lower() != "none":
                return rendered
        return "unknown"

    @classmethod
    def _cluster_buyer_authority(cls, cluster: dict[str, Any], examples: list[dict[str, Any]]) -> float:
        direct = cls._coerce_float(cluster.get("median_buyer_authority"), default=0.0)
        if direct:
            return direct
        values = [cls._coerce_float(example.get("buyer_authority_score"), default=0.0) for example in examples]
        values = [value for value in values if value]
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _cluster_text_values(examples: list[dict[str, Any]], key: str) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for example in examples:
            raw = example.get(key)
            items = raw if isinstance(raw, list) else [raw]
            for item in items:
                text = str(item or "").strip()
                normalized = text.lower()
                if text and normalized not in seen:
                    seen.add(normalized)
                    values.append(text)
        return values

    @classmethod
    def _cluster_personas(cls, examples: list[dict[str, Any]]) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for example in examples:
            context = example.get("user_context")
            if not isinstance(context, dict):
                context = {}
            for key in ("persona", "role", "workflow", "industry", "company_size"):
                raw = context.get(key) if isinstance(context, dict) else None
                items = raw if isinstance(raw, list) else [raw]
                for item in items:
                    text = str(item or "").strip()
                    normalized = text.lower()
                    if text and normalized not in seen:
                        seen.add(normalized)
                        values.append(text)
        return values

    @classmethod
    def _cluster_verified_quotes(cls, examples: list[dict[str, Any]]) -> list[tuple[str, str]]:
        quotes: list[tuple[str, str]] = []
        seen: set[str] = set()
        for example in examples:
            url = str(example.get("url") or "").strip()
            raw_quotes = example.get("verified_quotes") or []
            if not isinstance(raw_quotes, list):
                raw_quotes = [raw_quotes]
            for raw_quote in raw_quotes:
                quote = str(raw_quote or "").strip()
                normalized = quote.lower()
                if quote and normalized not in seen:
                    seen.add(normalized)
                    quotes.append((quote, url))
        return quotes

    @classmethod
    def _cluster_suggested_wedge(
        cls,
        cluster: dict[str, Any],
        examples: list[dict[str, Any]],
        *,
        personas: list[str],
        workarounds: list[str],
    ) -> str:
        explicit = str(cluster.get("suggested_wedge") or "").strip()
        if explicit:
            return explicit
        workaround = workarounds[0] if workarounds else "the current manual workflow"
        persona = personas[0] if personas else "the affected operator"
        return f"Replace {workaround} with an auditable workflow focused on {persona}."

    @classmethod
    def _cluster_risks(
        cls,
        cluster: dict[str, Any],
        examples: list[dict[str, Any]],
        *,
        independent_source_count: int,
    ) -> str:
        explicit = cluster.get("risks")
        if isinstance(explicit, list):
            rendered = "; ".join(str(item).strip() for item in explicit if str(item).strip())
            if rendered:
                return rendered
        explicit_text = str(explicit or "").strip()
        if explicit_text:
            return explicit_text
        failures = cls._cluster_text_values(examples, "incumbent_failure")
        if failures:
            return (
                f"Validate that {failures[0]} is painful across more than "
                f"{max(1, independent_source_count)} independent sources."
            )
        return "Watch for thin evidence, narrow buyer context, or unstable clustering before outreach."

    @classmethod
    def _cluster_score_breakdown(cls, cluster: dict[str, Any], examples: list[dict[str, Any]]) -> str:
        components = cluster.get("score_components")
        if not isinstance(components, dict):
            for example in examples:
                candidate = example.get("score_components")
                if isinstance(candidate, dict) and candidate:
                    components = candidate
                    break
        if not isinstance(components, dict) or not components:
            return ""
        parts: list[str] = []
        for section_name in ("factors", "penalties"):
            values = components.get(section_name)
            if not isinstance(values, dict) or not values:
                continue
            rendered_values = []
            for key, value in values.items():
                if isinstance(value, (int, float)):
                    rendered_values.append(f"{key}={float(value):.2f}")
                else:
                    rendered_values.append(f"{key}={value}")
            if rendered_values:
                parts.append(f"{section_name} {', '.join(rendered_values)}")
        return "; ".join(parts)

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
