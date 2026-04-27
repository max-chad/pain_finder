from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

PROMOTION_BUYER_AUTHORITY_MIN_SCORE = 0.82

FAILURE_SIGNAL_LABELS: dict[str, str] = {
    "pricing_pain": "Pricing pain",
    "missing_feature": "Missing feature",
    "lock_in_switching_churn": "Switching/lock-in/churn",
    "reliability_support_failure": "Reliability/support failure",
    "workaround": "Workaround",
    "alternative_tool_mentions": "Alternative-tool mentions",
}

FAILURE_SIGNAL_ORDER = list(FAILURE_SIGNAL_LABELS)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class CompetitorClusterLink:
    label: str
    anchor: str


@dataclass
class CompetitorFailureGroup:
    tool: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    signal_counts: Counter[str] = field(default_factory=Counter)
    quotes: list[str] = field(default_factory=list)
    clusters: list[CompetitorClusterLink] = field(default_factory=list)
    avg_opportunity_score: float = 0.0

    @property
    def mention_count(self) -> int:
        return len(self.rows)

    def rendered_signal_counts(self) -> list[str]:
        return [
            f"{FAILURE_SIGNAL_LABELS[key]} ({int(self.signal_counts[key])})"
            for key in FAILURE_SIGNAL_ORDER
            if self.signal_counts.get(key, 0) > 0
        ]


def build_competitor_failure_radar(
    rows: list[dict[str, Any]],
    clusters: list[dict[str, Any]] | None = None,
    *,
    is_promotion_eligible: Callable[[dict[str, Any]], bool] | None = None,
) -> list[CompetitorFailureGroup]:
    eligible_rows = [
        row
        for row in rows
        if (is_promotion_eligible(row) if is_promotion_eligible is not None else is_radar_promotion_candidate(row))
        and exact_quotes(row)
    ]
    cluster_links_by_post_id = _cluster_links_by_post_id(clusters or [])
    grouped: dict[str, CompetitorFailureGroup] = defaultdict(CompetitorFailureGroup)
    seen_rows_by_tool: dict[str, set[str]] = defaultdict(set)
    seen_quotes_by_tool: dict[str, set[str]] = defaultdict(set)
    seen_clusters_by_tool: dict[str, set[str]] = defaultdict(set)

    for row in eligible_rows:
        post_id = str(row.get("post_id") or "").strip()
        tags = _failure_group_tags(row)
        if not tags:
            continue
        for tool in tags:
            signals = failure_signals_for_row(row, primary_tool=tool)
            if not signals:
                continue
            group = grouped[tool]
            group.tool = tool
            if post_id and post_id not in seen_rows_by_tool[tool]:
                group.rows.append(row)
                seen_rows_by_tool[tool].add(post_id)
            group.signal_counts.update(signals)
            for quote in exact_quotes(row):
                normalized_quote = quote.lower()
                if normalized_quote not in seen_quotes_by_tool[tool]:
                    seen_quotes_by_tool[tool].add(normalized_quote)
                    group.quotes.append(quote)
            for link in cluster_links_by_post_id.get(post_id, []):
                if link.anchor not in seen_clusters_by_tool[tool]:
                    seen_clusters_by_tool[tool].add(link.anchor)
                    group.clusters.append(link)

    for group in grouped.values():
        scores = [_coerce_float(row.get("opportunity_score")) for row in group.rows]
        nonzero_scores = [score for score in scores if score > 0]
        group.avg_opportunity_score = sum(nonzero_scores) / len(nonzero_scores) if nonzero_scores else 0.0

    return sorted(
        grouped.values(),
        key=lambda group: (-group.mention_count, -group.avg_opportunity_score, group.tool),
    )


def failure_signals_for_row(row: dict[str, Any], *, primary_tool: str | None = None) -> list[str]:
    haystack = _row_haystack(row)
    tags = parse_tags(row.get("competitor_tags"))
    comment_mentions = parse_tags(row.get("comment_tool_mentions") or row.get("comment_tool_mentions_json"))
    primary = str(primary_tool or "").strip().lower()
    signals: list[str] = []

    if _contains_any(haystack, ["price", "pricing", "cost", "expensive", "renewal", "billing", "license", "doubled"]):
        signals.append("pricing_pain")
    if _contains_any(haystack, ["missing", "lacks", "lack ", "no ", "feature", "does not support", "approval routing"]):
        signals.append("missing_feature")
    if _contains_any(haystack, ["lock-in", "lock in", "locked", "switch", "switching", "churn", "migrate", "cannot export", "can't export", "contract"]):
        signals.append("lock_in_switching_churn")
    if _contains_any(haystack, ["support", "stalling", "reliability", "failure", "fails", "failing", "broken", "bug", "outage", "timeout", "down"]):
        signals.append("reliability_support_failure")
    if _has_workaround(row, haystack):
        signals.append("workaround")
    if _has_alternative_tool(tags=tags, comment_mentions=comment_mentions, primary_tool=primary):
        signals.append("alternative_tool_mentions")

    return [key for key in FAILURE_SIGNAL_ORDER if key in set(signals)]


