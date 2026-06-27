from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from budget import BudgetCapReachedError, BudgetGuard
from classifier import (
    Classifier,
    PainSignal,
    buyer_authority_score,
    estimate_impact_score,
    estimate_solved_penalty,
    estimate_workflow_frequency_score,
    extract_comment_market_signals,
    first_handness_score,
)
from db import Database
from evidence import EvidenceSource, VerifiedEvidence, verified_evidence_to_dicts, verify_evidence_spans
from openrouter import DeepDiveResult
from rejected_noise import hard_negative_type_for_signal
from scraper import Post, RedditScraper

if TYPE_CHECKING:
    from deduplicator import Deduplicator

logger = logging.getLogger(__name__)
ARTIFACT_STEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")
PROMOTION_SCORE_CAP = 35.0


def _safe_text(value: Any, *, default: str = "") -> str:
    text = str(default if value is None else value).strip()
    return text or default


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def safe_artifact_stem(raw: str, *, default: str = "scope") -> str:
    stem = ARTIFACT_STEM_RE.sub("_", str(raw or "").strip())
    stem = stem.strip("._-")
    return stem or default


@dataclass
class DeepDiveRun:
    post_id: str
    subreddit: str
    status: str
    source: str
    summary: str = ""
    payload: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class AnalysisRun:
    subreddit: str
    post_count: int
    pain_count: int
    monetizable_count: int
    deep_dive_count: int
    signals: list[PainSignal]
    json_path: str
    report_id: int
    analysis_run_id: int
    source: str = "reddit"


