from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Literal

SourceType = Literal["title", "body", "comment"]
MatchType = Literal["exact", "fuzzy", "none"]

FUZZY_CONFIDENCE = 0.9


@dataclass(frozen=True)
class EvidenceSource:
    source_type: SourceType
    text: str
    post_id: str
    comment_id: str | None = None
    permalink: str = ""
    created_utc: int | None = None


@dataclass(frozen=True)
class VerifiedEvidence:
    quote: str
    source_type: SourceType | str
    post_id: str
    comment_id: str | None
    permalink: str
    match_type: MatchType
    match_confidence: float
    created_utc: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def verify_evidence_spans(quotes: list[str], sources: list[EvidenceSource]) -> list[VerifiedEvidence]:
    return [_verify_quote(str(quote or ""), sources) for quote in quotes]


def verified_evidence_to_dicts(items: list[VerifiedEvidence]) -> list[dict[str, object]]:
    return [item.to_dict() for item in items]


def _verify_quote(quote: str, sources: list[EvidenceSource]) -> VerifiedEvidence:
    if not quote.strip():
        return _unverified(quote)

    for source in sources:
        if quote in source.text:
            return _verified(quote, source, "exact", 1.0)

    normalized_quote = _normalize_for_match(quote)
    if not normalized_quote:
        return _unverified(quote)

    for source in sources:
        if normalized_quote in _normalize_for_match(source.text):
            return _verified(quote, source, "fuzzy", FUZZY_CONFIDENCE)

    return _unverified(quote)


def _verified(quote: str, source: EvidenceSource, match_type: MatchType, match_confidence: float) -> VerifiedEvidence:
    return VerifiedEvidence(
        quote=quote,
        source_type=source.source_type,
        post_id=source.post_id,
        comment_id=source.comment_id,
        permalink=source.permalink,
        match_type=match_type,
        match_confidence=match_confidence,
        created_utc=source.created_utc,
    )


def _unverified(quote: str) -> VerifiedEvidence:
    return VerifiedEvidence(
        quote=quote,
        source_type="",
        post_id="",
        comment_id=None,
        permalink="",
        match_type="none",
        match_confidence=0.0,
        created_utc=None,
    )


def _normalize_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    chars: list[str] = []
    for char in normalized:
        if char.isspace() or unicodedata.category(char)[0] in {"P", "S"}:
            chars.append(" ")
        else:
            chars.append(char)
    return re.sub(r"\s+", " ", "".join(chars)).strip()


__all__ = ["EvidenceSource", "VerifiedEvidence", "verified_evidence_to_dicts", "verify_evidence_spans"]