def exact_quotes(row: dict[str, Any]) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()
    for item in _verified_evidence(row):
        if str(item.get("match_type") or "").strip().lower() != "exact":
            continue
        quote = str(item.get("quote") or "").strip()
        if not quote:
            continue
        normalized = quote.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        quotes.append(quote)
    return quotes


def is_radar_promotion_candidate(row: dict[str, Any]) -> bool:
    score_components = _score_components(row)
    if str(score_components.get("evidence_rejection_reason") or "").strip():
        return False
    if score_components.get("promotion_eligible") is False:
        return False
    if not exact_quotes(row):
        return False
    if _coerce_bool(row.get("needs_human_review")):
        return False
    first_handness = str(row.get("first_handness") or "unknown").strip().lower()
    authority_score = _coerce_float(row.get("buyer_authority_score"))
    if authority_score <= 0:
        authority = str(row.get("buyer_authority") or "unknown").strip().lower()
        authority_score = {
            "manager": 0.82,
            "head_of_ops": 0.94,
            "founder_owner": 1.0,
            "agency_operator": 0.88,
        }.get(authority, 0.55)
    return first_handness == "first_hand" or authority_score >= PROMOTION_BUYER_AUTHORITY_MIN_SCORE


def parse_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = [part.strip() for part in raw.split(",")]
        items = parsed if isinstance(parsed, list) else [parsed]
    else:
        items = []

    tags: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = str(item or "").strip().lower()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def cluster_anchor(label: Any) -> str:
    text = str(label or "recurring-pain-cluster").strip().lower()
    slug = _SLUG_RE.sub("-", text).strip("-")
    return f"cluster-{slug or 'recurring-pain-cluster'}"


def _failure_group_tags(row: dict[str, Any]) -> list[str]:
    """Return tags that should own the failure, not mere workaround alternatives."""
    tags = parse_tags(row.get("competitor_tags"))
    if len(tags) <= 1:
        return tags

    incumbent_failure = str(row.get("incumbent_failure") or "").strip().lower()
    matched = [tag for tag in tags if _tool_name_in_text(tag, incumbent_failure)]
    if matched:
        return matched

    failure_context = " ".join(
        str(row.get(field) or "")
        for field in ("title", "summary", "deep_dive_summary", "pain_type", "expression_type", "opportunity_type")
    ).lower()
    matched = [tag for tag in tags if _tool_name_in_text(tag, failure_context)]
    return matched or tags


def _tool_name_in_text(tag: str, text: str) -> bool:
    tag = str(tag or "").strip().lower()
    text = str(text or "").lower()
    if not tag or not text:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(tag)}(?![a-z0-9])", text) is not None


def _cluster_links_by_post_id(clusters: list[dict[str, Any]]) -> dict[str, list[CompetitorClusterLink]]:
    links: dict[str, list[CompetitorClusterLink]] = defaultdict(list)
    for cluster in clusters:
        label = str(cluster.get("label") or "Recurring pain cluster").strip() or "Recurring pain cluster"
        link = CompetitorClusterLink(label=label, anchor=cluster_anchor(label))
        post_ids = {str(item).strip() for item in cluster.get("post_ids") or [] if str(item).strip()}
        for example in cluster.get("eligible_examples") or cluster.get("representative_examples") or []:
            if isinstance(example, dict) and str(example.get("post_id") or "").strip():
                post_ids.add(str(example.get("post_id")).strip())
        for post_id in post_ids:
            links[post_id].append(link)
    return links


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
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


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


def _row_haystack(row: dict[str, Any]) -> str:
    fields = [
        "title",
        "summary",
        "deep_dive_summary",
        "pain_type",
        "expression_type",
        "opportunity_type",
        "current_workaround",
        "incumbent_failure",
    ]
    return " ".join(str(row.get(field) or "") for field in fields).lower()


def _contains_any(haystack: str, needles: list[str]) -> bool:
    return any(needle in haystack for needle in needles)


def _has_workaround(row: dict[str, Any], haystack: str) -> bool:
    workaround = str(row.get("current_workaround") or "").strip().lower()
    if workaround and workaround not in {"unknown", "none", "not captured", "n/a"}:
        return True
    return _contains_any(haystack, ["workaround", "manual", "spreadsheet", "csv", "zapier"])


def _has_alternative_tool(*, tags: list[str], comment_mentions: list[str], primary_tool: str) -> bool:
    if primary_tool:
        return any(tag != primary_tool for tag in tags) or any(tag != primary_tool for tag in comment_mentions)
    return len(tags) > 1 or bool(comment_mentions)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
