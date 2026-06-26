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
    r"\bpricing\b",
    r"\brenewal\b",
    r"\bsubscription\b",
    r"\blicen[cs]e\b",
    r"[$€£]",
)


@dataclass(frozen=True)
class BuyerWTPIntelligence:
    buyer_role_counts: tuple[tuple[str, int], ...] = ()
    avg_buyer_authority: float = 0.0
    avg_wtp: float = 0.0
    wtp_evidence_quotes: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()

    @property
    def has_content(self) -> bool:
        return any((self.buyer_role_counts, self.avg_buyer_authority, self.avg_wtp, self.wtp_evidence_quotes, self.uncertainties))

    @property
    def buyer_roles_text(self) -> str:
        return " | ".join(f"{role} ({count})" for role, count in self.buyer_role_counts)


def build_buyer_wtp_intelligence(examples: list[dict[str, Any]], *, quote_limit: int = 3) -> BuyerWTPIntelligence:
    role_counts: Counter[str] = Counter()
    role_order: list[str] = []
    authority_scores: list[float] = []
    wtp_scores: list[float] = []
    wtp_quotes: list[str] = []
    uncertainties: list[str] = []

    for example in examples:
        role = str(example.get("buyer_authority") or "").strip()
        if role and role.lower() not in {"unknown", "none", "n/a"}:
            if role not in role_counts:
                role_order.append(role)
            role_counts[role] += 1
        authority_score = _coerce_float(example.get("buyer_authority_score"))
        if authority_score:
            authority_scores.append(authority_score)
        wtp = _coerce_float(example.get("willingness_to_pay") or example.get("wtp_score"))
        if 0 < wtp <= 1:
            wtp *= 10
        if wtp:
            wtp_scores.append(min(10.0, wtp))
        for quote in _verified_quotes(example):
            if len(wtp_quotes) >= quote_limit:
                break
            if _matches_any(quote, WTP_EVIDENCE_PATTERNS) and quote not in wtp_quotes:
                wtp_quotes.append(quote)
        uncertainty = str(example.get("uncertainty_reason") or "").strip()
        if uncertainty and uncertainty not in uncertainties:
            uncertainties.append(uncertainty)

    return BuyerWTPIntelligence(
        buyer_role_counts=tuple((role, role_counts[role]) for role in role_order),
        avg_buyer_authority=_avg(authority_scores),
        avg_wtp=_avg(wtp_scores),
        wtp_evidence_quotes=tuple(wtp_quotes),
        uncertainties=tuple(uncertainties[:3]),
    )


def _verified_quotes(example: dict[str, Any]) -> list[str]:
    evidence = example.get("verified_evidence")
    if not isinstance(evidence, list):
        return []
    return [
        str(item.get("quote") or "").strip()
        for item in evidence
        if isinstance(item, dict)
        and str(item.get("match_type") or "").lower() == "exact"
        and str(item.get("quote") or "").strip()
    ]


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _avg(values: list[float]) -> float:
    values = [value for value in values if value]
    return round(sum(values) / len(values), 3) if values else 0.0
