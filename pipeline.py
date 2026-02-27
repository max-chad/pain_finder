from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from budget import BudgetCapReachedError, BudgetGuard
from classifier import Classifier, PainSignal
from db import Database
from openrouter import DeepDiveResult
from scraper import Post, RedditScraper

if TYPE_CHECKING:
    from deduplicator import Deduplicator

logger = logging.getLogger(__name__)


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
    ):
        self.scraper = scraper
        self.classifier = classifier
        self.db = db
        self.reports_dir = reports_dir
        self.deep_dive_wtp_threshold = deep_dive_wtp_threshold
        self.deep_dive_max_comments = deep_dive_max_comments
        self.budget_guard = budget_guard
        self.deduplicator = deduplicator

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
        if self.budget_guard is not None:
            await self.budget_guard.ensure_can_spend("pipeline_analyze")
        elif await self.db.is_llm_paused():
            raise RuntimeError("LLM operations are paused. Use /resume to override.")

        start = perf_counter()
        signals = await self.classifier.classify_batch(posts)

        monetizable_count = 0
        deep_dive_count = 0

        for signal in signals:
            embedding: list[float] | None = None

            if self.deduplicator is not None:
                text = f"{signal.post.title} {signal.post.body}"
                embedding = await self.deduplicator.embedder.embed(text)
                is_dup = await self.deduplicator.find_and_merge(
                    post_id=signal.post.post_id,
                    embedding=embedding,
                    source=signal.post.source,
                )
                if is_dup:
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
                analysis_mode=signal.analysis_mode,
                analysis_payload=signal.analysis_payload,
                emb_vector=embedding,
            )

            if signal.is_monetizable:
                monetizable_count += 1

            if signal.is_monetizable and signal.willingness_to_pay >= self.deep_dive_wtp_threshold:
                existing = await self.db.get_pain_point(signal.post.post_id)
                if existing and existing.get("deep_dive_status") == "completed":
                    continue
                deep_dive = await self.run_deep_dive(
                    post_id=signal.post.post_id,
                    subreddit=signal.post.subreddit,
                    source="auto",
                    title=signal.post.title,
                    body=signal.post.body,
                )
                if deep_dive.status == "completed":
                    deep_dive_count += 1

        report_data = self._build_report_payload(signals=signals, source=source)
        json_path = await self._write_report(run_label=run_label, payload=report_data)

        report_id = await self.db.save_report(
            subreddit=run_scope,
            post_count=len(posts),
            pain_count=len(signals),
            json_path=json_path,
        )
        duration_ms = int((perf_counter() - start) * 1000)
        analysis_run_id = await self.db.record_analysis_run(
            subreddit=run_scope,
            post_count=len(posts),
            pain_count=len(signals),
            monetizable_count=monetizable_count,
            deep_dive_count=deep_dive_count,
            duration_ms=duration_ms,
            report_id=report_id,
        )

        logger.info(
            "analysis_complete stage=analyze source=%s scope=%s analysis_run_id=%s post_count=%d pain_count=%d monetizable_count=%d deep_dive_count=%d duration_ms=%d",
            source,
            run_scope,
            analysis_run_id,
            len(posts),
            len(signals),
            monetizable_count,
            deep_dive_count,
            duration_ms,
        )

        return AnalysisRun(
            subreddit=run_scope,
            post_count=len(posts),
            pain_count=len(signals),
            monetizable_count=monetizable_count,
            deep_dive_count=deep_dive_count,
            signals=signals,
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
                "niche_counts": {},
                "source_counts": {},
                "recurring_blockers": [],
            }

        scored_rows = []
        niche_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        blockers: dict[str, int] = {}

        for row in rows:
            pain_level = int(row.get("pain_level") or 0)
            wtp = int(row.get("willingness_to_pay") or 0)
            score = round((pain_level + wtp) / 2)
            row_copy = dict(row)
            row_copy["weighted_score"] = score
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
                row.get("weighted_score", 0),
                int(row.get("willingness_to_pay") or 0),
                int(row.get("pain_level") or 0),
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
            "niche_counts": niche_counts,
            "source_counts": source_counts,
            "recurring_blockers": recurring_blockers,
        }

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
    def _build_report_payload(*, signals: list[PainSignal], source: str) -> list[dict[str, Any]]:
        return [
            {
                "post_id": signal.post.post_id,
                "title": signal.post.title,
                "url": signal.post.url,
                "source": source,
                "category": signal.category,
                "summary": signal.summary,
                "severity": signal.severity,
                "is_monetizable": signal.is_monetizable,
                "pain_level": signal.pain_level,
                "willingness_to_pay": signal.willingness_to_pay,
                "niche_category": signal.niche_category,
                "competitor_tags": signal.competitor_tags,
                "analysis_mode": signal.analysis_mode,
            }
            for signal in signals
        ]

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
