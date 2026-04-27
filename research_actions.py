from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

RESEARCH_ACTION_TEXT_FIELDS = (
    "icp_hypothesis",
    "mvp_wedge",
    "messaging_angle",
    "why_now",
    "manual_validation_step",
)
RESEARCH_ACTION_LIST_FIELDS = ("interview_questions", "risks_unknowns")


def normalize_research_action(
    raw: Any,
    *,
    eligible_post_ids: Iterable[str] | None = None,
    require_evidence_ids: bool = False,
    strict_types: bool = False,
) -> dict[str, Any]:
    """Return a safe research-action payload or `{}`.

    `eligible_post_ids` is an evidence-first guard for primary surfaces. If a
    stored/LLM action names weak or unknown evidence rows, callers should ignore
    it and rebuild from currently eligible exact-evidence examples.
    """

    payload = _json_object(raw)
    if not payload:
        return {}

    cleaned: dict[str, Any] = {}
    for field in RESEARCH_ACTION_LIST_FIELDS:
        values = _string_list(payload.get(field), limit=5, strict_types=strict_types)
        if field == "interview_questions" and len(values) < 2:
            return {}
        if not values:
            return {}
        cleaned[field] = values

    for field in RESEARCH_ACTION_TEXT_FIELDS:
        raw_value = payload.get(field)
        if strict_types and not isinstance(raw_value, str):
            return {}
        value = _clean_text(raw_value, limit=360)
        if not value:
            return {}
        cleaned[field] = value

    evidence_post_ids = _string_list(payload.get("evidence_post_ids"), limit=20, strict_types=strict_types)
    evidence_set = set(evidence_post_ids)
    if require_evidence_ids and not evidence_set:
        return {}
    if eligible_post_ids is not None:
        eligible = {str(item).strip() for item in eligible_post_ids if str(item).strip()}
        if evidence_set and (not eligible or not evidence_set.issubset(eligible)):
            return {}
    if evidence_post_ids:
        cleaned["evidence_post_ids"] = evidence_post_ids
    return cleaned


def build_next_research_action(
    cluster: dict[str, Any],
    examples: list[dict[str, Any]],
    *,
    stored_action: Any | None = None,
) -> dict[str, Any]:
    """Build an evidence-gated next-action block for a top cluster.

    The fallback is deterministic and uses only examples that carry exact
    verified quotes. This keeps research-to-action output actionable without
    turning cluster diagnostics or weak/no-evidence rows into a promotion path.
    """

    eligible_examples = [example for example in examples if _exact_quotes(example)]
    evidence_post_ids = _unique(
        str(example.get("post_id") or "").strip()
        for example in eligible_examples
        if str(example.get("post_id") or "").strip()
    )
    stored = normalize_research_action(
        stored_action,
        eligible_post_ids=evidence_post_ids,
        require_evidence_ids=True,
    )
    if stored:
        return stored
    if not eligible_examples:
        return {}

    label = _action_problem_label(eligible_examples)
    quotes = _unique(quote for example in eligible_examples for quote in _exact_quotes(example))
    workarounds = _text_values(eligible_examples, "current_workaround")
    failures = _text_values(eligible_examples, "incumbent_failure")
    personas = _personas(eligible_examples)
    source_count = len(_unique(str(example.get("source") or "").strip() for example in eligible_examples)) or len(
        eligible_examples
    )
    verified_quote_count = len(quotes)
    persona = personas[0] if personas else "the owner of this workflow"
    workaround = workarounds[0] if workarounds else "the current manual workflow"
    failure = failures[0] if failures else "the existing process keeps breaking"
    quote_hint = quotes[0] if quotes else label

    action = {
        "interview_questions": [
            f"How often does {workaround} happen, and who owns fixing it?",
            f"What breaks downstream when {failure}?",
            "What would make a manual concierge fix worth trying this week?",
        ],
        "icp_hypothesis": f"{persona} teams that own {label.lower()}.",
        "mvp_wedge": f"Concierge workflow that replaces {workaround} for {persona}.",
        "messaging_angle": f"Stop {workaround}; start from the verified pain: “{quote_hint[:140]}”.",
        "why_now": (
            f"{verified_quote_count} verified exact quote"
            f"{'s' if verified_quote_count != 1 else ''}"
            f" across {source_count} eligible evidence-backed signal"
            f"{'s' if source_count != 1 else ''}; validate whether this repeats beyond the surfaced rows"
        ),
        "risks_unknowns": _risks(
            independent_source_count=source_count,
            failure=failure,
        ),
        "manual_validation_step": (
            f"Interview 5 {persona} users and manually solve one {workaround} case before building automation."
        ),
        "evidence_post_ids": evidence_post_ids,
    }
    return normalize_research_action(action, eligible_post_ids=evidence_post_ids, require_evidence_ids=True)


def _action_problem_label(examples: list[dict[str, Any]]) -> str:
    for key in ("current_workaround", "incumbent_failure", "summary", "title"):
        for example in examples:
            value = _clean_text(example.get(key), limit=120)
            if value:
                return value.lower()
    return "this verified workflow pain"


def _risks(*, independent_source_count: int, failure: str) -> list[str]:
    risks = ["Confirm there is a clear owner and budget before productizing the workflow."]
    if independent_source_count < 2:
        risks.append("Validate the pain beyond one source before treating it as a repeatable wedge.")
    if failure:
        risks.append(f"Check whether {failure} is recurring or a one-off implementation issue.")
    return risks[:3]


def _exact_quotes(example: dict[str, Any]) -> list[str]:
    raw = example.get("exact_verified_quotes") or example.get("verified_quotes") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return _unique(str(item).strip() for item in raw if str(item).strip())


def _personas(examples: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for example in examples:
        context = _json_object(example.get("user_context"))
        for key in ("persona", "role", "workflow", "industry", "company_size", "tool_stack", "process"):
            raw = context.get(key)
            if isinstance(raw, list):
                values.extend(str(item).strip() for item in raw if str(item).strip())
            elif str(raw or "").strip():
                values.append(str(raw).strip())
        buyer = str(example.get("buyer_authority") or "").strip()
        if buyer and buyer != "unknown":
            values.append(buyer.replace("_", " "))
    return _unique(values)


def _text_values(examples: list[dict[str, Any]], key: str) -> list[str]:
    return _unique(str(example.get(key) or "").strip() for example in examples if str(example.get(key) or "").strip())


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _string_list(raw: Any, *, limit: int, strict_types: bool = False) -> list[str]:
    if strict_types:
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            return []
    elif isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return _unique(_clean_text(item, limit=240) for item in raw)[:limit]


def _clean_text(raw: Any, *, limit: int) -> str:
    text = " ".join(str(raw or "").split()).strip()
    return text[:limit]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_values.append(clean)
    return unique_values


def _coerce_float(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0
