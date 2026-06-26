from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

FAILURE_SIGNAL_LABELS: dict[str, str] = {
    "pricing_pain": "Pricing pain",
    "missing_feature": "Missing feature",
    "lock_in_switching_churn": "Switching/lock-in/churn",
    "reliability_support_failure": "Reliability/support failure",
    "workaround": "Workaround",
    "alternative_tool_mentions": "Alternative-tool mentions",
}
FAILURE_SIGNAL_ORDER = list(FAILURE_SIGNAL_LABELS)
PROMOTION_BUYER_AUTHORITY_MIN_SCORE = 0.82


@dataclass
class CompetitorFailureGroup:
    tool: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    signal_counts: Counter[str] = field(default_factory=Counter)
    quotes: list[str] = field(default_factory=list)
    avg_opportunity_score: float = 0.0

    @property
    def mention_count(self) -> int:
        return len(self.rows)

    def rendered_signal_counts(self) -> list[str]:
        return [f"{FAILURE_SIGNAL_LABELS[key]} ({int(self.signal_counts[key])})" for key in FAILURE_SIGNAL_ORDER if self.signal_counts.get(key)]


def build_competitor_failure_radar(
    rows: list[dict[str, Any]],
    *,
    is_promotion_eligible: Callable[[dict[str, Any]], bool] | None = None,
) -> list[CompetitorFailureGroup]:
    eligible_rows = [
        row
        for row in rows
        if (is_promotion_eligible(row) if is_promotion_eligible is not None else is_radar_promotion_candidate(row))
        and exact_quotes(row)
    ]
    grouped: dict[str, CompetitorFailureGroup] = defaultdict(CompetitorFailureGroup)
    seen_rows_by_tool: dict[str, set[str]] = defaultdict(set)
    seen_quotes_by_tool: dict[str, set[str]] = defaultdict(set)
    for row in eligible_rows:
        post_id = str(row.get("post_id") or "").strip()
        for tool in parse_tags(row.get("competitor_tags")):
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
                if quote.lower() not in seen_quotes_by_tool[tool]:
                    group.quotes.append(quote)
                    seen_quotes_by_tool[tool].add(quote.lower())
    for group in grouped.values():
        scores = [_coerce_float(row.get("opportunity_score")) for row in group.rows]
        scores = [score for score in scores if score > 0]
        group.avg_opportunity_score = round(sum(scores) / len(scores), 3) if scores else 0.0
    return sorted(grouped.values(), key=lambda group: (-group.mention_count, -group.avg_opportunity_score, group.tool))


def failure_signals_for_row(row: dict[str, Any], *, primary_tool: str | None = None) -> list[str]:
    haystack = " ".join(str(row.get(field) or "") for field in ("title", "summary", "deep_dive_summary", "body")).lower()
    tags = parse_tags(row.get("competitor_tags"))
    comment_mentions = parse_tags(row.get("comment_tool_mentions") or row.get("comment_tool_mentions_json"))
    primary = str(primary_tool or "").strip().lower()
    signals: list[str] = []
    if _contains_any(haystack, ["price", "pricing", "cost", "expensive", "renewal", "billing", "license"]):
        signals.append("pricing_pain")
    if _contains_any(haystack, ["missing", "lacks", "feature", "does not support", "approval routing"]):
        signals.append("missing_feature")
    if _contains_any(
        haystack,
        ["lock-in", "lock in", "switch", "churn", "migrate", "can't export", "cannot export", "contract"],
    ):
        signals.append("lock_in_switching_churn")
    if _contains_any(haystack, ["support", "reliability", "failure", "fails", "failing", "broken", "bug", "outage"]):
        signals.append("reliability_support_failure")
    if _contains_any(haystack, ["workaround", "manual", "spreadsheet", "csv", "zapier"]):
        signals.append("workaround")
    if (primary and any(tag != primary for tag in tags + comment_mentions)) or (not primary and (len(tags) > 1 or comment_mentions)):
        signals.append("alternative_tool_mentions")
    return [key for key in FAILURE_SIGNAL_ORDER if key in set(signals)]


def exact_quotes(row: dict[str, Any]) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()
    for item in _verified_evidence(row):
        if str(item.get("match_type") or "").strip().lower() != "exact":
            continue
        quote = str(item.get("quote") or "").strip()
        if quote and quote.lower() not in seen:
            seen.add(quote.lower())
            quotes.append(quote)
    return quotes


def is_radar_promotion_candidate(row: dict[str, Any]) -> bool:
    components = _score_components(row)
    if str(components.get("evidence_rejection_reason") or "").strip():
        return False
    if components.get("promotion_eligible") is False:
        return False
    if not exact_quotes(row):
        return False
    first_handness = str(row.get("first_handness") or "unknown").strip().lower()
    authority_score = _coerce_float(row.get("buyer_authority_score"))
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


def _verified_evidence(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("verified_evidence")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
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


def _contains_any(haystack: str, needles: list[str]) -> bool:
    return any(needle in haystack for needle in needles)


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
