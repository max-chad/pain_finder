from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, is_dataclass
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
from openrouter import DeepDiveResult
from rejected_noise import (
    DISPLAY_REJECTED_NOISE_LIMIT,
    FETCH_REJECTED_NOISE_LIMIT,
    bounded_rejected_noise_rows,
    rejection_reason_counts,
)
from scraper import Post, RedditScraper

if TYPE_CHECKING:
    from deduplicator import Deduplicator

logger = logging.getLogger(__name__)

PROMOTION_BUYER_AUTHORITY_MIN_SCORE = 0.82
WEAK_SIGNAL_SCORE_CAP = 49.0
OPPORTUNITY_SCORE_WEIGHTS = {
    "intensity": 0.18,
    "frequency": 0.14,
    "wtp": 0.14,
    "buyer_authority": 0.12,
    "current_workaround": 0.10,
    "incumbent_failure": 0.10,
    "urgency": 0.08,
    "evidence_quality": 0.08,
    "recency": 0.06,
}


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
    source_coverage: dict[str, Any] = field(default_factory=dict)
    normalized_frequency: dict[str, Any] = field(default_factory=dict)


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
        semantic_candidate_retrieval_enabled: bool = False,
        semantic_embedder: Any | None = None,
        semantic_candidate_max_per_run: int = 0,
        semantic_candidate_min_similarity: float = 0.22,
        semantic_candidate_max_pool: int = 200,
        min_confidence_for_promotion: float = 0.55,
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
        self.semantic_candidate_retrieval_enabled = bool(semantic_candidate_retrieval_enabled)
        self.semantic_embedder = semantic_embedder
        self.semantic_candidate_max_per_run = max(0, int(semantic_candidate_max_per_run))
        self.semantic_candidate_min_similarity = max(0.0, min(1.0, float(semantic_candidate_min_similarity)))
        self.semantic_candidate_max_pool = max(0, int(semantic_candidate_max_pool))
        self.min_confidence_for_promotion = max(0.0, min(1.0, float(min_confidence_for_promotion)))

    async def analyze_subreddit(self, subreddit: str, limit: int = 100) -> AnalysisRun:
        prior_cursor = await self.db.get_source_ingestion_cursor(source="reddit", subreddit=subreddit, timeframe="day")
        if prior_cursor:
            logger.debug(
                "source_ingestion_cursor_loaded source=reddit subreddit=%s last_seen_created_utc=%s after=%s",
                subreddit,
                prior_cursor.get("last_seen_created_utc"),
                prior_cursor.get("after"),
            )
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
        if self.budget_guard is not None:
            await self.budget_guard.ensure_can_spend("pipeline_analyze")
        elif await self.db.is_llm_paused():
            raise RuntimeError("LLM operations are paused. Use /resume to override.")

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
        screen_stats: dict[str, Any] = {
            "screen_rule_dropped_count": 0,
            "screen_kept_count": len(fresh_posts),
            "screen_capped_count": 0,
            "screen_high_recall_candidate_count": 0,
            "screen_semantic_candidate_count": 0,
            "screen_semantic_scored_count": 0,
            "screen_semantic_dropped_count": 0,
            "screen_semantic_rescued_count": 0,
            "screen_semantic_max_similarity": 0.0,
            "screen_candidate_cap": screening_limit,
        }
        if hasattr(self.classifier, "select_candidates"):
            fresh_posts, screen_stats = await self.classifier.select_candidates(
                fresh_posts,
                max_candidates=screening_limit,
                semantic_embedder=self.semantic_embedder if self.semantic_candidate_retrieval_enabled else None,
                semantic_min_similarity=self.semantic_candidate_min_similarity,
                semantic_max_candidates=self.semantic_candidate_max_per_run if self.semantic_candidate_retrieval_enabled else 0,
                semantic_max_pool=self.semantic_candidate_max_pool,
            )
        elif hasattr(self.classifier, "prescreen_posts"):
            fresh_posts, screen_stats = self.classifier.prescreen_posts(
                fresh_posts,
                max_candidates=screening_limit,
            )
        screen_rule_dropped_count = int(screen_stats.get("screen_rule_dropped_count", 0))
        screen_kept_count = int(screen_stats.get("screen_kept_count", len(fresh_posts)))
        screen_capped_count = int(screen_stats.get("screen_capped_count", 0))
        llm_capped_count = screen_capped_count

        classified_signals = await self.classifier.classify_batch(fresh_posts)
        persisted_signals: list[PainSignal] = []
        classified_count = len(classified_signals)
        inserted_count = 0
        dedup_merged_count = 0
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
                embedding = await self.deduplicator.embedder.embed(text)
                is_dup = await self.deduplicator.find_and_merge(
                    post_id=signal.post.post_id,
                    embedding=embedding,
                    source=source,
                )
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
                is_deleted=signal.post.is_deleted,
                is_removed=signal.post.is_removed,
                body_available=signal.post.body_available,
                deleted_detected_at=signal.post.deleted_detected_at,
                author_hash=signal.post.author_hash,
                opportunity_bucket=opportunity_bucket,
                post_type=signal.post_type,
                first_handness=signal.first_handness,
                buyer_authority=signal.buyer_authority,
                pain_type=signal.pain_type,
                expression_type=signal.expression_type,
                user_context_json=signal.user_context_json,
                intensity_score=signal.intensity_score,
                frequency_signal=signal.frequency_signal,
                urgency=signal.urgency,
                current_workaround=signal.current_workaround,
                wtp_score=signal.wtp_score,
                incumbent_failure=signal.incumbent_failure,
                opportunity_type=signal.opportunity_type,
                evidence_spans=signal.evidence_spans,
                verified_evidence=signal.verified_evidence,
                evidence_quality=signal.evidence_quality,
                evidence_match_rate=signal.evidence_match_rate,
                confidence=signal.confidence,
                uncertainty_reason=signal.uncertainty_reason,
                needs_human_review=signal.needs_human_review,
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
            if signal.post.comments:
                await self.db.upsert_comments(signal.post.comments)
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

        duration_ms = int((perf_counter() - start) * 1000)
        source_coverage = self._build_source_coverage(
            posts=posts,
            source=source,
            scope=run_scope,
            skipped_duplicates=skipped_existing_count + dedup_merged_count,
            duration_ms=duration_ms,
            candidate_generation=screen_stats,
        )
        await self.db.record_source_coverage_run(
            source=source,
            scope=run_scope,
            fetched_posts=source_coverage["fetched_posts"],
            fetched_comments=source_coverage["fetched_comments"],
            skipped_deleted=source_coverage["skipped_deleted"],
            skipped_duplicates=source_coverage["skipped_duplicates"],
            failed_requests=source_coverage["failed_requests"],
            source_method_used=source_coverage["source_method_used"],
            duration_ms=source_coverage["duration_ms"],
        )
        persisted_post_ids = [signal.post.post_id for signal in persisted_signals]
        fetch_errors = []
        if source_coverage["failed_requests"]:
            fetch_errors.append(f"failed_requests:{source_coverage['failed_requests']}")
        await self.db.upsert_source_ingestion_cursor(
            source=source,
            subreddit=run_scope,
            timeframe="day" if source == "reddit" else None,
            after=str(getattr(self.scraper, "last_after", "") or "") or None,
            before=str(getattr(self.scraper, "last_before", "") or "") or None,
            time_window=str(getattr(self.scraper, "last_time_window", "") or "") or None,
            last_seen_created_utc=self._latest_source_created_ts(posts),
            last_success_at=datetime.now(UTC).isoformat(),
            fetch_errors=fetch_errors,
        )
        normalized_frequency: dict[str, Any] = {}
        if persisted_post_ids:
            normalized_frequency = await self.db.calculate_normalized_frequency(
                source=source,
                scope=run_scope,
                post_ids=persisted_post_ids,
            )
            await self.db.update_pain_points_frequency_metrics(
                post_ids=persisted_post_ids,
                metrics=normalized_frequency,
            )

        report_data = self._build_report_payload(
            signals=persisted_signals,
            source=source,
            source_coverage=source_coverage,
            normalized_frequency=normalized_frequency,
        )
        json_path = await self._write_report(run_label=run_label, payload=report_data)

        report_id = await self.db.save_report(
            subreddit=run_scope,
            post_count=len(posts),
            pain_count=inserted_count,
            json_path=json_path,
        )
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
            "screen_kept_count=%d llm_capped_count=%d semantic_rescued_count=%d high_recall_candidate_count=%d "
            "pain_count=%d monetizable_count=%d deep_dive_count=%d "
            "inserted_count=%d dedup_merged_count=%d discarded_non_pain_count=%d primary_success_count=%d "
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
            int(screen_stats.get("screen_semantic_rescued_count", 0)),
            int(screen_stats.get("screen_high_recall_candidate_count", 0)),
            inserted_count,
            monetizable_count,
            deep_dive_count,
            inserted_count,
            dedup_merged_count,
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
            source_coverage=source_coverage,
            normalized_frequency=normalized_frequency,
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
        source_coverage_runs = await self.db.list_source_coverage_runs(scope=subreddit, limit=5)
        rejected_noise_candidates = await self._recent_rejected_noise_candidates(hours=hours, subreddit=subreddit)
        rejected_noise_items = bounded_rejected_noise_rows(
            rejected_noise_candidates,
            limit=DISPLAY_REJECTED_NOISE_LIMIT,
        )
        rejected_noise_counts = rejection_reason_counts(rejected_noise_candidates)
        if not rows:
            return {
                "hours": hours,
                "subreddit": subreddit,
                "total": 0,
                "top_items": [],
                "needs_review_items": [],
                "rejected_noise_items": rejected_noise_items,
                "rejected_noise_counts": rejected_noise_counts,
                "top_clusters": [],
                "niche_counts": {},
                "source_counts": {},
                "source_coverage_runs": source_coverage_runs,
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
            row_copy["verified_evidence"] = self._decode_json_list(row_copy.get("verified_evidence_json"))
            row_copy["evidence_spans"] = self._decode_json_list(row_copy.get("evidence_spans_json"))
            score_components = row_copy.get("score_components_json")
            if isinstance(score_components, str) and score_components.strip():
                try:
                    row_copy["score_components"] = json.loads(score_components)
                except json.JSONDecodeError:
                    row_copy["score_components"] = {}
            elif not isinstance(row_copy.get("score_components"), dict):
                row_copy["score_components"] = {}
            row_source = (row_copy.get("source") or "unknown").strip() or "unknown"
            row_scope = (row_copy.get("subreddit") or subreddit or "global").strip() or "global"
            row_post_id = str(row_copy.get("post_id") or "").strip()
            row_copy["normalized_frequency"] = await self.db.calculate_normalized_frequency(
                source=row_source,
                scope=row_scope,
                post_ids=[row_post_id] if row_post_id else [],
            )
            rejection_reason = self._row_evidence_rejection_reason(row_copy)
            row_copy["promotion_eligible"] = not rejection_reason
            row_copy["evidence_rejection_reason"] = rejection_reason
            scored_rows.append(row_copy)

            niche = (row.get("niche_category") or "Uncategorized").strip() or "Uncategorized"
            niche_counts[niche] = niche_counts.get(niche, 0) + 1
            source_name = (row.get("source") or "unknown").strip() or "unknown"
            source_counts[source_name] = source_counts.get(source_name, 0) + 1

            summary = (row.get("deep_dive_summary") or "").strip()
            if summary:
                blockers[summary] = blockers.get(summary, 0) + 1

        scored_rows.sort(
            key=lambda row: (
                self._row_opportunity_score(row),
                len(row.get("evidence_spans") or []),
                int(row.get("source_created_ts") or 0),
                int(row.get("willingness_to_pay") or 0),
                int(row.get("pain_level") or 0),
            ),
            reverse=True,
        )

        top_rows = [row for row in scored_rows if row.get("promotion_eligible")]
        needs_review_rows = [row for row in scored_rows if not row.get("promotion_eligible")]

        recurring_blockers = [
            item[0]
            for item in sorted(blockers.items(), key=lambda item: item[1], reverse=True)[:5]
        ]
        return {
            "hours": hours,
            "subreddit": subreddit,
            "total": len(rows),
            "top_items": top_rows[:5],
            "needs_review_items": needs_review_rows[:5],
            "rejected_noise_items": rejected_noise_items,
            "rejected_noise_counts": rejected_noise_counts,
            "top_clusters": top_clusters,
            "niche_counts": niche_counts,
            "source_counts": source_counts,
            "source_coverage_runs": source_coverage_runs,
            "recurring_blockers": recurring_blockers,
        }

    async def _recent_rejected_noise_candidates(
        self,
        *,
        hours: int,
        subreddit: str | None,
    ) -> list[dict[str, Any]]:
        if not hasattr(self.db, "get_recent_rejected_noise_candidates"):
            return []
        try:
            if subreddit:
                rows = await self.db.get_recent_rejected_noise_candidates(
                    hours=hours,
                    subreddit=subreddit,
                    limit=FETCH_REJECTED_NOISE_LIMIT,
                )
            else:
                rows = await self.db.get_recent_rejected_noise_candidates(
                    hours=hours,
                    limit=FETCH_REJECTED_NOISE_LIMIT,
                )
        except TypeError:
            return []
        return rows if isinstance(rows, list) else []

    async def _write_report(self, *, run_label: str, payload: list[dict[str, Any]]) -> str:
        os.makedirs(self.reports_dir, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        json_path = os.path.join(self.reports_dir, f"{run_label}_{timestamp}.json")
        tmp_path = f"{json_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as report_file:
                json.dump(payload, report_file, indent=2, ensure_ascii=False)
            os.replace(tmp_path, json_path)
            return json_path
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    @staticmethod
    def _verified_evidence_payload(signal: PainSignal) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for item in signal.verified_evidence:
            if is_dataclass(item):
                payload.append(asdict(item))
            elif isinstance(item, dict):
                payload.append(dict(item))
        return payload

    @staticmethod
    def _verified_evidence_match_type(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("match_type") or "none")
        return str(getattr(item, "match_type", "none") or "none")

    @classmethod
    def _evidence_match_counts(cls, evidence_items: list[Any]) -> tuple[int, int, int, int]:
        exact_count = 0
        fuzzy_count = 0
        none_count = 0
        for item in evidence_items:
            match_type = cls._verified_evidence_match_type(item).strip().lower()
            if match_type == "exact":
                exact_count += 1
            elif match_type == "fuzzy":
                fuzzy_count += 1
            else:
                none_count += 1
        matched_count = exact_count + fuzzy_count
        return exact_count, fuzzy_count, none_count, matched_count

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return False

    @classmethod
    def _score_components_from_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("score_components")
        if isinstance(raw, dict):
            return raw
        raw = row.get("score_components_json")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @classmethod
    def _verified_evidence_from_row(cls, row: dict[str, Any]) -> list[dict[str, Any]]:
        raw = row.get("verified_evidence")
        if raw is None:
            raw = row.get("verified_evidence_json")
        return [item for item in cls._decode_json_list(raw) if isinstance(item, dict)]

    @classmethod
    def _row_evidence_rejection_reason(cls, row: dict[str, Any]) -> str:
        components = cls._score_components_from_row(row)
        component_reason = str(components.get("evidence_rejection_reason") or "").strip()
        if component_reason:
            return component_reason

        exact_count, _, _, _ = cls._evidence_match_counts(cls._verified_evidence_from_row(row))
        if exact_count <= 0:
            return "no_verified_exact_quote"
        if cls._coerce_bool(row.get("needs_human_review")):
            return "needs_human_review"

        first_handness = str(row.get("first_handness") or "unknown").strip().lower()
        try:
            authority_score = float(row.get("buyer_authority_score"))
        except (TypeError, ValueError):
            authority_score = buyer_authority_score(str(row.get("buyer_authority") or "unknown"))
        if first_handness != "first_hand" and authority_score < PROMOTION_BUYER_AUTHORITY_MIN_SCORE:
            return "missing_first_hand_or_buyer_signal"
        return ""

    def _build_source_coverage(
        self,
        *,
        posts: list[Post],
        source: str,
        scope: str,
        skipped_duplicates: int,
        duration_ms: int,
        candidate_generation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_method_used = ""
        failed_requests = 0
        if source == "reddit":
            source_method_used = str(getattr(self.scraper, "last_source_method_used", "") or "").strip()
            failed_requests = int(getattr(self.scraper, "last_failed_requests", 0) or 0)
        if not source_method_used:
            source_method_used = "external" if source != "reddit" else "unknown"
        return {
            "source": source,
            "scope": scope,
            "fetched_posts": len(posts),
            "fetched_comments": sum(len(getattr(post, "comments", []) or []) for post in posts),
            "skipped_deleted": sum(
                1
                for post in posts
                if bool(getattr(post, "is_deleted", False))
                or bool(getattr(post, "is_removed", False))
                or not bool(getattr(post, "body_available", True))
            ),
            "skipped_duplicates": int(skipped_duplicates or 0),
            "failed_requests": failed_requests,
            "source_method_used": source_method_used,
            "duration_ms": int(duration_ms),
            "candidate_generation": dict(candidate_generation or {}),
        }

    @staticmethod
    def _latest_source_created_ts(posts: list[Post]) -> int | None:
        values: list[int] = []
        for post in posts:
            raw = getattr(post, "source_created_ts", None)
            if raw in {None, ""}:
                continue
            try:
                values.append(int(raw))
            except (TypeError, ValueError):
                continue
        return max(values) if values else None

    @staticmethod
    def _build_report_payload(
        *,
        signals: list[PainSignal],
        source: str,
        source_coverage: dict[str, Any] | None = None,
        normalized_frequency: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        coverage_payload = dict(source_coverage or {})
        frequency_payload = dict(normalized_frequency or {})
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
                "author_hash": signal.post.author_hash,
                "is_deleted": signal.post.is_deleted,
                "is_removed": signal.post.is_removed,
                "body_available": signal.post.body_available,
                "deleted_detected_at": signal.post.deleted_detected_at,
                "source_coverage": coverage_payload,
                "normalized_frequency": frequency_payload,
                "pain_mentions_per_1000_posts": frequency_payload.get("pain_mentions_per_1000_posts", 0.0),
                "pain_mentions_per_1000_comments": frequency_payload.get("pain_mentions_per_1000_comments", 0.0),
                "unique_authors_count": frequency_payload.get("unique_authors_count", 0),
                "unique_threads_count": frequency_payload.get("unique_threads_count", 0),
                "weekly_delta": frequency_payload.get("weekly_delta", 0),
                "source_activity_baseline": frequency_payload.get("source_activity_baseline", {}),
                "opportunity_bucket": signal.opportunity_bucket,
                "post_type": signal.post_type,
                "first_handness": signal.first_handness,
                "buyer_authority": signal.buyer_authority,
                "pain_type": signal.pain_type,
                "expression_type": signal.expression_type,
                "user_context": signal.user_context,
                "user_context_json": signal.user_context_json,
                "intensity_score": signal.intensity_score,
                "frequency_signal": signal.frequency_signal,
                "urgency": signal.urgency,
                "current_workaround": signal.current_workaround,
                "wtp_score": signal.wtp_score,
                "incumbent_failure": signal.incumbent_failure,
                "opportunity_type": signal.opportunity_type,
                "evidence_spans": signal.evidence_spans,
                "verified_evidence": AnalysisPipeline._verified_evidence_payload(signal),
                "evidence_quality": signal.evidence_quality,
                "evidence_match_rate": signal.evidence_match_rate,
                "confidence": signal.confidence,
                "uncertainty_reason": signal.uncertainty_reason,
                "needs_human_review": signal.needs_human_review,
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
                "promotion_eligible": signal.promotion_eligible,
                "evidence_rejection_reason": signal.evidence_rejection_reason,
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
        exact_evidence_count, fuzzy_evidence_count, unmatched_evidence_count, matched_evidence_count = self._evidence_match_counts(
            signal.verified_evidence
        )
        if signal.verified_evidence and signal.evidence_match_rate <= 0 and matched_evidence_count > 0:
            signal.evidence_match_rate = round(matched_evidence_count / len(signal.verified_evidence), 3)
        if signal.verified_evidence:
            effective_match_rate = max(0.0, min(1.0, float(signal.evidence_match_rate)))
            evidence_quality_weight = exact_evidence_count + fuzzy_evidence_count * 0.35
            evidence_score = min(1.0, (evidence_quality_weight / 3) * effective_match_rate)
        else:
            effective_match_rate = 0.0
            evidence_score = 0.0
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
            + self._incumbent_failure_factor(signal.incumbent_failure) * 0.35
            + (0.14 if signal.post_type in {"vendor_rant", "tool_comparison"} else 0.0),
        )
        type_penalty = 0.0
        if signal.post_type in {"founder_pitch", "news_analysis"} and signal.first_handness != "first_hand":
            type_penalty += 0.22
        elif signal.post_type == "advice_thread":
            type_penalty += 0.08

        factors = {
            "intensity": self._unit_score(signal.intensity_score or signal.pain_level / 10),
            "frequency": max(self._frequency_signal_factor(signal.frequency_signal), workflow_frequency_score),
            "wtp": self._unit_score(signal.wtp_score or signal.willingness_to_pay / 10),
            "buyer_authority": authority_score,
            "current_workaround": self._current_workaround_factor(signal.current_workaround),
            "incumbent_failure": max(self._incumbent_failure_factor(signal.incumbent_failure), incumbent_failure_score),
            "urgency": self._urgency_factor(signal.urgency),
            "evidence_quality": max(evidence_score, self._evidence_quality_factor(signal.evidence_quality, effective_match_rate)),
            "recency": recency_score,
        }
        factors = {key: round(self._unit_score(value), 3) for key, value in factors.items()}
        penalties = {
            "noise": round(self._noise_penalty(signal), 3),
            "shill_risk": round(self._unit_score(comment_signals["comment_shill_risk"]) * 0.06, 3),
            "solved": round(self._unit_score(solved_penalty) * 0.12, 3),
            "stale": round(self._unit_score(stale_penalty) * 0.10, 3),
            "type": round(self._unit_score(type_penalty) * 0.10, 3),
        }
        weighted_score = sum(factors[key] * OPPORTUNITY_SCORE_WEIGHTS[key] for key in OPPORTUNITY_SCORE_WEIGHTS)
        raw_score = (weighted_score - sum(penalties.values())) * 100
        pre_promotion_score = round(max(0.0, min(100.0, raw_score)), 2)
        has_first_hand_or_buyer_signal = (
            signal.first_handness == "first_hand" or authority_score >= PROMOTION_BUYER_AUTHORITY_MIN_SCORE
        )
        low_confidence = self._has_explicit_confidence(signal) and signal.confidence < self.min_confidence_for_promotion
        if low_confidence:
            signal.needs_human_review = True
            confidence_reason = f"model confidence {signal.confidence:.2f} below promotion threshold {self.min_confidence_for_promotion:.2f}"
            if signal.uncertainty_reason:
                signal.uncertainty_reason = f"{signal.uncertainty_reason}; {confidence_reason}"
            else:
                signal.uncertainty_reason = confidence_reason
        if exact_evidence_count <= 0:
            evidence_rejection_reason = "no_verified_exact_quote"
        elif signal.needs_human_review:
            evidence_rejection_reason = "low_confidence_needs_review" if low_confidence else "needs_human_review"
        elif not has_first_hand_or_buyer_signal:
            evidence_rejection_reason = "missing_first_hand_or_buyer_signal"
        else:
            evidence_rejection_reason = ""
        promotion_eligible = not evidence_rejection_reason
        opportunity_score = pre_promotion_score if promotion_eligible else min(pre_promotion_score, WEAK_SIGNAL_SCORE_CAP)

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
        signal.promotion_eligible = promotion_eligible
        signal.evidence_rejection_reason = evidence_rejection_reason
        signal.score_components = {
            "weights": dict(OPPORTUNITY_SCORE_WEIGHTS),
            "factors": factors,
            "penalties": penalties,
            "raw_score": pre_promotion_score,
            "pre_promotion_score": pre_promotion_score,
            "buyer_authority_score": signal.buyer_authority_score,
            "first_handness_score": round(first_hand_score, 3),
            "workflow_frequency_score": signal.workflow_frequency_score,
            "impact_score": signal.impact_score,
            "consensus_score": signal.consensus_score,
            "incumbent_failure_score": signal.incumbent_failure_score,
            "recency_score": signal.recency_score,
            "stale_penalty": signal.stale_penalty,
            "solved_penalty": signal.solved_penalty,
            "raw_opportunity_score": pre_promotion_score,
            "opportunity_score": signal.opportunity_score,
            "promotion_eligible": signal.promotion_eligible,
            "evidence_rejection_reason": signal.evidence_rejection_reason,
            "confidence": round(float(signal.confidence or 0.0), 3),
            "min_confidence_for_promotion": self.min_confidence_for_promotion,
            "low_confidence": low_confidence,
            "evidence_match_rate": round(effective_match_rate, 3),
            "exact_evidence_count": exact_evidence_count,
            "fuzzy_evidence_count": fuzzy_evidence_count,
            "unmatched_evidence_count": unmatched_evidence_count,
            "matched_evidence_count": matched_evidence_count,
            "evidence_score": round(evidence_score, 3),
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

    @staticmethod
    def _unit_score(value: Any) -> float:
        if isinstance(value, bool):
            return 0.0
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric != numeric:
            return 0.0
        return max(0.0, min(1.0, numeric))

    @classmethod
    def _frequency_signal_factor(cls, value: Any) -> float:
        if not isinstance(value, str):
            return cls._unit_score(value)
        normalized = value.strip().lower()
        if normalized in {"trend", "repeated_multi_source"}:
            return 1.0
        if normalized in {"repeated_cross_thread", "cross_thread"}:
            return 0.78
        if normalized in {"thread_consensus", "multi_comment"}:
            return 0.58
        if normalized in {"single", "one_off", "unknown", ""}:
            return 0.18
        try:
            return cls._unit_score(float(normalized))
        except ValueError:
            return 0.35

    @classmethod
    def _urgency_factor(cls, value: Any) -> float:
        if isinstance(value, int | float) and not isinstance(value, bool):
            numeric = float(value)
            return cls._unit_score(numeric / 10 if numeric > 1 else numeric)
        normalized = str(value or "").strip().lower().replace(" ", "_")
        mapping = {
            "none": 0.0,
            "unknown": 0.0,
            "low": 0.2,
            "mild": 0.25,
            "medium": 0.5,
            "active_blocker": 0.78,
            "blocked": 0.78,
            "urgent": 0.86,
            "high": 0.86,
            "revenue_critical": 1.0,
            "critical": 1.0,
        }
        if normalized in mapping:
            return mapping[normalized]
        try:
            numeric = float(normalized)
        except ValueError:
            return 0.35
        return cls._unit_score(numeric / 10 if numeric > 1 else numeric)

    @staticmethod
    def _current_workaround_factor(value: Any) -> float:
        normalized = str(value or "").strip().lower().replace(" ", "_")
        if normalized in {"", "none", "no", "unknown", "not_stated"}:
            return 0.0
        if any(marker in normalized for marker in ("spreadsheet", "csv", "manual", "email", "slack", "copy", "reconcile")):
            return 0.85
        if any(marker in normalized for marker in ("paid_tool", "outsourced", "consultant", "custom_script")):
            return 1.0
        if normalized in {"weak", "partial"}:
            return 0.35
        return 0.55

    @staticmethod
    def _incumbent_failure_factor(value: Any) -> float:
        normalized = str(value or "").strip().lower().replace(" ", "_")
        if normalized in {"", "none", "no", "unknown", "not_stated"}:
            return 0.0
        if normalized in {"weak", "partial"}:
            return 0.35
        if any(marker in normalized for marker in ("explicit_competitor_failure", "switching", "broken", "fails", "lag", "data_loss", "duplicate", "sync")):
            return 1.0
        if any(marker in normalized for marker in ("expensive", "slow", "manual", "missing")):
            return 0.72
        return 0.55

    @staticmethod
    def _evidence_quality_factor(quality: Any, match_rate: float) -> float:
        normalized = str(quality or "").strip().lower()
        base = {
            "linked_multi_source": 1.0,
            "multi_quote": 1.0,
            "exact_quote": 0.86,
            "weak_quote": 0.35,
            "no_quote": 0.0,
        }.get(normalized, 0.0)
        return base * max(0.0, min(1.0, float(match_rate or 0.0)))

    @staticmethod
    def _noise_penalty(signal: PainSignal) -> float:
        penalty = 0.0
        if not signal.is_monetizable:
            penalty += 0.15
        if signal.post_type in {"founder_pitch", "news_analysis"}:
            penalty += 0.08
        if signal.pain_level <= 2 and signal.willingness_to_pay <= 2:
            penalty += 0.06
        return min(0.25, penalty)

    @staticmethod
    def _has_explicit_confidence(signal: PainSignal) -> bool:
        if signal.confidence > 0:
            return True
        payload = signal.analysis_payload
        return isinstance(payload, dict) and "confidence" in payload

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
        if not signal.is_monetizable:
            return "not_monetizable"
        if not signal.promotion_eligible:
            return "evidence_needs_review"
        if signal.willingness_to_pay < self.deep_dive_wtp_threshold:
            return "below_wtp_threshold"
        if getattr(self.classifier, "openrouter", None) is None:
            return "openrouter_unconfigured"
        if existing and existing.get("deep_dive_status") == "completed":
            return "already_completed"
        return None

    @staticmethod
    def _decode_json_list(raw: Any) -> list[Any]:
        if isinstance(raw, list):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def _row_opportunity_score(row: dict[str, Any]) -> float:
        raw = row.get("opportunity_score")
        try:
            if raw is not None:
                return round(float(raw), 2)
        except (TypeError, ValueError):
            pass
        pain_level = int(row.get("pain_level") or 0)
        wtp = int(row.get("willingness_to_pay") or 0)
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
