from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

WTP_EVIDENCE_PATTERNS = (
    r"\bwould\s+pay\b",
    r"\bpay(?:ing)?\b",
    r"\bpaid\b",
    r"\bbudget\b",
    r"\bspend(?:ing)?\b",
    r"\bspent\b",
    r"\bpricing\b",
    r"\brenewal\b",
    r"\bsubscription\b",
    r"\blicen[cs]e\b",
    r"\bcontractor\b",
    r"[$€£]",
)
PAID_WORKAROUND_PATTERNS = (
    r"\bpaid\b",
    r"\bpaying\b",
    r"\bpay\s+(?:for|to)\b",
    r"\bbudget\b",
    r"\bsubscription\b",
    r"\blicen[cs]e\b",
    r"\bcontractor\b",
    r"[$€£]",
)
UNKNOWN_BUYER_AUTHORITIES = {"", "unknown", "none", "n/a", "na"}


@dataclass(frozen=True)
class BuyerWTPIntelligence:
    """Evidence-gated buyer and willingness-to-pay context for a rendered cluster."""

    buyer_role_counts: tuple[tuple[str, int], ...] = ()
    avg_buyer_authority: float = 0.0
    avg_wtp: float = 0.0
    wtp_evidence_quotes: tuple[str, ...] = ()
    paid_workarounds: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()

    @property
    def has_content(self) -> bool:
        return any(
            (
                self.buyer_role_counts,
                self.avg_buyer_authority,
                self.avg_wtp,
                self.wtp_evidence_quotes,
                self.paid_workarounds,
                self.uncertainties,
            )
        )

    @property
    def buyer_roles_text(self) -> str:
        return " | ".join(f"{role} ({count})" for role, count in self.buyer_role_counts)


def build_buyer_wtp_intelligence(
    examples: list[dict[str, Any]],
    *,
    quote_limit: int = 3,
    workaround_limit: int = 4,
    uncertainty_limit: int = 3,
) -> BuyerWTPIntelligence:
    """Summarize buyer/WTP signals from already promotion-filtered cluster examples.

    This helper intentionally assumes the caller has already applied verified-evidence
    promotion gating. It never decides eligibility and therefore cannot promote weak,
    noisy, or no-evidence rows by itself.
    """

    role_counts: Counter[str] = Counter()
    role_order: list[str] = []
    authority_scores: list[float] = []
    wtp_scores: list[float] = []
    wtp_quotes: list[str] = []
    paid_workarounds: list[str] = []
    uncertainties: list[str] = []

    for example in examples:
        role = _buyer_role(example)
        if role:
            if role not in role_counts:
                role_order.append(role)
            role_counts[role] += 1

        authority_score = _coerce_float(example.get("buyer_authority_score"))
        if authority_score:
            authority_scores.append(authority_score)

        wtp_score = _coerce_float(example.get("willingness_to_pay") or example.get("wtp_score"))
        if 0 < wtp_score <= 1:
            wtp_score *= 10
        if wtp_score:
            wtp_scores.append(min(10.0, wtp_score))

        for quote in _verified_quotes(example):
            if _matches_any(quote, WTP_EVIDENCE_PATTERNS):
                _append_unique(wtp_quotes, quote, limit=quote_limit)

        workaround = str(example.get("current_workaround") or "").strip()
        if workaround and _matches_any(workaround, PAID_WORKAROUND_PATTERNS):
            _append_unique(paid_workarounds, workaround, limit=workaround_limit)

        uncertainty = str(example.get("uncertainty_reason") or "").strip()
        if uncertainty:
            _append_unique(uncertainties, uncertainty, limit=uncertainty_limit)

    return BuyerWTPIntelligence(
        buyer_role_counts=tuple((role, role_counts[role]) for role in role_order),
        avg_buyer_authority=_avg(authority_scores),
        avg_wtp=_avg(wtp_scores),
        wtp_evidence_quotes=tuple(wtp_quotes),
        paid_workarounds=tuple(paid_workarounds),
        uncertainties=tuple(uncertainties),
    )


def _buyer_role(example: dict[str, Any]) -> str:
    authority = str(example.get("buyer_authority") or "").strip()
    if authority.lower() not in UNKNOWN_BUYER_AUTHORITIES:
        return authority
    context = example.get("user_context")
    if not isinstance(context, dict):
        context = {}
    for key in ("role", "persona", "job_title"):
        role = str(context.get(key) or "").strip()
        if role and role.lower() not in UNKNOWN_BUYER_AUTHORITIES:
            return role
    return ""


def _verified_quotes(example: dict[str, Any]) -> list[str]:
    exact_raw = example.get("exact_verified_quotes") or []
    exact_quotes = _string_list(exact_raw)
    if exact_quotes:
        return exact_quotes
    verified_evidence = example.get("verified_evidence") or []
    if isinstance(verified_evidence, list):
        evidence_quotes = [
            str(item.get("quote") or "").strip()
            for item in verified_evidence
            if isinstance(item, dict)
            and str(item.get("match_type") or "").lower() == "exact"
            and str(item.get("quote") or "").strip()
        ]
        if evidence_quotes:
            return evidence_quotes
    return _string_list(example.get("verified_quotes") or [])


def _string_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _append_unique(values: list[str], value: str, *, limit: int) -> None:
    normalized = value.casefold()
    if len(values) >= limit or any(existing.casefold() == normalized for existing in values):
        return
    values.append(value)


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _avg(values: list[float]) -> float:
    values = [value for value in values if value]
    return sum(values) / len(values) if values else 0.0


__all__ = ["BuyerWTPIntelligence", "build_buyer_wtp_intelligence"]
