from __future__ import annotations

import html
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from digest_delivery import DailyDigestDocumentService


@dataclass
class ResearchReportResult:
    html_path: str | None
    total_items: int
    top_opportunity_count: int
    cluster_count: int
    weak_signal_count: int
    coverage_run_count: int


class ResearchReportBuilder:
    """Build a local static HTML research report from already-persisted evidence.

    The report is intentionally static: no external services, no JavaScript runtime,
    and no SaaS/dashboard server. Promotion-sensitive sections reuse the same
    evidence-first eligibility helpers as the `.docx` digest.
    """

    def __init__(self, *, db, reports_dir: str):
        self.db = db
        self.reports_dir = reports_dir

    async def build_report(self, *, hours: int = 24, limit: int = 1000) -> ResearchReportResult:
        rows = await self.db.get_recent_pain_points(hours=hours, limit=limit)
        coverage_runs = await self._list_source_coverage_runs()
        promoted_rows = [row for row in rows if self._promotion_eligible(row)]
        weak_rows = [row for row in rows if not self._promotion_eligible(row)]
        promoted_rows_by_id = {str(row.get("post_id")): row for row in promoted_rows if row.get("post_id")}
        promoted_post_ids = list(promoted_rows_by_id)
        clusters = (
            await self.db.get_latest_canonical_clusters(limit=50, post_ids=promoted_post_ids)
            if promoted_post_ids
            else []
        )
        renderable_clusters = self._renderable_clusters(clusters, promoted_rows_by_id=promoted_rows_by_id)

        top_opportunities = self._sort_rows(promoted_rows)[:20]
        high_wtp_rows = [row for row in top_opportunities if self._coerce_float(row.get("willingness_to_pay")) >= 8]
        feature_request_rows = [row for row in top_opportunities if self._is_feature_request(row)]
        competitor_groups = self._competitor_failure_groups(top_opportunities)

        html_body = self._render_html(
            hours=hours,
            rows=rows,
            promoted_rows=promoted_rows,
            weak_rows=weak_rows,
            clusters=renderable_clusters,
            top_opportunities=top_opportunities,
            high_wtp_rows=high_wtp_rows,
            feature_request_rows=feature_request_rows,
            competitor_groups=competitor_groups,
            coverage_runs=coverage_runs,
        )
        os.makedirs(self.reports_dir, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        final_path = os.path.join(self.reports_dir, f"research_report_{timestamp}.html")
        tmp_path = f"{final_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(html_body)
        os.replace(tmp_path, final_path)
        return ResearchReportResult(
            html_path=final_path,
            total_items=len(rows),
            top_opportunity_count=len(top_opportunities),
            cluster_count=len(renderable_clusters),
            weak_signal_count=len(weak_rows),
            coverage_run_count=len(coverage_runs),
        )

    async def _list_source_coverage_runs(self) -> list[dict[str, Any]]:
        if not hasattr(self.db, "list_source_coverage_runs"):
            return []
        try:
            runs = await self.db.list_source_coverage_runs(limit=10)
        except TypeError:
            return []
        return [dict(run) for run in runs if isinstance(run, dict)]

    def _render_html(
        self,
        *,
        hours: int,
        rows: list[dict[str, Any]],
        promoted_rows: list[dict[str, Any]],
        weak_rows: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        top_opportunities: list[dict[str, Any]],
        high_wtp_rows: list[dict[str, Any]],
        feature_request_rows: list[dict[str, Any]],
        competitor_groups: list[tuple[str, list[dict[str, Any]]]],
        coverage_runs: list[dict[str, Any]],
    ) -> str:
        generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        sections = [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>Pain Finder Research Report</title>",
            f"<style>{self._css()}</style>",
            "</head>",
            "<body>",
            "<main>",
            "<header class=\"hero\">",
            "<p class=\"eyebrow\">Local static report</p>",
            "<h1>Pain Finder Research Report</h1>",
            f"<p>Generated {self._e(generated)} · Window: last {int(hours)}h · Total rows: {len(rows)} · Verified opportunities: {len(promoted_rows)} · Weak/review rows: {len(weak_rows)}</p>",
            "</header>",
            self._render_filter_panel(rows),
            self._render_cluster_section(clusters),
            self._render_top_opportunities(top_opportunities),
            self._render_competitor_failures(competitor_groups),
            self._render_unmet_feature_requests(feature_request_rows),
            self._render_high_wtp(high_wtp_rows),
            self._render_weak_signals(weak_rows),
            self._render_rejected_noise(weak_rows),
            self._render_coverage(coverage_runs, rows=rows, promoted_rows=promoted_rows, weak_rows=weak_rows),
            "</main>",
            "</body>",
            "</html>",
        ]
        return "\n".join(section for section in sections if section)

    def _render_filter_panel(self, rows: list[dict[str, Any]]) -> str:
        filters = [
            ("Source", self._unique(row.get("source") for row in rows)),
            ("Subreddit/source", self._unique(row.get("subreddit") or row.get("source") for row in rows)),
            ("Time range", ["last report window"]),
            ("Pain type", self._unique(row.get("pain_type") for row in rows)),
            ("Industry/persona", self._unique(row.get("niche_category") for row in rows)),
            ("Intensity", self._bucket_values(row.get("intensity_score") or row.get("pain_level") for row in rows)),
            ("WTP", self._bucket_values(row.get("willingness_to_pay") for row in rows)),
            ("Urgency", self._unique(row.get("urgency") for row in rows)),
            ("Confidence", self._bucket_values(row.get("confidence") for row in rows)),
            ("First-hand only", ["first_hand", "other"]),
            ("Buyer authority", self._unique(row.get("buyer_authority") for row in rows)),
            ("Competitor/tool", self._unique(tag for row in rows for tag in self._tags(row.get("competitor_tags")))),
            ("Opportunity bucket", self._unique(row.get("opportunity_bucket") for row in rows)),
            ("Evidence quality", self._unique(row.get("evidence_quality") for row in rows)),
        ]
        chips = []
        for label, values in filters:
            value_text = ", ".join(self._e(value) for value in values[:8]) or "none"
            chips.append(f"<div class=\"filter\"><strong>{self._e(label)}</strong><span>{value_text}</span></div>")
        return "<section class=\"filters\"><h2>Filters</h2><p>Static filter dimensions encoded on cards for local review/export.</p><div class=\"filter-grid\">" + "".join(chips) + "</div></section>"

    def _render_cluster_section(self, clusters: list[dict[str, Any]]) -> str:
        cards = []
        for rank, cluster in enumerate(clusters[:20], start=1):
            label = self._text(cluster.get("label"), "Recurring pain cluster")
            summary = self._text(cluster.get("summary"), "No summary available.")
            examples = cluster.get("eligible_examples") if isinstance(cluster.get("eligible_examples"), list) else []
            quotes = self._cluster_quotes(examples)
            quote_items = "".join(f"<li>{self._e(quote)}</li>" for quote in quotes[:3]) or "<li>No verified quote snippet available.</li>"
            incumbents = ", ".join(self._e(tag) for tag in self._tags(cluster.get("incumbents"))) or "none"
            personas = "; ".join(self._e(value) for value in self._cluster_personas(examples)[:5]) or "unknown"
            workarounds = "; ".join(self._e(value) for value in self._cluster_text_values(examples, "current_workaround")[:4]) or "not captured"
            failures = "; ".join(self._e(value) for value in self._cluster_text_values(examples, "incumbent_failure")[:4]) or "not captured"
            score = self._cluster_score(cluster, examples)
            confidence = self._avg([self._coerce_float(example.get("confidence")) for example in examples])
            stability = self._coerce_float(cluster.get("cluster_stability_score"))
            sources = int(self._coerce_float(cluster.get("independent_source_count")))
            authors = int(self._coerce_float(cluster.get("unique_author_count") or cluster.get("unique_authors_count")))
            posts_freq = self._coerce_float(cluster.get("pain_mentions_per_1000_posts"))
            comments_freq = self._coerce_float(cluster.get("pain_mentions_per_1000_comments"))
            cards.append(
                "<article class=\"card cluster-card\">"
                f"<h3>#{rank} {self._e(label)}</h3>"
                f"<p class=\"metric\">Opportunity score {score:.1f} · Confidence {confidence:.2f} · Stability {stability:.2f}</p>"
                f"<p><strong>Why it matters:</strong> {self._e(summary)}</p>"
                f"<p><strong>Coverage/confidence:</strong> Verified quotes {int(self._coerce_float(cluster.get('verified_quote_count')))} · Sources {sources} · Authors {authors} · Frequency {posts_freq:.1f}/1k posts, {comments_freq:.1f}/1k comments</p>"
                f"<p><strong>Affected users/personas:</strong> {personas}</p>"
                f"<p><strong>Current workarounds:</strong> {workarounds}</p>"
                f"<p><strong>Competitors/tools mentioned:</strong> {incumbents}</p>"
                f"<p><strong>Incumbent failure:</strong> {failures}</p>"
                f"<ul class=\"quotes\">{quote_items}</ul>"
                "</article>"
            )
        empty = "<p class=\"empty\">No verified trending clusters in this window.</p>" if not cards else ""
        return "<section id=\"trending-pains\"><h2>Trending pains</h2>" + empty + "".join(cards) + "</section>"

    def _render_top_opportunities(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return '<section id="top-opportunities"><h2>Top opportunities</h2><p class="empty">No verified opportunities in this window.</p></section>'
        return "<section id=\"top-opportunities\"><h2>Top opportunities</h2>" + "".join(
            self._render_row_card(row, badge="verified") for row in rows[:20]
        ) + "</section>"

    def _render_competitor_failures(self, groups: list[tuple[str, list[dict[str, Any]]]]) -> str:
        if not groups:
            return '<section id="competitor-failures"><h2>Competitor failures</h2><p class="empty">No verified competitor/tool failure clusters in this window.</p></section>'
        cards = []
        for tool, rows in groups[:12]:
            failures = self._unique(row.get("incumbent_failure") for row in rows)
            quotes = [quote for row in rows for quote in self._row_quotes(row)]
            cards.append(
                "<article class=\"card\">"
                f"<h3>{self._e(tool)}</h3>"
                f"<p>{len(rows)} verified mention(s)</p>"
                f"<p><strong>Failure pattern:</strong> {self._e('; '.join(failures[:3]) or 'not captured')}</p>"
                f"<ul class=\"quotes\">{''.join(f'<li>{self._e(quote)}</li>' for quote in quotes[:2])}</ul>"
                "</article>"
            )
        return '<section id="competitor-failures"><h2>Competitor failures</h2>' + "".join(cards) + "</section>"

    def _render_unmet_feature_requests(self, rows: list[dict[str, Any]]) -> str:
        return self._render_row_section(
            "unmet-feature-requests",
            "Unmet feature requests",
            rows,
            empty="No verified unmet feature requests in this window.",
            badge="feature request",
        )

    def _render_high_wtp(self, rows: list[dict[str, Any]]) -> str:
        return self._render_row_section(
            "high-wtp-signals",
            "High-WTP signals",
            rows,
            empty="No verified high-WTP signals in this window.",
            badge="high WTP",
        )

    def _render_weak_signals(self, rows: list[dict[str, Any]]) -> str:
        return self._render_row_section(
            "weak-signals",
            "Weak signals to watch",
            self._sort_rows(rows)[:20],
            empty="No weak signals in this window.",
            badge="needs review",
            include_rejection=True,
        )

    def _render_rejected_noise(self, rows: list[dict[str, Any]]) -> str:
        bounded = [row for row in self._sort_rows(rows) if self._evidence_rejection_reason(row)][:12]
        return self._render_row_section(
            "rejected-noise",
            "Rejected/noise examples",
            bounded,
            empty="No rejected/noise examples in this window.",
            badge="rejected",
            include_rejection=True,
        )

    def _render_coverage(
        self,
        coverage_runs: list[dict[str, Any]],
        *,
        rows: list[dict[str, Any]],
        promoted_rows: list[dict[str, Any]],
        weak_rows: list[dict[str, Any]],
    ) -> str:
        summary = (
            f"<p>Rows reviewed: {len(rows)} · Verified opportunities: {len(promoted_rows)} · Weak/review rows: {len(weak_rows)}</p>"
        )
        if not coverage_runs:
            return '<section id="coverage"><h2>Coverage and confidence report</h2>' + summary + '<p class="empty">No source coverage runs recorded.</p></section>'
        cards = []
        for run in coverage_runs[:10]:
            cards.append(
                "<article class=\"card compact\">"
                f"<h3>{self._e(run.get('source') or 'unknown')} · {self._e(run.get('scope') or 'all')}</h3>"
                f"<p>Fetched posts: {int(self._coerce_float(run.get('fetched_posts')))} · Fetched comments: {int(self._coerce_float(run.get('fetched_comments')))} · Failed requests: {int(self._coerce_float(run.get('failed_requests')))}</p>"
                f"<p>Skipped deleted: {int(self._coerce_float(run.get('skipped_deleted')))} · Skipped duplicates: {int(self._coerce_float(run.get('skipped_duplicates')))} · Source method: {self._e(run.get('source_method_used') or 'unknown')}</p>"
                "</article>"
            )
        return '<section id="coverage"><h2>Coverage and confidence report</h2>' + summary + "".join(cards) + "</section>"

    def _render_row_section(
        self,
        section_id: str,
        title: str,
        rows: list[dict[str, Any]],
        *,
        empty: str,
        badge: str,
        include_rejection: bool = False,
    ) -> str:
        if not rows:
            return f'<section id="{self._e(section_id)}"><h2>{self._e(title)}</h2><p class="empty">{self._e(empty)}</p></section>'
        return f'<section id="{self._e(section_id)}"><h2>{self._e(title)}</h2>' + "".join(
            self._render_row_card(row, badge=badge, include_rejection=include_rejection) for row in rows
        ) + "</section>"

    def _render_row_card(self, row: dict[str, Any], *, badge: str, include_rejection: bool = False) -> str:
        title = self._text(row.get("title"), "Untitled pain signal")
        summary = self._text(row.get("summary") or row.get("deep_dive_summary"), "No summary available.")
        metrics = (
            f"Score {self._coerce_float(row.get('opportunity_score')):.1f} · "
            f"Pain {self._coerce_float(row.get('pain_level')):.1f}/10 · "
            f"WTP {self._coerce_float(row.get('willingness_to_pay')):.1f}/10 · "
            f"Confidence {self._coerce_float(row.get('confidence')):.2f}"
        )
        quotes = self._row_quotes(row)
        quote_html = "".join(f"<li>{self._e(quote)}</li>" for quote in quotes[:3])
        rejection = self._evidence_rejection_reason(row) if include_rejection else ""
        rejection_html = f"<p><strong>Evidence rejection: {self._e(rejection)}</strong></p>" if rejection else ""
        link = self._safe_href(row.get("url"))
        link_html = f'<p><a href="{self._e(link)}">Source link</a></p>' if link else ""
        attrs = self._row_filter_attrs(row)
        return (
            f"<article class=\"card row-card\" {attrs}>"
            f"<p class=\"badge\">{self._e(badge)}</p>"
            f"<h3>{self._e(title)}</h3>"
            f"<p class=\"metric\">{self._e(metrics)}</p>"
            f"<p>{self._e(summary)}</p>"
            f"<p><strong>Workaround:</strong> {self._e(row.get('current_workaround') or 'not captured')}</p>"
            f"<p><strong>Incumbent failure:</strong> {self._e(row.get('incumbent_failure') or 'not captured')}</p>"
            f"<p><strong>Evidence quality:</strong> {self._e(row.get('evidence_quality') or 'unknown')}</p>"
            f"<ul class=\"quotes\">{quote_html}</ul>"
            f"{rejection_html}{link_html}"
            "</article>"
        )

    def _renderable_clusters(
        self,
        clusters: list[dict[str, Any]],
        *,
        promoted_rows_by_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        renderable: list[dict[str, Any]] = []
        for cluster in clusters:
            post_ids = {str(item) for item in cluster.get("post_ids") or [] if str(item).strip()}
            raw_examples = [item for item in cluster.get("representative_examples") or [] if isinstance(item, dict)]
            eligible_examples = [
                example
                for example in raw_examples
                if str(example.get("post_id") or "") in promoted_rows_by_id
            ]
            if not eligible_examples:
                eligible_examples = [
                    self._row_as_example(promoted_rows_by_id[post_id])
                    for post_id in post_ids
                    if post_id in promoted_rows_by_id
                ]
            if not eligible_examples:
                continue
            copy = dict(cluster)
            copy["eligible_examples"] = eligible_examples
            renderable.append(copy)
        return sorted(renderable, key=lambda item: self._cluster_score(item, item.get("eligible_examples") or []), reverse=True)

    def _row_as_example(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "post_id": row.get("post_id"),
            "title": row.get("title"),
            "source": row.get("source"),
            "url": row.get("url"),
            "summary": row.get("summary"),
            "verified_quotes": self._row_quotes(row),
            "current_workaround": row.get("current_workaround"),
            "incumbent_failure": row.get("incumbent_failure"),
            "pain_level": row.get("pain_level"),
            "willingness_to_pay": row.get("willingness_to_pay"),
            "confidence": row.get("confidence"),
            "user_context": self._json_object(row.get("user_context") or row.get("user_context_json")),
        }

    def _row_filter_attrs(self, row: dict[str, Any]) -> str:
        competitors = ",".join(self._tags(row.get("competitor_tags")))
        attrs = {
            "source": row.get("source"),
            "subreddit": row.get("subreddit") or row.get("source"),
            "pain-type": row.get("pain_type"),
            "industry-persona": row.get("niche_category"),
            "intensity": row.get("intensity_score") or row.get("pain_level"),
            "wtp": row.get("willingness_to_pay"),
            "urgency": row.get("urgency"),
            "confidence": row.get("confidence"),
            "first-hand": str(row.get("first_handness") or "").lower() == "first_hand",
            "buyer-authority": row.get("buyer_authority"),
            "competitor": competitors,
            "bucket": row.get("opportunity_bucket"),
            "evidence-quality": row.get("evidence_quality"),
        }
        return " ".join(f'data-{name}=\"{self._e(value)}\"' for name, value in attrs.items())

    def _competitor_failure_groups(self, rows: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if not str(row.get("incumbent_failure") or "").strip():
                continue
            for tag in self._tags(row.get("competitor_tags")):
                grouped[tag].append(row)
        return sorted(grouped.items(), key=lambda item: (len(item[1]), self._avg([self._coerce_float(row.get("opportunity_score")) for row in item[1]])), reverse=True)

    @staticmethod
    def _promotion_eligible(row: dict[str, Any]) -> bool:
        return DailyDigestDocumentService._promotion_eligible(row)

    @staticmethod
    def _evidence_rejection_reason(row: dict[str, Any]) -> str:
        return DailyDigestDocumentService._evidence_rejection_reason(row)

    @staticmethod
    def _verified_evidence(row: dict[str, Any]) -> list[dict[str, Any]]:
        return DailyDigestDocumentService._verified_evidence(row)

    def _row_quotes(self, row: dict[str, Any]) -> list[str]:
        return [str(item.get("quote") or "").strip() for item in self._verified_evidence(row) if str(item.get("match_type") or "").lower() == "exact" and str(item.get("quote") or "").strip()]

    def _cluster_quotes(self, examples: list[dict[str, Any]]) -> list[str]:
        quotes: list[str] = []
        for example in examples:
            raw = example.get("verified_quotes") or []
            if isinstance(raw, str):
                raw = [raw]
            if isinstance(raw, list):
                quotes.extend(str(item).strip() for item in raw if str(item).strip())
        return self._unique(quotes)

    def _cluster_score(self, cluster: dict[str, Any], examples: list[dict[str, Any]]) -> float:
        direct = self._coerce_float(cluster.get("avg_opportunity_score") or cluster.get("opportunity_score"))
        if direct:
            return direct
        values = [self._coerce_float(example.get("opportunity_score")) for example in examples]
        return self._avg(values)

    def _cluster_personas(self, examples: list[dict[str, Any]]) -> list[str]:
        values: list[str] = []
        for example in examples:
            context = example.get("user_context")
            if not isinstance(context, dict):
                context = self._json_object(context)
            for key in ("persona", "workflow", "industry", "segment"):
                value = str(context.get(key) or "").strip()
                if value:
                    values.append(value)
        return self._unique(values)

    def _cluster_text_values(self, examples: list[dict[str, Any]], field: str) -> list[str]:
        return self._unique(example.get(field) for example in examples)

    def _is_feature_request(self, row: dict[str, Any]) -> bool:
        haystack = " ".join(
            str(row.get(key) or "").lower()
            for key in ("category", "pain_type", "expression_type", "opportunity_type", "title", "summary")
        )
        return any(token in haystack for token in ("feature", "request", "missing", "wish"))

    def _sort_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            rows,
            key=lambda row: (
                self._coerce_float(row.get("opportunity_score")),
                self._coerce_float(row.get("willingness_to_pay")),
                self._coerce_float(row.get("pain_level")),
            ),
            reverse=True,
        )

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _tags(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = [part.strip() for part in value.split(",")]
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            if parsed:
                return [str(parsed).strip()]
        return []

    @staticmethod
    def _unique(values: Any) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _bucket_values(self, values: Any) -> list[str]:
        buckets: set[str] = set()
        for value in values:
            number = self._coerce_float(value)
            if number <= 0:
                continue
            if 0 < number <= 1:
                number *= 10
            if number >= 8:
                buckets.add("high")
            elif number >= 5:
                buckets.add("medium")
            else:
                buckets.add("low")
        return [bucket for bucket in ("high", "medium", "low") if bucket in buckets]

    @staticmethod
    def _coerce_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _avg(values: list[float]) -> float:
        nonzero = [value for value in values if value]
        return sum(nonzero) / len(nonzero) if nonzero else 0.0

    @staticmethod
    def _text(value: Any, fallback: str) -> str:
        text = str(value or "").strip()
        return text or fallback

    @staticmethod
    def _safe_href(value: Any) -> str:
        text = str(value or "").strip()
        if text.startswith(("https://", "http://")):
            return text
        return ""

    @staticmethod
    def _e(value: Any) -> str:
        return html.escape(str(value or ""), quote=True)

    @staticmethod
    def _css() -> str:
        return """
:root { color-scheme: light; --bg: #f7f7fb; --card: #ffffff; --ink: #202334; --muted: #5f667a; --accent: #3f5efb; --border: #dde1ee; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 32px 18px 64px; }
.hero { background: linear-gradient(135deg, #19213f, #3f5efb); color: white; border-radius: 20px; padding: 28px; box-shadow: 0 18px 50px rgba(32, 35, 52, .16); }
.eyebrow { text-transform: uppercase; letter-spacing: .12em; font-size: 12px; opacity: .78; }
h1, h2, h3 { line-height: 1.15; margin: 0 0 12px; }
section { margin-top: 28px; }
.card, .filters { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 18px; margin: 14px 0; box-shadow: 0 8px 24px rgba(32, 35, 52, .05); }
.cluster-card { border-left: 6px solid var(--accent); }
.compact { margin: 10px 0; }
.metric, .empty, .filter span { color: var(--muted); }
.badge { display: inline-block; margin: 0 0 8px; padding: 3px 9px; border-radius: 999px; background: #edf0ff; color: #2f42c3; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.filter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }
.filter { border: 1px solid var(--border); border-radius: 12px; padding: 10px; }
.filter strong, .filter span { display: block; }
ul.quotes { padding-left: 20px; }
a { color: var(--accent); }
""".strip()