class AnalysisPipeline:
    def __init__(
        self,
        scraper: RedditScraper,
        classifier: Classifier,
        db: Database,
        reports_dir: str,
        deep_dive_wtp_threshold: int = 8,
        deep_dive_max_comments: int = 250,
        budget_guard: BudgetGuard | None = None,
        deduplicator: Deduplicator | None = None,
        llm_max_classifications_per_run: int = 0,
        screen_max_llm_candidates_per_run: int = 0,
        current_opportunity_max_age_days: int = 180,
    ):
        self.scraper = scraper
        self.classifier = classifier
        self.db = db
        self.reports_dir = reports_dir
        self.deep_dive_wtp_threshold = deep_dive_wtp_threshold
        self.deep_dive_max_comments = deep_dive_max_comments
        self.budget_guard = budget_guard
        self.deduplicator = deduplicator
        self.llm_max_classifications_per_run = max(0, int(llm_max_classifications_per_run))
        self.screen_max_llm_candidates_per_run = max(0, int(screen_max_llm_candidates_per_run))
        self.current_opportunity_max_age_days = max(1, int(current_opportunity_max_age_days))

    async def analyze_subreddit(self, subreddit: str, limit: int = 100) -> AnalysisRun:
        posts = await self.scraper.fetch_posts(subreddit, limit=limit)
        return await self._analyze_posts(
            posts=posts,
            run_scope=subreddit,
            source="reddit",
            run_label=subreddit,
        )

    async def analyze_external_posts(
        self,
        *,
        posts: list[Post],
        source: str,
        run_scope: str,
    ) -> AnalysisRun:
        return await self._analyze_posts(
            posts=posts,
            run_scope=run_scope,
            source=source,
            run_label=f"{source}_{run_scope}",
        )

    async def _analyze_posts(
        self,
        *,
        posts: list[Post],
        run_scope: str,
        source: str,
        run_label: str,
    ) -> AnalysisRun:
        start = perf_counter()
        existing_ids = await self.db.get_pain_points_by_ids([post.post_id for post in posts])
        fresh_posts = [post for post in posts if post.post_id not in existing_ids]
        skipped_existing_count = len(posts) - len(fresh_posts)
        fresh_post_count = len(fresh_posts)

        configured_limits = [limit for limit in [self.screen_max_llm_candidates_per_run, self.llm_max_classifications_per_run] if limit > 0]
        screening_limit = min(configured_limits) if configured_limits else 0
        screen_rule_dropped_count = 0
        screen_kept_count = len(fresh_posts)
        screen_capped_count = 0
        if hasattr(self.classifier, "prescreen_posts"):
            fresh_posts, screen_stats = self.classifier.prescreen_posts(
                fresh_posts,
                max_candidates=screening_limit,
            )
            screen_rule_dropped_count = int(screen_stats.get("screen_rule_dropped_count", 0))
            screen_kept_count = int(screen_stats.get("screen_kept_count", len(fresh_posts)))
            screen_capped_count = int(screen_stats.get("screen_capped_count", 0))
        llm_capped_count = screen_capped_count

        if fresh_posts:
            if self.budget_guard is not None:
                await self.budget_guard.ensure_can_spend("pipeline_analyze")
            elif await self.db.is_llm_paused():
                raise RuntimeError("LLM operations are paused. Use /resume to override.")
            classified_signals = await self.classifier.classify_batch(fresh_posts)
        else:
            classified_signals = []
        persisted_signals: list[PainSignal] = []
        classified_count = len(classified_signals)
        inserted_count = 0
        dedup_merged_count = 0
        dedup_embed_failed_count = 0
        dedup_merge_failed_count = 0
        discarded_non_pain_count = max(0, len(fresh_posts) - classified_count)

        monetizable_count = 0
        deep_dive_count = 0
        primary_success_count = 0
        legacy_fallback_count = 0
        deep_dive_skipped_reasons: dict[str, int] = {}

        for signal in classified_signals:
            embedding: list[float] | None = None
            opportunity_bucket = self._classify_opportunity_bucket(signal.post)
            signal.opportunity_bucket = opportunity_bucket
            self._enrich_signal(signal)
            if signal.analysis_mode in {"b2b", "dspy_b2b"}:
                primary_success_count += 1
            elif signal.analysis_mode == "legacy_llm":
                legacy_fallback_count += 1

            if self.deduplicator is not None:
                text = f"{signal.post.title} {signal.post.body}"
                try:
                    embedding = await self.deduplicator.embedder.embed(text)
                except Exception as exc:
                    dedup_embed_failed_count += 1
                    logger.warning(
                        "dedup: embed failed for %s (%s), skipping dedup",
                        signal.post.post_id,
                        exc,
                    )
                    embedding = None
                else:
                    try:
                        is_dup = await self.deduplicator.find_and_merge(
                            post_id=signal.post.post_id,
                            embedding=embedding,
                            source=source,
                        )
                    except Exception as exc:
                        dedup_merge_failed_count += 1
                        logger.warning(
                            "dedup: merge check failed for %s (%s), skipping dedup",
                            signal.post.post_id,
                            exc,
                        )
                        is_dup = False
                    if is_dup:
                        dedup_merged_count += 1
                        continue  # duplicate merged into canonical; skip insert

            await self.db.insert_pain_point(
                subreddit=signal.post.subreddit,
                post_id=signal.post.post_id,
                url=signal.post.url,
                title=signal.post.title,
                body=signal.post.body,
                category=signal.category,
                summary=signal.summary,
                severity=signal.severity,
                is_monetizable=signal.is_monetizable,
                pain_level=signal.pain_level,
                willingness_to_pay=signal.willingness_to_pay,
                niche_category=signal.niche_category,
                competitor_tags=signal.competitor_tags,
                source=source,
                source_created_at=signal.post.source_created_at,
                source_created_ts=signal.post.source_created_ts,
                author_name=signal.post.author_name,
                opportunity_bucket=opportunity_bucket,
                post_type=signal.post_type,
                first_handness=signal.first_handness,
                buyer_authority=signal.buyer_authority,
                evidence_spans=signal.evidence_spans,
                comment_sample=signal.comment_sample,
                buyer_authority_score=signal.buyer_authority_score,
                workflow_frequency_score=signal.workflow_frequency_score,
                impact_score=signal.impact_score,
                consensus_score=signal.consensus_score,
                incumbent_failure_score=signal.incumbent_failure_score,
                recency_score=signal.recency_score,
                stale_penalty=signal.stale_penalty,
                solved_penalty=signal.solved_penalty,
                opportunity_score=signal.opportunity_score,
                score_components=signal.score_components,
                comment_consensus_count=signal.comment_consensus_count,
                comment_same_here_count=signal.comment_same_here_count,
                comment_workaround_count=signal.comment_workaround_count,
                comment_tool_mentions=signal.comment_tool_mentions,
                comment_shill_risk=signal.comment_shill_risk,
                analysis_mode=signal.analysis_mode,
                analysis_payload=signal.analysis_payload,
                emb_vector=embedding,
            )
            persisted_signals.append(signal)
            inserted_count += 1

            if signal.is_monetizable:
                monetizable_count += 1

            existing = await self.db.get_pain_point(signal.post.post_id)
            deep_dive_skip_reason = self._deep_dive_skip_reason(signal, existing=existing)
            if deep_dive_skip_reason is None:
                deep_dive = await self.run_deep_dive(
                    post_id=signal.post.post_id,
                    subreddit=signal.post.subreddit,
                    source="auto",
                    title=signal.post.title,
                    body=signal.post.body,
                )
                if deep_dive.status == "completed":
                    deep_dive_count += 1
                else:
                    deep_dive_skipped_reasons[deep_dive.status] = deep_dive_skipped_reasons.get(deep_dive.status, 0) + 1
            else:
                deep_dive_skipped_reasons[deep_dive_skip_reason] = deep_dive_skipped_reasons.get(deep_dive_skip_reason, 0) + 1

        report_data = self._build_report_payload(signals=persisted_signals, source=source)
        json_path = await self._write_report(run_label=run_label, payload=report_data)

        report_id = await self.db.save_report(
            subreddit=run_scope,
            post_count=len(posts),
            pain_count=inserted_count,
            json_path=json_path,
        )
        duration_ms = int((perf_counter() - start) * 1000)
        analysis_run_id = await self.db.record_analysis_run(
            subreddit=run_scope,
            post_count=len(posts),
            pain_count=inserted_count,
            monetizable_count=monetizable_count,
            deep_dive_count=deep_dive_count,
            skipped_existing_count=skipped_existing_count,
            dedup_merged_count=dedup_merged_count,
            screen_rule_dropped_count=screen_rule_dropped_count,
            screen_kept_count=screen_kept_count,
            screen_capped_count=screen_capped_count,
            duration_ms=duration_ms,
            report_id=report_id,
        )

        logger.info(
            "analysis_complete stage=analyze source=%s scope=%s analysis_run_id=%s "
            "post_count=%d fresh_post_count=%d skipped_existing_count=%d screen_rule_dropped_count=%d "
            "screen_kept_count=%d llm_capped_count=%d pain_count=%d monetizable_count=%d deep_dive_count=%d "
            "inserted_count=%d dedup_merged_count=%d dedup_embed_failed_count=%d dedup_merge_failed_count=%d discarded_non_pain_count=%d primary_success_count=%d "
            "legacy_fallback_count=%d deep_dive_skipped_reasons=%s duration_ms=%d",
            source,
            run_scope,
            analysis_run_id,
            len(posts),
            fresh_post_count,
            skipped_existing_count,
            screen_rule_dropped_count,
            screen_kept_count,
            llm_capped_count,
            inserted_count,
            monetizable_count,
            deep_dive_count,
            inserted_count,
            dedup_merged_count,
            dedup_embed_failed_count,
            dedup_merge_failed_count,
            discarded_non_pain_count,
            primary_success_count,
            legacy_fallback_count,
            json.dumps(deep_dive_skipped_reasons, sort_keys=True),
            duration_ms,
        )

        return AnalysisRun(
            subreddit=run_scope,
            post_count=len(posts),
            pain_count=inserted_count,
            monetizable_count=monetizable_count,
            deep_dive_count=deep_dive_count,
            signals=persisted_signals,
            json_path=json_path,
            report_id=report_id,
            analysis_run_id=analysis_run_id,
            source=source,
        )

    async def run_deep_dive(
        self,
        *,
        post_id: str,
        subreddit: str,
        source: str = "manual",
        title: str | None = None,
        body: str | None = None,
    ) -> DeepDiveRun:
        openrouter = self.classifier.openrouter
        if openrouter is None:
            return DeepDiveRun(
                post_id=post_id,
                subreddit=subreddit,
                source=source,
                status="failed",
                error="OpenRouter client is not configured.",
            )

        existing = await self.db.get_pain_point(post_id)
        if existing:
            title = title or existing.get("title") or ""
            body = body or existing.get("body") or ""

        await self.db.mark_deep_dive_status(post_id, "running")
        await self.db.save_deep_dive(
            post_id=post_id,
            subreddit=subreddit,
            source=source,
            status="running",
        )

        try:
            comments = await self.scraper.fetch_full_thread(
                subreddit=subreddit,
                post_id=post_id,
                max_comments=self.deep_dive_max_comments,
            )
            thread_text = self._build_thread_text(title or "", body or "", comments)
            deep_result = await openrouter.analyze_deep_dive(
                title or "",
                thread_text,
                post_id=post_id,
            )
            if deep_result is None:
                raise RuntimeError("Deep dive model returned invalid response")

            payload = self._deep_dive_payload(deep_result)
            await self.db.save_deep_dive(
                post_id=post_id,
                subreddit=subreddit,
                source=source,
                status="completed",
                payload=payload,
            )
            await self.db.mark_deep_dive_status(post_id, "completed", summary=deep_result.actionable_summary)

            logger.info(
                "deep_dive_complete stage=deep_dive subreddit=%s post_id=%s source=%s",
                subreddit,
                post_id,
                source,
            )
            return DeepDiveRun(
                post_id=post_id,
                subreddit=subreddit,
                source=source,
                status="completed",
                summary=deep_result.actionable_summary,
                payload=payload,
            )
        except BudgetCapReachedError as e:
            await self.db.mark_deep_dive_status(post_id, "failed", error=str(e))
            return DeepDiveRun(post_id=post_id, subreddit=subreddit, source=source, status="failed", error=str(e))
        except Exception as e:
            error = str(e)
            await self.db.save_deep_dive(
                post_id=post_id,
                subreddit=subreddit,
                source=source,
                status="failed",
                error=error,
            )
            await self.db.mark_deep_dive_status(post_id, "failed", error=error)
            logger.exception(
                "deep_dive_failed stage=deep_dive subreddit=%s post_id=%s source=%s",
                subreddit,
                post_id,
                source,
            )
            return DeepDiveRun(post_id=post_id, subreddit=subreddit, source=source, status="failed", error=error)

    async def generate_digest(self, *, subreddit: str | None = None, hours: int = 24) -> dict[str, Any]:
        rows = await self.db.get_recent_pain_points(hours=hours, subreddit=subreddit)
        if not rows:
            return {
                "hours": hours,
                "subreddit": subreddit,
                "total": 0,
                "top_items": [],
                "top_clusters": [],
                "niche_counts": {},
                "source_counts": {},
                "recurring_blockers": [],
            }

        row_post_ids = [str(row.get("post_id")) for row in rows if row.get("post_id")]
        top_clusters = await self.db.get_latest_canonical_clusters(limit=5, post_ids=row_post_ids)

        scored_rows = []
        niche_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        blockers: dict[str, int] = {}

        for row in rows:
            score = self._row_opportunity_score(row)
            row_copy = dict(row)
            row_copy["opportunity_score"] = score
            row_copy["weighted_score"] = score
            score_components = row_copy.get("score_components_json")
            if isinstance(score_components, str) and score_components.strip():
                try:
                    row_copy["score_components"] = json.loads(score_components)
                except json.JSONDecodeError:
                    row_copy["score_components"] = {}
            scored_rows.append(row_copy)

            niche = _safe_text(row.get("niche_category"), default="Uncategorized")
            niche_counts[niche] = niche_counts.get(niche, 0) + 1
            source_name = _safe_text(row.get("source"), default="unknown")
            source_counts[source_name] = source_counts.get(source_name, 0) + 1

            summary = _safe_text(row.get("deep_dive_summary"))
            if summary:
                blockers[summary] = blockers.get(summary, 0) + 1

        scored_rows.sort(
            key=lambda row: (
                self._row_opportunity_score(row),
                len(row.get("evidence_spans") or []),
                _safe_int(row.get("source_created_ts")),
                _safe_int(row.get("willingness_to_pay")),
                _safe_int(row.get("pain_level")),
            ),
            reverse=True,
        )

        recurring_blockers = [
            item[0]
            for item in sorted(blockers.items(), key=lambda item: item[1], reverse=True)[:5]
        ]
        return {
            "hours": hours,
            "subreddit": subreddit,
            "total": len(rows),
            "top_items": scored_rows[:5],
            "top_clusters": top_clusters,
            "niche_counts": niche_counts,
            "source_counts": source_counts,
            "recurring_blockers": recurring_blockers,
        }

    async def _write_report(self, *, run_label: str, payload: list[dict[str, Any]]) -> str:
        os.makedirs(self.reports_dir, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        safe_run_label = safe_artifact_stem(run_label, default="report")
        json_path = os.path.join(self.reports_dir, f"{safe_run_label}_{timestamp}.json")
        tmp_path = f"{json_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as report_file:
                json.dump(payload, report_file, indent=2, ensure_ascii=False, allow_nan=False)
            os.replace(tmp_path, json_path)
            return json_path
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    @staticmethod
    def _build_report_payload(*, signals: list[PainSignal], source: str) -> list[dict[str, Any]]:
        return [
            {
                "post_id": signal.post.post_id,
                "title": signal.post.title,
                "url": signal.post.url,
                "source": source,
                "discovery_query": signal.post.discovery_query,
                "category": signal.category,
                "summary": signal.summary,
                "severity": signal.severity,
                "is_monetizable": signal.is_monetizable,
                "pain_level": signal.pain_level,
                "willingness_to_pay": signal.willingness_to_pay,
                "niche_category": signal.niche_category,
                "competitor_tags": signal.competitor_tags,
                "analysis_mode": signal.analysis_mode,
                "source_created_at": signal.post.source_created_at,
                "source_created_ts": signal.post.source_created_ts,
                "author_name": signal.post.author_name,
                "opportunity_bucket": signal.opportunity_bucket,
                "post_type": signal.post_type,
                "first_handness": signal.first_handness,
                "buyer_authority": signal.buyer_authority,
                "evidence_spans": signal.evidence_spans,
                "verified_evidence": (
                    signal.analysis_payload.get("verified_evidence")
                    if isinstance(signal.analysis_payload, dict)
                    else []
                ),
                "promotion_eligible": bool(
                    signal.analysis_payload.get("promotion_eligible")
                    if isinstance(signal.analysis_payload, dict)
                    else False
                ),
                "evidence_rejection_reason": (
                    signal.analysis_payload.get("evidence_rejection_reason")
                    if isinstance(signal.analysis_payload, dict)
                    else None
                ),
                "comment_sample": signal.comment_sample,
                "buyer_authority_score": signal.buyer_authority_score,
                "workflow_frequency_score": signal.workflow_frequency_score,
                "impact_score": signal.impact_score,
                "consensus_score": signal.consensus_score,
                "incumbent_failure_score": signal.incumbent_failure_score,
                "recency_score": signal.recency_score,
                "stale_penalty": signal.stale_penalty,
                "solved_penalty": signal.solved_penalty,
                "opportunity_score": signal.opportunity_score,
                "score_components": signal.score_components or {},
                "comment_consensus_count": signal.comment_consensus_count,
                "comment_same_here_count": signal.comment_same_here_count,
                "comment_workaround_count": signal.comment_workaround_count,
                "comment_tool_mentions": signal.comment_tool_mentions,
                "comment_shill_risk": signal.comment_shill_risk,
            }
            for signal in signals
        ]

    def _enrich_signal(self, signal: PainSignal) -> None:
        comment_signals = extract_comment_market_signals(signal.post, competitor_tags=signal.competitor_tags)
        recency_score, stale_penalty = self._recency_profile(signal.post, signal.opportunity_bucket)
        verified_evidence = self._verified_evidence(signal)
        verified_evidence_dicts = verified_evidence_to_dicts(verified_evidence)
        anchored_evidence_count = sum(1 for item in verified_evidence if item.match_type != "none")
        exact_evidence_count = sum(1 for item in verified_evidence if item.match_type == "exact")
        evidence_score = min(1.0, anchored_evidence_count / 3) if signal.evidence_spans else 0.0
        authority_score = buyer_authority_score(signal.buyer_authority)
        first_hand_score = first_handness_score(signal.first_handness)
        workflow_frequency_score = estimate_workflow_frequency_score(signal.post, signal)
        impact_score = estimate_impact_score(signal.post, signal)
        solved_penalty = estimate_solved_penalty(signal.post, comment_signals=comment_signals)
        consensus_score = min(1.0, 0.18 + comment_signals["comment_consensus_count"] * 0.22 + evidence_score * 0.18)
        incumbent_failure_score = min(
            1.0,
            0.18
            + len(signal.competitor_tags) * 0.16
            + len(comment_signals["comment_tool_mentions"]) * 0.05
            + comment_signals["comment_workaround_count"] * 0.11
            + (0.14 if signal.post_type in {"vendor_rant", "tool_comparison"} else 0.0),
        )
        type_penalty = 0.0
        if signal.post_type in {"founder_pitch", "news_analysis"} and signal.first_handness != "first_hand":
            type_penalty += 0.22
        elif signal.post_type == "advice_thread":
            type_penalty += 0.08
        raw_score = (
            signal.pain_level / 10 * 22
            + signal.willingness_to_pay / 10 * 18
            + authority_score * 14
            + first_hand_score * 8
            + workflow_frequency_score * 10
            + impact_score * 12
            + consensus_score * 10
            + incumbent_failure_score * 8
            + recency_score * 10
            + evidence_score * 6
            - stale_penalty * 10
            - solved_penalty * 12
            - float(comment_signals["comment_shill_risk"]) * 6
            - type_penalty * 10
        )
        opportunity_score = round(max(0.0, raw_score), 2)

        signal.comment_consensus_count = int(comment_signals["comment_consensus_count"])
        signal.comment_same_here_count = int(comment_signals["comment_same_here_count"])
        signal.comment_workaround_count = int(comment_signals["comment_workaround_count"])
        signal.comment_tool_mentions = list(comment_signals["comment_tool_mentions"])
        signal.comment_shill_risk = float(comment_signals["comment_shill_risk"])
        signal.comment_sample = list(comment_signals["comment_sample"])
        signal.buyer_authority_score = round(authority_score, 3)
        signal.workflow_frequency_score = round(workflow_frequency_score, 3)
        signal.impact_score = round(impact_score, 3)
        signal.consensus_score = round(consensus_score, 3)
        signal.incumbent_failure_score = round(incumbent_failure_score, 3)
        signal.recency_score = round(recency_score, 3)
        signal.stale_penalty = round(stale_penalty, 3)
        signal.solved_penalty = round(solved_penalty + type_penalty, 3)
        signal.opportunity_score = opportunity_score
        signal.score_components = {
            "buyer_authority_score": signal.buyer_authority_score,
            "first_handness_score": round(first_hand_score, 3),
            "workflow_frequency_score": signal.workflow_frequency_score,
            "impact_score": signal.impact_score,
            "consensus_score": signal.consensus_score,
            "incumbent_failure_score": signal.incumbent_failure_score,
            "recency_score": signal.recency_score,
            "stale_penalty": signal.stale_penalty,
            "solved_penalty": signal.solved_penalty,
            "evidence_score": round(evidence_score, 3),
            "verified_evidence_count": anchored_evidence_count,
            "exact_evidence_count": exact_evidence_count,
            "type_penalty": round(type_penalty, 3),
            "comment_consensus_count": signal.comment_consensus_count,
            "comment_same_here_count": signal.comment_same_here_count,
            "comment_workaround_count": signal.comment_workaround_count,
            "comment_tool_mentions": signal.comment_tool_mentions,
            "comment_shill_risk": signal.comment_shill_risk,
        }
        if signal.analysis_payload is None:
            signal.analysis_payload = {}
        if isinstance(signal.analysis_payload, dict):
            signal.analysis_payload.setdefault("comment_sample", signal.comment_sample)
            signal.analysis_payload.setdefault("score_components", signal.score_components)
            signal.analysis_payload["verified_evidence"] = verified_evidence_dicts
        promotion_rejection_reason = self._promotion_rejection_reason(signal)
        hard_negative_type = hard_negative_type_for_signal(
            post_type=signal.post_type,
            niche_category=signal.niche_category,
            rejection_reason=promotion_rejection_reason,
        )
        promotion_eligible = promotion_rejection_reason is None
        if not promotion_eligible:
            signal.opportunity_score = min(signal.opportunity_score, PROMOTION_SCORE_CAP)
            if signal.score_components is not None:
                signal.score_components["promotion_score_cap"] = PROMOTION_SCORE_CAP
        if signal.score_components is not None:
            signal.score_components["promotion_eligible"] = promotion_eligible
            signal.score_components["evidence_rejection_reason"] = promotion_rejection_reason
            signal.score_components["hard_negative_type"] = hard_negative_type
        if isinstance(signal.analysis_payload, dict):
            signal.analysis_payload["promotion_eligible"] = promotion_eligible
            signal.analysis_payload["evidence_rejection_reason"] = promotion_rejection_reason
            signal.analysis_payload["hard_negative_type"] = hard_negative_type
            signal.analysis_payload["score_components"] = signal.score_components

    @staticmethod
    def _evidence_sources(post: Post) -> list[EvidenceSource]:
        sources = [
            EvidenceSource(
                source_type="title",
                text=post.title,
                post_id=post.post_id,
                permalink=post.permalink or post.url,
                created_utc=post.source_created_ts,
            ),
            EvidenceSource(
                source_type="body",
                text=post.body,
                post_id=post.post_id,
                permalink=post.permalink or post.url,
                created_utc=post.source_created_ts,
            ),
        ]
        for index, comment in enumerate(post.top_comments):
            if isinstance(comment, str) and comment.strip():
                sources.append(
                    EvidenceSource(
                        source_type="comment",
                        text=comment,
                        post_id=post.post_id,
                        comment_id=f"comment:{index}",
                        permalink=post.permalink or post.url,
                        created_utc=post.source_created_ts,
                    )
                )
        return sources

    @classmethod
    def _verified_evidence(cls, signal: PainSignal) -> list[VerifiedEvidence]:
        return verify_evidence_spans(signal.evidence_spans, cls._evidence_sources(signal.post))

    @classmethod
    def _grounded_evidence_spans(cls, signal: PainSignal) -> list[str]:
        return [item.quote for item in cls._verified_evidence(signal) if item.match_type != "none"]

    def _promotion_rejection_reason(self, signal: PainSignal) -> str | None:
        if not signal.is_monetizable:
            return "not_monetizable"
        if signal.post_type == "news_analysis":
            return "unsupported_post_type"
        if signal.post_type in {"founder_pitch", "advice_thread"} and signal.first_handness not in {
            "first_hand",
            "second_hand",
        }:
            return "insufficient_first_hand_evidence"
        if not self._grounded_evidence_spans(signal):
            return "ungrounded_evidence"
        return None

    def _recency_profile(self, post: Post, bucket: str) -> tuple[float, float]:
        if not post.source_created_ts:
            return 0.35, 0.08
        age_seconds = max(0, int(datetime.now(UTC).timestamp()) - int(post.source_created_ts))
        age_days = age_seconds / 86400.0
        if bucket == "current_opportunity":
            recency_score = max(0.45, 1.0 - age_days / max(1, self.current_opportunity_max_age_days) * 0.55)
            return round(min(1.0, recency_score), 3), 0.0
        overflow_days = max(0.0, age_days - self.current_opportunity_max_age_days)
        recency_score = max(0.18, 0.45 - min(365.0, overflow_days) / 365.0 * 0.22)
        stale_penalty = min(0.55, 0.1 + overflow_days / 365.0 * 0.25)
        return round(recency_score, 3), round(stale_penalty, 3)

    def _deep_dive_skip_reason(self, signal: PainSignal, *, existing: dict[str, Any] | None) -> str | None:
        promotion_rejection_reason = None
        if isinstance(signal.analysis_payload, dict):
            promotion_rejection_reason = signal.analysis_payload.get("evidence_rejection_reason")
        if promotion_rejection_reason:
            return f"not_promotion_eligible:{promotion_rejection_reason}"
        if not signal.is_monetizable:
            return "not_monetizable"
        if signal.willingness_to_pay < self.deep_dive_wtp_threshold:
            return "below_wtp_threshold"
        if getattr(self.classifier, "openrouter", None) is None:
            return "openrouter_unconfigured"
        if existing and existing.get("deep_dive_status") == "completed":
            return "already_completed"
        return None

    @staticmethod
    def _row_opportunity_score(row: dict[str, Any]) -> float:
        raw = row.get("opportunity_score")
        if raw is not None:
            try:
                parsed = float(raw)
            except (TypeError, ValueError, OverflowError):
                pass
            else:
                if math.isfinite(parsed):
                    return round(parsed, 2)
        pain_level = _safe_int(row.get("pain_level"))
        wtp = _safe_int(row.get("willingness_to_pay"))
        return round((pain_level + wtp) / 2, 2)

    def _classify_opportunity_bucket(self, post: Post) -> str:
        if not post.source_created_ts:
            return "unknown_age"
        age_seconds = max(0, int(datetime.now(UTC).timestamp()) - int(post.source_created_ts))
        age_days = age_seconds / 86400.0
        if age_days <= self.current_opportunity_max_age_days:
            return "current_opportunity"
        return "evergreen_pain"

    @staticmethod
    def _build_thread_text(title: str, body: str, comments: list[str]) -> str:
        comment_lines = "\n".join(f"- {comment}" for comment in comments)
        return f"Title: {title}\n\nBody:\n{body}\n\nThread comments:\n{comment_lines}".strip()

    @staticmethod
    def _deep_dive_payload(result: DeepDiveResult) -> dict[str, Any]:
        return {
            "workarounds": result.workarounds,
            "competitors": result.competitors,
            "feature_wishlist": result.feature_wishlist,
            "buying_signals": result.buying_signals,
            "icp_hypothesis": result.icp_hypothesis,
            "actionable_summary": result.actionable_summary,
            "raw_payload": result.raw_payload,
        }
