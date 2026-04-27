import json
import logging
import math
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from typing import Any

import aiosqlite

from feedback import build_feedback_label_review_row, empty_feedback_summary, normalize_feedback_value
from rejected_noise import annotate_rejected_noise_rows, sort_rejected_noise_rows

logger = logging.getLogger(__name__)

PAIN_POINT_STATUSES = {"new", "favorite", "discarded", "merged"}
DEEP_DIVE_STATUSES = {"not_requested", "queued", "running", "completed", "failed"}
OPPORTUNITY_BUCKETS = {"current_opportunity", "evergreen_pain", "unknown_age"}

CREATE_PAIN_POINTS = """
CREATE TABLE IF NOT EXISTS pain_points (
    id INTEGER PRIMARY KEY,
    subreddit TEXT NOT NULL,
    post_id TEXT UNIQUE NOT NULL,
    url TEXT,
    title TEXT,
    body TEXT,
    category TEXT,
    summary TEXT,
    severity TEXT,
    is_monetizable INTEGER DEFAULT 0,
    pain_level INTEGER DEFAULT 0,
    willingness_to_pay INTEGER DEFAULT 0,
    niche_category TEXT DEFAULT '',
    competitor_tags TEXT DEFAULT '[]',
    source TEXT DEFAULT 'reddit',
    source_created_at TEXT,
    source_created_ts INTEGER,
    author_name TEXT,
    is_deleted INTEGER DEFAULT 0,
    is_removed INTEGER DEFAULT 0,
    body_available INTEGER DEFAULT 1,
    deleted_detected_at TEXT,
    author_hash TEXT,
    opportunity_bucket TEXT DEFAULT 'unknown_age',
    post_type TEXT DEFAULT 'advice_thread',
    first_handness TEXT DEFAULT 'unknown',
    buyer_authority TEXT DEFAULT 'unknown',
    pain_type TEXT DEFAULT 'unknown',
    expression_type TEXT DEFAULT 'unknown',
    user_context_json TEXT DEFAULT '{}',
    intensity_score REAL DEFAULT 0,
    frequency_signal TEXT DEFAULT 'single',
    urgency TEXT DEFAULT 'none',
    current_workaround TEXT DEFAULT '',
    wtp_score REAL DEFAULT 0,
    incumbent_failure TEXT DEFAULT '',
    opportunity_type TEXT DEFAULT 'unknown',
    evidence_spans_json TEXT DEFAULT '[]',
    verified_evidence_json TEXT DEFAULT '[]',
    evidence_quality TEXT DEFAULT 'no_quote',
    evidence_match_rate REAL DEFAULT 0,
    confidence REAL DEFAULT 0,
    uncertainty_reason TEXT DEFAULT '',
    needs_human_review INTEGER DEFAULT 0,
    comment_sample_json TEXT DEFAULT '[]',
    buyer_authority_score REAL DEFAULT 0.55,
    workflow_frequency_score REAL DEFAULT 0,
    impact_score REAL DEFAULT 0,
    consensus_score REAL DEFAULT 0,
    incumbent_failure_score REAL DEFAULT 0,
    recency_score REAL DEFAULT 0,
    stale_penalty REAL DEFAULT 0,
    solved_penalty REAL DEFAULT 0,
    opportunity_score REAL DEFAULT 0,
    score_components_json TEXT DEFAULT '{}',
    comment_consensus_count INTEGER DEFAULT 0,
    comment_same_here_count INTEGER DEFAULT 0,
    comment_workaround_count INTEGER DEFAULT 0,
    comment_tool_mentions_json TEXT DEFAULT '[]',
    comment_shill_risk REAL DEFAULT 0,
    triage_status TEXT DEFAULT 'new',
    analysis_mode TEXT DEFAULT 'legacy',
    deep_dive_status TEXT DEFAULT 'not_requested',
    deep_dive_summary TEXT,
    analysis_payload_json TEXT,
    pain_mentions_per_1000_posts REAL DEFAULT 0,
    pain_mentions_per_1000_comments REAL DEFAULT 0,
    unique_authors_count INTEGER DEFAULT 0,
    unique_threads_count INTEGER DEFAULT 0,
    weekly_delta INTEGER DEFAULT 0,
    source_activity_baseline_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_MONITORED = """
CREATE TABLE IF NOT EXISTS monitored_subreddits (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    interval_hours INTEGER NOT NULL,
    last_checked TEXT,
    active INTEGER DEFAULT 1
)"""

CREATE_REPORTS = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    subreddit TEXT NOT NULL,
    run_at TEXT DEFAULT (datetime('now')),
    post_count INTEGER,
    pain_count INTEGER,
    json_path TEXT
)"""

CREATE_DEEP_DIVES = """
CREATE TABLE IF NOT EXISTS deep_dives (
    id INTEGER PRIMARY KEY,
    post_id TEXT UNIQUE NOT NULL,
    subreddit TEXT NOT NULL,
    source TEXT DEFAULT 'auto',
    status TEXT NOT NULL,
    payload_json TEXT,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_ANALYSIS_RUNS = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    subreddit TEXT NOT NULL,
    post_count INTEGER NOT NULL,
    pain_count INTEGER NOT NULL,
    monetizable_count INTEGER NOT NULL,
    deep_dive_count INTEGER NOT NULL,
    skipped_existing_count INTEGER DEFAULT 0,
    dedup_merged_count INTEGER DEFAULT 0,
    screen_rule_dropped_count INTEGER DEFAULT 0,
    screen_kept_count INTEGER DEFAULT 0,
    screen_capped_count INTEGER DEFAULT 0,
    duration_ms INTEGER,
    report_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_COMMENTS = """
CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    parent_id TEXT,
    body TEXT,
    body_hash TEXT,
    author_hash TEXT,
    score INTEGER DEFAULT 0,
    created_utc INTEGER,
    depth INTEGER DEFAULT 0,
    is_op INTEGER DEFAULT 0,
    is_deleted INTEGER DEFAULT 0,
    is_removed INTEGER DEFAULT 0,
    body_available INTEGER DEFAULT 1,
    deleted_detected_at TEXT,
    permalink TEXT,
    fetched_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_SOURCE_INGESTION_CURSORS = """
CREATE TABLE IF NOT EXISTS source_ingestion_cursors (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    subreddit TEXT,
    feed TEXT,
    query TEXT,
    timeframe TEXT,
    after TEXT,
    before TEXT,
    time_window TEXT,
    last_seen_created_utc INTEGER,
    last_success_at TEXT,
    fetch_errors_json TEXT DEFAULT '[]',
    UNIQUE(source, subreddit, feed, query, timeframe)
)"""

CREATE_SOURCE_COVERAGE_RUNS = """
CREATE TABLE IF NOT EXISTS source_coverage_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    scope TEXT NOT NULL,
    fetched_posts INTEGER DEFAULT 0,
    fetched_comments INTEGER DEFAULT 0,
    skipped_deleted INTEGER DEFAULT 0,
    skipped_duplicates INTEGER DEFAULT 0,
    failed_requests INTEGER DEFAULT 0,
    source_method_used TEXT,
    duration_ms INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_PAIN_POINT_COMPETITORS = """
CREATE TABLE IF NOT EXISTS pain_point_competitors (
    post_id TEXT NOT NULL,
    competitor_tag TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (post_id, competitor_tag)
)"""

CREATE_MACRO_TREND_RUNS = """
CREATE TABLE IF NOT EXISTS macro_trend_runs (
    id INTEGER PRIMARY KEY,
    window_days INTEGER NOT NULL,
    candidate_count INTEGER NOT NULL,
    cluster_count INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_MACRO_TREND_CLUSTERS = """
CREATE TABLE IF NOT EXISTS macro_trend_clusters (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    canonical_key TEXT,
    cluster_key TEXT,
    label TEXT,
    summary TEXT,
    estimated_monetization_signal TEXT,
    item_count INTEGER NOT NULL,
    aggregate_wtp REAL NOT NULL,
    fresh_post_count INTEGER DEFAULT 0,
    evergreen_post_count INTEGER DEFAULT 0,
    median_buyer_authority REAL DEFAULT 0,
    incumbents_json TEXT DEFAULT '[]',
    avg_opportunity_score REAL DEFAULT 0,
    pain_mentions_per_1000_posts REAL DEFAULT 0,
    pain_mentions_per_1000_comments REAL DEFAULT 0,
    unique_authors_count INTEGER DEFAULT 0,
    unique_threads_count INTEGER DEFAULT 0,
    weekly_delta INTEGER DEFAULT 0,
    source_activity_baseline_json TEXT DEFAULT '{}',
    latest_source_created_ts INTEGER,
    cluster_stability_score REAL DEFAULT 0,
    representative_examples_json TEXT DEFAULT '[]',
    verified_quote_count INTEGER DEFAULT 0,
    independent_source_count INTEGER DEFAULT 0,
    unique_author_count INTEGER DEFAULT 0,
    normalized_frequency_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_MACRO_TREND_MEMBERS = """
CREATE TABLE IF NOT EXISTS macro_trend_members (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    cluster_id INTEGER NOT NULL,
    post_id TEXT NOT NULL,
    similarity REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_LLM_USAGE_EVENTS = """
CREATE TABLE IF NOT EXISTS llm_usage_events (
    id INTEGER PRIMARY KEY,
    model TEXT NOT NULL,
    operation TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    post_id TEXT,
    prompt_hash TEXT,
    fallback_reason TEXT,
    schema_version TEXT,
    provider TEXT,
    request_path TEXT,
    candidate_stage TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_RUNTIME_FLAGS = """
CREATE TABLE IF NOT EXISTS runtime_flags (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    llm_paused INTEGER DEFAULT 0,
    pause_reason TEXT,
    pause_day TEXT,
    resume_override_until TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_LLM_RESPONSE_CACHE = """
CREATE TABLE IF NOT EXISTS llm_response_cache (
    cache_key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_GTM_ASSETS = """
CREATE TABLE IF NOT EXISTS gtm_assets (
    id INTEGER PRIMARY KEY,
    post_id TEXT NOT NULL,
    model TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_FEEDBACK_EVENTS = """
CREATE TABLE IF NOT EXISTS feedback_events (
    id INTEGER PRIMARY KEY,
    post_id TEXT NOT NULL,
    feedback_value TEXT NOT NULL,
    source TEXT DEFAULT 'manual',
    actor_id TEXT,
    note TEXT,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(post_id) REFERENCES pain_points(post_id)
)"""

CREATE_LABEL_REVIEW_QUEUE = """
CREATE TABLE IF NOT EXISTS label_review_queue (
    id INTEGER PRIMARY KEY,
    feedback_event_id INTEGER UNIQUE NOT NULL,
    post_id TEXT NOT NULL,
    review_status TEXT DEFAULT 'pending',
    review_payload_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(feedback_event_id) REFERENCES feedback_events(id),
    FOREIGN KEY(post_id) REFERENCES pain_points(post_id)
)"""

CREATE_SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pain_points_subreddit_created_at ON pain_points(subreddit, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pain_points_wtp ON pain_points(willingness_to_pay DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pain_points_triage_status ON pain_points(triage_status)",
    "CREATE INDEX IF NOT EXISTS idx_pain_points_source ON pain_points(source)",
    "CREATE INDEX IF NOT EXISTS idx_pain_points_author_hash ON pain_points(author_hash)",
    "CREATE INDEX IF NOT EXISTS idx_pain_points_opportunity_bucket ON pain_points(opportunity_bucket)",
    "CREATE INDEX IF NOT EXISTS idx_pain_points_source_created_ts ON pain_points(source_created_ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pain_points_opportunity_score ON pain_points(opportunity_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reports_subreddit_run_at ON reports(subreddit, run_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_deep_dives_post_id ON deep_dives(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_runs_created_at ON analysis_runs(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id, created_utc DESC)",
    "CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_comments_author_hash ON comments(author_hash)",
    "CREATE INDEX IF NOT EXISTS idx_comments_body_hash ON comments(body_hash)",
    "CREATE INDEX IF NOT EXISTS idx_source_cursors_key ON source_ingestion_cursors(source, subreddit, feed, query, timeframe)",
    "CREATE INDEX IF NOT EXISTS idx_source_coverage_scope ON source_coverage_runs(source, scope, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pain_point_competitors_tag ON pain_point_competitors(competitor_tag)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_clusters_run ON macro_trend_clusters(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_clusters_canonical ON macro_trend_clusters(canonical_key)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_members_run ON macro_trend_members(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_members_post ON macro_trend_members(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_llm_usage_events_created ON llm_usage_events(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_llm_usage_events_stage ON llm_usage_events(candidate_stage, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_llm_response_cache_updated ON llm_response_cache(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_gtm_assets_post ON gtm_assets(post_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_events_post ON feedback_events(post_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_events_value ON feedback_events(feedback_value, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_label_review_queue_status ON label_review_queue(review_status, created_at DESC)",
]

PAIN_POINT_COLUMNS = {
    "is_monetizable": "INTEGER DEFAULT 0",
    "pain_level": "INTEGER DEFAULT 0",
    "willingness_to_pay": "INTEGER DEFAULT 0",
    "niche_category": "TEXT DEFAULT ''",
    "competitor_tags": "TEXT DEFAULT '[]'",
    "source": "TEXT DEFAULT 'reddit'",
    "source_created_at": "TEXT",
    "source_created_ts": "INTEGER",
    "author_name": "TEXT",
    "is_deleted": "INTEGER DEFAULT 0",
    "is_removed": "INTEGER DEFAULT 0",
    "body_available": "INTEGER DEFAULT 1",
    "deleted_detected_at": "TEXT",
    "author_hash": "TEXT",
    "opportunity_bucket": "TEXT DEFAULT 'unknown_age'",
    "post_type": "TEXT DEFAULT 'advice_thread'",
    "first_handness": "TEXT DEFAULT 'unknown'",
    "buyer_authority": "TEXT DEFAULT 'unknown'",
    "pain_type": "TEXT DEFAULT 'unknown'",
    "expression_type": "TEXT DEFAULT 'unknown'",
    "user_context_json": "TEXT DEFAULT '{}'",
    "intensity_score": "REAL DEFAULT 0",
    "frequency_signal": "TEXT DEFAULT 'single'",
    "urgency": "TEXT DEFAULT 'none'",
    "current_workaround": "TEXT DEFAULT ''",
    "wtp_score": "REAL DEFAULT 0",
    "incumbent_failure": "TEXT DEFAULT ''",
    "opportunity_type": "TEXT DEFAULT 'unknown'",
    "evidence_spans_json": "TEXT DEFAULT '[]'",
    "verified_evidence_json": "TEXT DEFAULT '[]'",
    "evidence_quality": "TEXT DEFAULT 'no_quote'",
    "evidence_match_rate": "REAL DEFAULT 0",
    "confidence": "REAL DEFAULT 0",
    "uncertainty_reason": "TEXT DEFAULT ''",
    "needs_human_review": "INTEGER DEFAULT 0",
    "comment_sample_json": "TEXT DEFAULT '[]'",
    "buyer_authority_score": "REAL DEFAULT 0.55",
    "workflow_frequency_score": "REAL DEFAULT 0",
    "impact_score": "REAL DEFAULT 0",
    "consensus_score": "REAL DEFAULT 0",
    "incumbent_failure_score": "REAL DEFAULT 0",
    "recency_score": "REAL DEFAULT 0",
    "stale_penalty": "REAL DEFAULT 0",
    "solved_penalty": "REAL DEFAULT 0",
    "opportunity_score": "REAL DEFAULT 0",
    "score_components_json": "TEXT DEFAULT '{}'",
    "comment_consensus_count": "INTEGER DEFAULT 0",
    "comment_same_here_count": "INTEGER DEFAULT 0",
    "comment_workaround_count": "INTEGER DEFAULT 0",
    "comment_tool_mentions_json": "TEXT DEFAULT '[]'",
    "comment_shill_risk": "REAL DEFAULT 0",
    "triage_status": "TEXT DEFAULT 'new'",
    "analysis_mode": "TEXT DEFAULT 'legacy'",
    "deep_dive_status": "TEXT DEFAULT 'not_requested'",
    "deep_dive_summary": "TEXT",
    "analysis_payload_json": "TEXT",
    "pain_mentions_per_1000_posts": "REAL DEFAULT 0",
    "pain_mentions_per_1000_comments": "REAL DEFAULT 0",
    "unique_authors_count": "INTEGER DEFAULT 0",
    "unique_threads_count": "INTEGER DEFAULT 0",
    "weekly_delta": "INTEGER DEFAULT 0",
    "source_activity_baseline_json": "TEXT DEFAULT '{}'",
    "emb_vector": "TEXT",
    "cross_source_count": "INTEGER DEFAULT 1",
    "cross_source_ids": "TEXT DEFAULT '[]'",
}

ANALYSIS_RUN_COLUMNS = {
    "skipped_existing_count": "INTEGER DEFAULT 0",
    "dedup_merged_count": "INTEGER DEFAULT 0",
    "screen_rule_dropped_count": "INTEGER DEFAULT 0",
    "screen_kept_count": "INTEGER DEFAULT 0",
    "screen_capped_count": "INTEGER DEFAULT 0",
}

LLM_USAGE_EVENT_COLUMNS = {
    "prompt_hash": "TEXT",
    "fallback_reason": "TEXT",
    "schema_version": "TEXT",
    "provider": "TEXT",
    "request_path": "TEXT",
    "candidate_stage": "TEXT",
}

MACRO_TREND_CLUSTER_COLUMNS = {
    "canonical_key": "TEXT",
    "fresh_post_count": "INTEGER DEFAULT 0",
    "evergreen_post_count": "INTEGER DEFAULT 0",
    "median_buyer_authority": "REAL DEFAULT 0",
    "incumbents_json": "TEXT DEFAULT '[]'",
    "avg_opportunity_score": "REAL DEFAULT 0",
    "pain_mentions_per_1000_posts": "REAL DEFAULT 0",
    "pain_mentions_per_1000_comments": "REAL DEFAULT 0",
    "unique_authors_count": "INTEGER DEFAULT 0",
    "unique_threads_count": "INTEGER DEFAULT 0",
    "weekly_delta": "INTEGER DEFAULT 0",
    "source_activity_baseline_json": "TEXT DEFAULT '{}'",
    "latest_source_created_ts": "INTEGER",
    "cluster_stability_score": "REAL DEFAULT 0",
    "representative_examples_json": "TEXT DEFAULT '[]'",
    "verified_quote_count": "INTEGER DEFAULT 0",
    "independent_source_count": "INTEGER DEFAULT 0",
    "unique_author_count": "INTEGER DEFAULT 0",
    "normalized_frequency_json": "TEXT DEFAULT '{}'",
}

COMMENT_COLUMNS = {
    "is_removed": "INTEGER DEFAULT 0",
    "body_available": "INTEGER DEFAULT 1",
    "deleted_detected_at": "TEXT",
}


class Database:
    def __init__(self, path: str = "pain_finder.db"):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._apply_pragmas()

        await self._conn.execute(CREATE_PAIN_POINTS)
        await self._conn.execute(CREATE_MONITORED)
        await self._conn.execute(CREATE_REPORTS)
        await self._conn.execute(CREATE_DEEP_DIVES)
        await self._conn.execute(CREATE_ANALYSIS_RUNS)
        await self._conn.execute(CREATE_COMMENTS)
        await self._conn.execute(CREATE_SOURCE_INGESTION_CURSORS)
        await self._conn.execute(CREATE_SOURCE_COVERAGE_RUNS)
        await self._conn.execute(CREATE_PAIN_POINT_COMPETITORS)
        await self._conn.execute(CREATE_MACRO_TREND_RUNS)
        await self._conn.execute(CREATE_MACRO_TREND_CLUSTERS)
        await self._conn.execute(CREATE_MACRO_TREND_MEMBERS)
        await self._conn.execute(CREATE_LLM_USAGE_EVENTS)
        await self._conn.execute(CREATE_RUNTIME_FLAGS)
        await self._conn.execute(CREATE_LLM_RESPONSE_CACHE)
        await self._conn.execute(CREATE_GTM_ASSETS)
        await self._conn.execute(CREATE_FEEDBACK_EVENTS)
        await self._conn.execute(CREATE_LABEL_REVIEW_QUEUE)
        await self._conn.execute(CREATE_SCHEMA_MIGRATIONS)

        await self._run_migrations()
        for query in CREATE_INDEXES:
            await self._conn.execute(query)
        await self._ensure_runtime_flags_row()
        await self._conn.commit()

    async def _apply_pragmas(self) -> None:
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._conn.execute("PRAGMA busy_timeout=5000;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")

    async def _run_migrations(self) -> None:
        pain_point_migrations = [
            "2026_02_24_expand_pain_points",
            "2026_02_25_phase_5_8_expansion",
            "2026_02_27_cross_source_dedup",
            "2026_04_22_source_context_and_opportunity_bucket",
            "2026_04_26_verified_evidence_fields",
            "2026_04_26_wave3_comments_coverage_frequency",
            "2026_04_27_wave5_taxonomy_scoring",
        ]
        for migration_name in pain_point_migrations:
            if await self._is_migration_applied(migration_name):
                continue
            for column_name, ddl in PAIN_POINT_COLUMNS.items():
                await self._ensure_column("pain_points", column_name, ddl)
            await self._mark_migration_applied(migration_name)

        analysis_run_migration = "2026_04_15_analysis_run_efficiency_metrics"
        if not await self._is_migration_applied(analysis_run_migration):
            for column_name in ["skipped_existing_count", "dedup_merged_count"]:
                await self._ensure_column("analysis_runs", column_name, ANALYSIS_RUN_COLUMNS[column_name])
            await self._mark_migration_applied(analysis_run_migration)

        analysis_run_screening_migration = "2026_04_22_analysis_run_screening_metrics"
        if not await self._is_migration_applied(analysis_run_screening_migration):
            for column_name in ["screen_rule_dropped_count", "screen_kept_count", "screen_capped_count"]:
                await self._ensure_column("analysis_runs", column_name, ANALYSIS_RUN_COLUMNS[column_name])
            await self._mark_migration_applied(analysis_run_screening_migration)

        llm_usage_migration = "2026_04_22_llm_usage_lineage"
        if not await self._is_migration_applied(llm_usage_migration):
            for column_name, ddl in LLM_USAGE_EVENT_COLUMNS.items():
                await self._ensure_column("llm_usage_events", column_name, ddl)
            await self._mark_migration_applied(llm_usage_migration)

        canonical_cluster_migration = "2026_04_22_canonical_pain_clusters"
        if not await self._is_migration_applied(canonical_cluster_migration):
            for column_name, ddl in MACRO_TREND_CLUSTER_COLUMNS.items():
                await self._ensure_column("macro_trend_clusters", column_name, ddl)
            await self._mark_migration_applied(canonical_cluster_migration)

        macro_frequency_migration = "2026_04_26_macro_cluster_frequency_metrics"
        if not await self._is_migration_applied(macro_frequency_migration):
            for column_name, ddl in MACRO_TREND_CLUSTER_COLUMNS.items():
                await self._ensure_column("macro_trend_clusters", column_name, ddl)
            await self._mark_migration_applied(macro_frequency_migration)

        wave6_cluster_foundations_migration = "2026_04_27_wave6_verified_cluster_foundations"
        if not await self._is_migration_applied(wave6_cluster_foundations_migration):
            for column_name, ddl in MACRO_TREND_CLUSTER_COLUMNS.items():
                await self._ensure_column("macro_trend_clusters", column_name, ddl)
            await self._mark_migration_applied(wave6_cluster_foundations_migration)

        comment_availability_migration = "2026_04_26_comment_availability_flags"
        if not await self._is_migration_applied(comment_availability_migration):
            for column_name, ddl in COMMENT_COLUMNS.items():
                await self._ensure_column("comments", column_name, ddl)
            await self._mark_migration_applied(comment_availability_migration)

        feedback_loop_migration = "2026_04_27_wave7_feedback_loop"
        if not await self._is_migration_applied(feedback_loop_migration):
            await self._mark_migration_applied(feedback_loop_migration)

    async def _is_migration_applied(self, name: str) -> bool:
        async with self._conn.execute("SELECT 1 FROM schema_migrations WHERE name = ? LIMIT 1", (name,)) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def _mark_migration_applied(self, name: str) -> None:
        await self._conn.execute("INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)", (name,))

    async def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        async with self._conn.execute(f"PRAGMA table_info({table})") as cursor:
            columns = await cursor.fetchall()
        existing = {row[1] for row in columns}
        if column in existing:
            return
        await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    async def _ensure_runtime_flags_row(self) -> None:
        await self._conn.execute("INSERT OR IGNORE INTO runtime_flags (id, llm_paused) VALUES (1, 0)")

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @staticmethod
    def _normalize_competitor_tags(tags: list[str] | None) -> list[str]:
        if not tags:
            return []
        out = []
        seen = set()
        for item in tags:
            if not isinstance(item, str):
                continue
            clean = item.strip().lower()
            if not clean:
                continue
            if len(clean) > 64:
                clean = clean[:64]
            if clean in seen:
                continue
            seen.add(clean)
            out.append(clean)
        return out

    @staticmethod
    def _coerce_unit_float(value: Any) -> float:
        if isinstance(value, bool):
            return 0.0
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(numeric):
            return 0.0
        return round(max(0.0, min(1.0, numeric)), 3)

    @staticmethod
    def _coerce_bool_int(value: Any) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return int(bool(value))
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return 1
            if normalized in {"0", "false", "no", "n", "off", ""}:
                return 0
        return 0

    @staticmethod
    def _normalize_verified_evidence(items: list[Any] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in items or []:
            if is_dataclass(item):
                raw = asdict(item)
            elif isinstance(item, dict):
                raw = dict(item)
            else:
                continue
            quote = str(raw.get("quote") or "").strip()[:240]
            if not quote:
                continue
            match_type = str(raw.get("match_type") or "none").strip().lower()
            if match_type not in {"exact", "fuzzy", "none"}:
                match_type = "none"
            try:
                match_confidence = Database._coerce_unit_float(raw.get("match_confidence"))
            except (TypeError, ValueError):
                match_confidence = 0.0
            created_utc = raw.get("created_utc")
            if created_utc is not None:
                try:
                    created_utc = int(created_utc)
                except (TypeError, ValueError):
                    created_utc = None
            normalized.append(
                {
                    "quote": quote,
                    "source_type": str(raw.get("source_type") or "").strip()[:32],
                    "post_id": str(raw.get("post_id") or "").strip()[:128],
                    "comment_id": str(raw.get("comment_id")).strip()[:128] if raw.get("comment_id") is not None else None,
                    "permalink": str(raw.get("permalink") or "").strip()[:500],
                    "match_type": match_type,
                    "match_confidence": match_confidence,
                    "created_utc": created_utc,
                }
            )
            if len(normalized) >= 10:
                break
        return normalized

    async def _replace_competitor_tags(self, post_id: str, tags: list[str]) -> None:
        await self._conn.execute("DELETE FROM pain_point_competitors WHERE post_id = ?", (post_id,))
        for tag in tags:
            await self._conn.execute(
                "INSERT OR IGNORE INTO pain_point_competitors (post_id, competitor_tag) VALUES (?, ?)",
                (post_id, tag),
            )

    async def insert_pain_point(
        self,
        *,
        subreddit: str,
        post_id: str,
        url: str,
        title: str,
        body: str,
        category: str,
        summary: str,
        severity: str,
        is_monetizable: bool = False,
        pain_level: int = 0,
        willingness_to_pay: int = 0,
        niche_category: str = "",
        competitor_tags: list[str] | None = None,
        source: str = "reddit",
        source_created_at: str | None = None,
        source_created_ts: int | None = None,
        author_name: str | None = None,
        is_deleted: bool = False,
        is_removed: bool = False,
        body_available: bool = True,
        deleted_detected_at: str | None = None,
        author_hash: str | None = None,
        opportunity_bucket: str = "unknown_age",
        post_type: str = "advice_thread",
        first_handness: str = "unknown",
        buyer_authority: str = "unknown",
        pain_type: str = "unknown",
        expression_type: str = "unknown",
        user_context_json: dict[str, Any] | None = None,
        intensity_score: float = 0.0,
        frequency_signal: str = "single",
        urgency: int | str = "none",
        current_workaround: str = "",
        wtp_score: float = 0.0,
        incumbent_failure: str = "",
        opportunity_type: str = "unknown",
        evidence_spans: list[str] | None = None,
        verified_evidence: list[Any] | None = None,
        evidence_quality: str = "no_quote",
        evidence_match_rate: float = 0.0,
        confidence: float = 0.0,
        uncertainty_reason: str = "",
        needs_human_review: bool = False,
        comment_sample: list[str] | None = None,
        buyer_authority_score: float = 0.55,
        workflow_frequency_score: float = 0.0,
        impact_score: float = 0.0,
        consensus_score: float = 0.0,
        incumbent_failure_score: float = 0.0,
        recency_score: float = 0.0,
        stale_penalty: float = 0.0,
        solved_penalty: float = 0.0,
        opportunity_score: float = 0.0,
        score_components: dict[str, Any] | None = None,
        comment_consensus_count: int = 0,
        comment_same_here_count: int = 0,
        comment_workaround_count: int = 0,
        comment_tool_mentions: list[str] | None = None,
        comment_shill_risk: float = 0.0,
        triage_status: str = "new",
        analysis_mode: str = "legacy",
        deep_dive_status: str = "not_requested",
        deep_dive_summary: str | None = None,
        analysis_payload: dict[str, Any] | None = None,
        pain_mentions_per_1000_posts: float = 0.0,
        pain_mentions_per_1000_comments: float = 0.0,
        unique_authors_count: int = 0,
        unique_threads_count: int = 0,
        weekly_delta: int = 0,
        source_activity_baseline: dict[str, Any] | None = None,
        emb_vector: list[float] | None = None,
    ) -> None:
        if triage_status not in PAIN_POINT_STATUSES:
            triage_status = "new"
        if deep_dive_status not in DEEP_DIVE_STATUSES:
            deep_dive_status = "not_requested"

        normalized_pain_type = str(pain_type or "unknown").strip()[:96] or "unknown"
        normalized_expression_type = str(expression_type or "unknown").strip()[:96] or "unknown"
        normalized_user_context = user_context_json if isinstance(user_context_json, dict) else {}
        user_context_json_text = json.dumps(normalized_user_context, ensure_ascii=False, default=str)
        normalized_intensity_score = self._coerce_unit_float(intensity_score)
        normalized_frequency_signal = str(frequency_signal or "single").strip()[:64] or "single"
        normalized_urgency = str(urgency if urgency is not None else "none").strip()[:96] or "none"
        normalized_current_workaround = str(current_workaround or "").strip()[:240]
        normalized_wtp_score = self._coerce_unit_float(wtp_score)
        normalized_incumbent_failure = str(incumbent_failure or "").strip()[:240]
        normalized_opportunity_type = str(opportunity_type or "unknown").strip()[:96] or "unknown"
        normalized_tags = self._normalize_competitor_tags(competitor_tags)
        if opportunity_bucket not in OPPORTUNITY_BUCKETS:
            opportunity_bucket = "unknown_age"
        normalized_evidence_spans = [
            str(item).strip()[:160]
            for item in (evidence_spans or [])
            if isinstance(item, str) and str(item).strip()
        ][:3]
        normalized_verified_evidence = self._normalize_verified_evidence(verified_evidence)
        normalized_evidence_quality = str(evidence_quality or "no_quote").strip()[:64] or "no_quote"
        if normalized_evidence_quality not in {"no_quote", "exact_quote", "weak_quote", "multi_quote", "linked_multi_source"}:
            normalized_evidence_quality = "no_quote"
        normalized_evidence_match_rate = self._coerce_unit_float(evidence_match_rate)
        normalized_confidence = self._coerce_unit_float(confidence)
        normalized_needs_human_review = self._coerce_bool_int(needs_human_review)
        normalized_uncertainty_reason = str(uncertainty_reason or "").strip()[:500]
        normalized_comment_sample = [
            str(item).strip()[:240]
            for item in (comment_sample or [])
            if isinstance(item, str) and str(item).strip()
        ][:5]
        normalized_comment_tool_mentions = self._normalize_competitor_tags(comment_tool_mentions)
        score_components_json = json.dumps(score_components or {}, ensure_ascii=False)
        normalized_is_deleted = self._coerce_bool_int(is_deleted)
        normalized_is_removed = self._coerce_bool_int(is_removed)
        normalized_body_available = self._coerce_bool_int(body_available)
        normalized_author_hash = str(author_hash or "").strip()
        source_activity_baseline_json = json.dumps(source_activity_baseline or {}, ensure_ascii=False)

        try:
            await self._conn.execute(
                """
                INSERT INTO pain_points (
                    subreddit, post_id, url, title, body, category, summary, severity,
                    is_monetizable, pain_level, willingness_to_pay, niche_category,
                    competitor_tags, source, source_created_at, source_created_ts, author_name,
                    is_deleted, is_removed, body_available, deleted_detected_at, author_hash,
                    opportunity_bucket, post_type, first_handness, buyer_authority,
                    pain_type, expression_type, user_context_json, intensity_score, frequency_signal,
                    urgency, current_workaround, wtp_score, incumbent_failure, opportunity_type,
                    evidence_spans_json, verified_evidence_json, evidence_quality, evidence_match_rate, confidence,
                    uncertainty_reason, needs_human_review,
                    comment_sample_json, buyer_authority_score, workflow_frequency_score, impact_score,
                    consensus_score, incumbent_failure_score, recency_score, stale_penalty, solved_penalty,
                    opportunity_score, score_components_json, comment_consensus_count, comment_same_here_count,
                    comment_workaround_count, comment_tool_mentions_json, comment_shill_risk,
                    triage_status, analysis_mode, deep_dive_status, deep_dive_summary, analysis_payload_json,
                    pain_mentions_per_1000_posts, pain_mentions_per_1000_comments, unique_authors_count,
                    unique_threads_count, weekly_delta, source_activity_baseline_json,
                    emb_vector
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                    subreddit = excluded.subreddit,
                    url = excluded.url,
                    title = excluded.title,
                    body = excluded.body,
                    category = excluded.category,
                    summary = excluded.summary,
                    severity = excluded.severity,
                    is_monetizable = excluded.is_monetizable,
                    pain_level = excluded.pain_level,
                    willingness_to_pay = excluded.willingness_to_pay,
                    niche_category = excluded.niche_category,
                    competitor_tags = excluded.competitor_tags,
                    source = excluded.source,
                    source_created_at = COALESCE(excluded.source_created_at, pain_points.source_created_at),
                    source_created_ts = COALESCE(excluded.source_created_ts, pain_points.source_created_ts),
                    author_name = COALESCE(excluded.author_name, pain_points.author_name),
                    is_deleted = excluded.is_deleted,
                    is_removed = excluded.is_removed,
                    body_available = excluded.body_available,
                    deleted_detected_at = COALESCE(excluded.deleted_detected_at, pain_points.deleted_detected_at),
                    author_hash = COALESCE(NULLIF(excluded.author_hash, ''), pain_points.author_hash),
                    opportunity_bucket = excluded.opportunity_bucket,
                    post_type = excluded.post_type,
                    first_handness = excluded.first_handness,
                    buyer_authority = excluded.buyer_authority,
                    pain_type = excluded.pain_type,
                    expression_type = excluded.expression_type,
                    user_context_json = excluded.user_context_json,
                    intensity_score = excluded.intensity_score,
                    frequency_signal = excluded.frequency_signal,
                    urgency = excluded.urgency,
                    current_workaround = excluded.current_workaround,
                    wtp_score = excluded.wtp_score,
                    incumbent_failure = excluded.incumbent_failure,
                    opportunity_type = excluded.opportunity_type,
                    evidence_spans_json = excluded.evidence_spans_json,
                    verified_evidence_json = excluded.verified_evidence_json,
                    evidence_quality = excluded.evidence_quality,
                    evidence_match_rate = excluded.evidence_match_rate,
                    confidence = excluded.confidence,
                    uncertainty_reason = excluded.uncertainty_reason,
                    needs_human_review = excluded.needs_human_review,
                    comment_sample_json = excluded.comment_sample_json,
                    buyer_authority_score = excluded.buyer_authority_score,
                    workflow_frequency_score = excluded.workflow_frequency_score,
                    impact_score = excluded.impact_score,
                    consensus_score = excluded.consensus_score,
                    incumbent_failure_score = excluded.incumbent_failure_score,
                    recency_score = excluded.recency_score,
                    stale_penalty = excluded.stale_penalty,
                    solved_penalty = excluded.solved_penalty,
                    opportunity_score = excluded.opportunity_score,
                    score_components_json = excluded.score_components_json,
                    comment_consensus_count = excluded.comment_consensus_count,
                    comment_same_here_count = excluded.comment_same_here_count,
                    comment_workaround_count = excluded.comment_workaround_count,
                    comment_tool_mentions_json = excluded.comment_tool_mentions_json,
                    comment_shill_risk = excluded.comment_shill_risk,
                    analysis_mode = excluded.analysis_mode,
                    analysis_payload_json = excluded.analysis_payload_json,
                    pain_mentions_per_1000_posts = excluded.pain_mentions_per_1000_posts,
                    pain_mentions_per_1000_comments = excluded.pain_mentions_per_1000_comments,
                    unique_authors_count = excluded.unique_authors_count,
                    unique_threads_count = excluded.unique_threads_count,
                    weekly_delta = excluded.weekly_delta,
                    source_activity_baseline_json = excluded.source_activity_baseline_json,
                    deep_dive_summary = COALESCE(excluded.deep_dive_summary, pain_points.deep_dive_summary),
                    deep_dive_status = CASE
                        WHEN pain_points.deep_dive_status = 'completed' THEN pain_points.deep_dive_status
                        ELSE excluded.deep_dive_status
                    END
                """,
                (
                    subreddit,
                    post_id,
                    url,
                    title,
                    body,
                    category,
                    summary,
                    severity,
                    int(is_monetizable),
                    pain_level,
                    willingness_to_pay,
                    niche_category,
                    json.dumps(normalized_tags, ensure_ascii=False),
                    source,
                    source_created_at,
                    source_created_ts,
                    author_name,
                    normalized_is_deleted,
                    normalized_is_removed,
                    normalized_body_available,
                    deleted_detected_at,
                    normalized_author_hash,
                    opportunity_bucket,
                    post_type,
                    first_handness,
                    buyer_authority,
                    normalized_pain_type,
                    normalized_expression_type,
                    user_context_json_text,
                    normalized_intensity_score,
                    normalized_frequency_signal,
                    normalized_urgency,
                    normalized_current_workaround,
                    normalized_wtp_score,
                    normalized_incumbent_failure,
                    normalized_opportunity_type,
                    json.dumps(normalized_evidence_spans, ensure_ascii=False),
                    json.dumps(normalized_verified_evidence, ensure_ascii=False),
                    normalized_evidence_quality,
                    normalized_evidence_match_rate,
                    normalized_confidence,
                    normalized_uncertainty_reason,
                    normalized_needs_human_review,
                    json.dumps(normalized_comment_sample, ensure_ascii=False),
                    float(buyer_authority_score),
                    float(workflow_frequency_score),
                    float(impact_score),
                    float(consensus_score),
                    float(incumbent_failure_score),
                    float(recency_score),
                    float(stale_penalty),
                    float(solved_penalty),
                    float(opportunity_score),
                    score_components_json,
                    int(comment_consensus_count),
                    int(comment_same_here_count),
                    int(comment_workaround_count),
                    json.dumps(normalized_comment_tool_mentions, ensure_ascii=False),
                    float(comment_shill_risk),
                    triage_status,
                    analysis_mode,
                    deep_dive_status,
                    deep_dive_summary,
                    json.dumps(analysis_payload, ensure_ascii=False) if analysis_payload else None,
                    float(pain_mentions_per_1000_posts),
                    float(pain_mentions_per_1000_comments),
                    int(unique_authors_count),
                    int(unique_threads_count),
                    int(weekly_delta),
                    source_activity_baseline_json,
                    json.dumps(emb_vector) if emb_vector is not None else None,
                ),
            )
            await self._replace_competitor_tags(post_id, normalized_tags)
            await self._conn.commit()
        except Exception as e:
            logger.error("Failed to insert pain point %s: %s", post_id, e)
            raise

    async def get_pain_points(self, subreddit: str) -> list[dict[str, Any]]:
        async with self._conn.execute(
            "SELECT * FROM pain_points WHERE subreddit = ? ORDER BY created_at DESC",
            (subreddit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_pain_point(self, post_id: str) -> dict[str, Any] | None:
        async with self._conn.execute("SELECT * FROM pain_points WHERE post_id = ? LIMIT 1", (post_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def _comment_row(comment: Any) -> dict[str, Any]:
        if is_dataclass(comment):
            return asdict(comment)
        if isinstance(comment, dict):
            return dict(comment)
        return {
            "comment_id": getattr(comment, "comment_id", ""),
            "post_id": getattr(comment, "post_id", ""),
            "parent_id": getattr(comment, "parent_id", ""),
            "body": getattr(comment, "body", ""),
            "body_hash": getattr(comment, "body_hash", ""),
            "author_hash": getattr(comment, "author_hash", ""),
            "score": getattr(comment, "score", 0),
            "created_utc": getattr(comment, "created_utc", None),
            "depth": getattr(comment, "depth", 0),
            "is_op": getattr(comment, "is_op", False),
            "is_deleted": getattr(comment, "is_deleted", False),
            "is_removed": getattr(comment, "is_removed", False),
            "body_available": getattr(comment, "body_available", True),
            "deleted_detected_at": getattr(comment, "deleted_detected_at", None),
            "permalink": getattr(comment, "permalink", ""),
            "fetched_at": getattr(comment, "fetched_at", None),
        }

    async def upsert_comments(self, comments: list[Any]) -> None:
        if not comments:
            return
        rows: list[tuple[Any, ...]] = []
        for comment in comments:
            row = self._comment_row(comment)
            comment_id = str(row.get("comment_id") or "").strip()
            post_id = str(row.get("post_id") or "").strip()
            if not comment_id or not post_id:
                continue
            rows.append(
                (
                    comment_id,
                    post_id,
                    str(row.get("parent_id") or "").strip() or None,
                    str(row.get("body") or ""),
                    str(row.get("body_hash") or "").strip() or None,
                    str(row.get("author_hash") or "").strip() or None,
                    int(row.get("score") or 0),
                    int(row["created_utc"]) if row.get("created_utc") not in {None, ""} else None,
                    int(row.get("depth") or 0),
                    self._coerce_bool_int(row.get("is_op")),
                    self._coerce_bool_int(row.get("is_deleted")),
                    self._coerce_bool_int(row.get("is_removed")),
                    self._coerce_bool_int(row.get("body_available", True)),
                    str(row.get("deleted_detected_at") or "").strip() or None,
                    str(row.get("permalink") or "").strip() or None,
                    str(row.get("fetched_at") or "").strip() or None,
                )
            )
        if not rows:
            return
        await self._conn.executemany(
            """
            INSERT INTO comments (
                comment_id, post_id, parent_id, body, body_hash, author_hash, score,
                created_utc, depth, is_op, is_deleted, is_removed, body_available,
                deleted_detected_at, permalink, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(comment_id) DO UPDATE SET
                post_id = excluded.post_id,
                parent_id = excluded.parent_id,
                body = excluded.body,
                body_hash = excluded.body_hash,
                author_hash = COALESCE(excluded.author_hash, comments.author_hash),
                score = excluded.score,
                created_utc = COALESCE(excluded.created_utc, comments.created_utc),
                depth = excluded.depth,
                is_op = excluded.is_op,
                is_deleted = excluded.is_deleted,
                is_removed = excluded.is_removed,
                body_available = excluded.body_available,
                deleted_detected_at = COALESCE(excluded.deleted_detected_at, comments.deleted_detected_at),
                permalink = COALESCE(excluded.permalink, comments.permalink),
                fetched_at = COALESCE(excluded.fetched_at, comments.fetched_at),
                updated_at = datetime('now')
            """,
            rows,
        )
        await self._conn.commit()

    async def get_comments_for_post(self, post_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        async with self._conn.execute(
            """
            SELECT * FROM comments
            WHERE post_id = ?
            ORDER BY COALESCE(created_utc, 0), depth, comment_id
            LIMIT ?
            """,
            (post_id, max(1, int(limit))),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def upsert_source_ingestion_cursor(
        self,
        *,
        source: str,
        subreddit: str | None = None,
        feed: str | None = None,
        query: str | None = None,
        timeframe: str | None = None,
        after: str | None = None,
        before: str | None = None,
        time_window: str | None = None,
        last_seen_created_utc: int | None = None,
        last_success_at: str | None = None,
        fetch_errors: list[str] | None = None,
    ) -> int:
        key = (source, subreddit, feed, query, timeframe)
        async with self._conn.execute(
            """
            SELECT id FROM source_ingestion_cursors
            WHERE source = ?
              AND COALESCE(subreddit, '') = COALESCE(?, '')
              AND COALESCE(feed, '') = COALESCE(?, '')
              AND COALESCE(query, '') = COALESCE(?, '')
              AND COALESCE(timeframe, '') = COALESCE(?, '')
            LIMIT 1
            """,
            key,
        ) as cursor:
            existing = await cursor.fetchone()
        fetch_errors_json = json.dumps(fetch_errors or [], ensure_ascii=False)
        if existing:
            await self._conn.execute(
                """
                UPDATE source_ingestion_cursors
                SET after = ?, before = ?, time_window = ?, last_seen_created_utc = ?,
                    last_success_at = ?, fetch_errors_json = ?
                WHERE source = ?
                  AND COALESCE(subreddit, '') = COALESCE(?, '')
                  AND COALESCE(feed, '') = COALESCE(?, '')
                  AND COALESCE(query, '') = COALESCE(?, '')
                  AND COALESCE(timeframe, '') = COALESCE(?, '')
                """,
                (
                    after,
                    before,
                    time_window,
                    last_seen_created_utc,
                    last_success_at,
                    fetch_errors_json,
                    *key,
                ),
            )
            await self._conn.commit()
            return int(existing["id"])
        async with self._conn.execute(
            """
            INSERT INTO source_ingestion_cursors (
                source, subreddit, feed, query, timeframe, after, before, time_window,
                last_seen_created_utc, last_success_at, fetch_errors_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                subreddit,
                feed,
                query,
                timeframe,
                after,
                before,
                time_window,
                last_seen_created_utc,
                last_success_at,
                fetch_errors_json,
            ),
        ) as cursor:
            await self._conn.commit()
            return int(cursor.lastrowid)

    async def get_source_ingestion_cursor(
        self,
        *,
        source: str,
        subreddit: str | None = None,
        feed: str | None = None,
        query: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any] | None:
        async with self._conn.execute(
            """
            SELECT * FROM source_ingestion_cursors
            WHERE source = ?
              AND COALESCE(subreddit, '') = COALESCE(?, '')
              AND COALESCE(feed, '') = COALESCE(?, '')
              AND COALESCE(query, '') = COALESCE(?, '')
              AND COALESCE(timeframe, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (source, subreddit, feed, query, timeframe),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def record_source_coverage_run(
        self,
        *,
        source: str,
        scope: str,
        fetched_posts: int = 0,
        fetched_comments: int = 0,
        skipped_deleted: int = 0,
        skipped_duplicates: int = 0,
        failed_requests: int = 0,
        source_method_used: str | None = None,
        duration_ms: int | None = None,
    ) -> int:
        async with self._conn.execute(
            """
            INSERT INTO source_coverage_runs (
                source, scope, fetched_posts, fetched_comments, skipped_deleted,
                skipped_duplicates, failed_requests, source_method_used, duration_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                scope,
                int(fetched_posts or 0),
                int(fetched_comments or 0),
                int(skipped_deleted or 0),
                int(skipped_duplicates or 0),
                int(failed_requests or 0),
                source_method_used,
                duration_ms,
            ),
        ) as cursor:
            await self._conn.commit()
            return int(cursor.lastrowid)

    async def list_source_coverage_runs(
        self,
        *,
        source: str | None = None,
        scope: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if source is not None:
            conditions.append("source = ?")
            params.append(source)
        if scope is not None:
            conditions.append("scope = ?")
            params.append(scope)
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        async with self._conn.execute(
            f"""
            SELECT * FROM source_coverage_runs
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,  # nosec B608
            (*params, max(1, int(limit))),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def calculate_normalized_frequency(
        self,
        *,
        source: str,
        scope: str,
        post_ids: list[str],
    ) -> dict[str, Any]:
        unique_post_ids = [post_id for post_id in dict.fromkeys(str(item) for item in post_ids if str(item or "").strip())]
        coverage_runs = await self.list_source_coverage_runs(source=source, scope=scope, limit=1)
        baseline = coverage_runs[0] if coverage_runs else {}
        fetched_posts = int(baseline.get("fetched_posts") or 0)
        fetched_comments = int(baseline.get("fetched_comments") or 0)
        unique_authors_count = 0
        unique_threads_count = len(unique_post_ids)
        if unique_post_ids:
            placeholders = ",".join("?" * len(unique_post_ids))
            async with self._conn.execute(
                f"""
                SELECT COUNT(DISTINCT NULLIF(author_hash, '')) AS unique_authors,
                       COUNT(DISTINCT post_id) AS unique_threads
                FROM pain_points
                WHERE post_id IN ({placeholders})
                """,  # nosec B608
                tuple(unique_post_ids),
            ) as cursor:
                row = await cursor.fetchone()
            if row:
                unique_authors_count = int(row["unique_authors"] or 0)
                unique_threads_count = int(row["unique_threads"] or unique_threads_count)
        pain_mentions = len(unique_post_ids)
        return {
            "pain_mentions_per_1000_posts": round(pain_mentions / fetched_posts * 1000, 3) if fetched_posts > 0 else 0.0,
            "pain_mentions_per_1000_comments": round(pain_mentions / fetched_comments * 1000, 3) if fetched_comments > 0 else 0.0,
            "unique_authors_count": unique_authors_count,
            "unique_threads_count": unique_threads_count,
            "weekly_delta": 0,
            "source_activity_baseline": {
                "source": baseline.get("source", source),
                "scope": baseline.get("scope", scope),
                "fetched_posts": fetched_posts,
                "fetched_comments": fetched_comments,
                "skipped_deleted": int(baseline.get("skipped_deleted") or 0),
                "skipped_duplicates": int(baseline.get("skipped_duplicates") or 0),
                "failed_requests": int(baseline.get("failed_requests") or 0),
                "source_method_used": baseline.get("source_method_used"),
                "duration_ms": baseline.get("duration_ms"),
                "created_at": baseline.get("created_at"),
            },
        }

    async def update_pain_points_frequency_metrics(
        self,
        *,
        post_ids: list[str],
        metrics: dict[str, Any],
    ) -> None:
        unique_post_ids = [post_id for post_id in dict.fromkeys(str(item) for item in post_ids if str(item or "").strip())]
        if not unique_post_ids:
            return
        source_activity_baseline_json = json.dumps(metrics.get("source_activity_baseline") or {}, ensure_ascii=False)
        rows = [
            (
                float(metrics.get("pain_mentions_per_1000_posts") or 0.0),
                float(metrics.get("pain_mentions_per_1000_comments") or 0.0),
                int(metrics.get("unique_authors_count") or 0),
                int(metrics.get("unique_threads_count") or 0),
                int(metrics.get("weekly_delta") or 0),
                source_activity_baseline_json,
                post_id,
            )
            for post_id in unique_post_ids
        ]
        await self._conn.executemany(
            """
            UPDATE pain_points
            SET pain_mentions_per_1000_posts = ?,
                pain_mentions_per_1000_comments = ?,
                unique_authors_count = ?,
                unique_threads_count = ?,
                weekly_delta = ?,
                source_activity_baseline_json = ?
            WHERE post_id = ?
            """,
            rows,
        )
        await self._conn.commit()

    async def store_embedding(self, post_id: str, emb_vector: list[float]) -> None:
        await self._conn.execute(
            "UPDATE pain_points SET emb_vector = ? WHERE post_id = ?",
            (json.dumps(emb_vector), post_id),
        )
        await self._conn.commit()

    async def get_pain_points_with_embeddings(self) -> list[dict[str, Any]]:
        """Returns all rows that have a stored embedding (not merged duplicates)."""
        async with self._conn.execute(
            "SELECT post_id, source, emb_vector FROM pain_points "
            "WHERE emb_vector IS NOT NULL AND triage_status != 'merged'"
        ) as cursor:
            rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["emb_vector"] = json.loads(d["emb_vector"])
            result.append(d)
        return result

    async def get_pain_points_without_embeddings(self) -> list[dict[str, Any]]:
        """Returns all rows missing an embedding (used for backfill)."""
        async with self._conn.execute(
            "SELECT post_id, source, title, body FROM pain_points "
            "WHERE emb_vector IS NULL AND triage_status != 'merged'"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def merge_duplicate(
        self,
        *,
        canonical_post_id: str,
        dup_post_id: str,
        dup_emb_vector: list[float],
    ) -> None:
        """Merge a duplicate into the canonical record.

        Increments cross_source_count and appends dup_post_id to cross_source_ids
        on the canonical.  Marks the duplicate row as merged and stores its embedding.
        """
        async with self._conn.execute(
            "SELECT cross_source_ids FROM pain_points WHERE post_id = ?",
            (canonical_post_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            logger.warning("merge_duplicate: canonical %s not found", canonical_post_id)
            return

        current_ids: list[str] = json.loads(row["cross_source_ids"] or "[]")
        should_increment_count = dup_post_id not in current_ids
        if should_increment_count:
            current_ids.append(dup_post_id)

        try:
            if should_increment_count:
                await self._conn.execute(
                    "UPDATE pain_points SET cross_source_count = cross_source_count + 1, "
                    "cross_source_ids = ? WHERE post_id = ?",
                    (json.dumps(current_ids), canonical_post_id),
                )
            else:
                await self._conn.execute(
                    "UPDATE pain_points SET cross_source_ids = ? WHERE post_id = ?",
                    (json.dumps(current_ids), canonical_post_id),
                )
            await self._conn.execute(
                "UPDATE pain_points SET emb_vector = ?, triage_status = 'merged' WHERE post_id = ?",
                (json.dumps(dup_emb_vector), dup_post_id),
            )
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            raise
        logger.info("merge_duplicate: merged %s -> canonical %s", dup_post_id, canonical_post_id)

    async def get_pain_points_by_ids(self, post_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not post_ids:
            return {}
        placeholders = ",".join("?" * len(post_ids))
        async with self._conn.execute(
            f"SELECT * FROM pain_points WHERE post_id IN ({placeholders})",  # nosec B608
            tuple(post_ids),
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["post_id"]: dict(row) for row in rows}

    async def get_competitor_pain(self, competitor_tag: str, days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
        tag = competitor_tag.strip().lower()
        async with self._conn.execute(
            """
            SELECT p.*
            FROM pain_points p
            JOIN pain_point_competitors c ON c.post_id = p.post_id
            WHERE c.competitor_tag = ?
              AND datetime(p.created_at) >= datetime('now', ?)
            ORDER BY p.willingness_to_pay DESC, p.pain_level DESC
            LIMIT ?
            """,
            (tag, f"-{days} days", limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_top_competitor_tags(self, days: int = 30, limit: int = 20) -> list[dict[str, Any]]:
        async with self._conn.execute(
            """
            SELECT c.competitor_tag AS tag, COUNT(*) AS mention_count
            FROM pain_point_competitors c
            JOIN pain_points p ON p.post_id = c.post_id
            WHERE datetime(p.created_at) >= datetime('now', ?)
            GROUP BY c.competitor_tag
            ORDER BY mention_count DESC
            LIMIT ?
            """,
            (f"-{days} days", limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_triage_status(self, post_id: str, status: str) -> bool:
        if status not in PAIN_POINT_STATUSES:
            raise ValueError(f"Unsupported triage status: {status}")
        cursor = await self._conn.execute("UPDATE pain_points SET triage_status = ? WHERE post_id = ?", (status, post_id))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def mark_deep_dive_status(
        self,
        post_id: str,
        status: str,
        summary: str | None = None,
        error: str | None = None,
    ) -> bool:
        if status not in DEEP_DIVE_STATUSES:
            raise ValueError(f"Unsupported deep dive status: {status}")
        merged_summary = summary or (f"Deep dive error: {error}" if error else None)
        cursor = await self._conn.execute(
            "UPDATE pain_points SET deep_dive_status = ?, deep_dive_summary = COALESCE(?, deep_dive_summary) WHERE post_id = ?",
            (status, merged_summary, post_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def save_deep_dive(
        self,
        *,
        post_id: str,
        subreddit: str,
        source: str,
        status: str,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in DEEP_DIVE_STATUSES:
            raise ValueError(f"Unsupported deep dive status: {status}")
        payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        await self._conn.execute(
            """
            INSERT INTO deep_dives (post_id, subreddit, source, status, payload_json, error)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                source = excluded.source,
                status = excluded.status,
                payload_json = excluded.payload_json,
                error = excluded.error,
                updated_at = datetime('now')
            """,
            (post_id, subreddit, source, status, payload_json, error),
        )
        await self._conn.commit()

    async def get_deep_dive(self, post_id: str) -> dict[str, Any] | None:
        async with self._conn.execute(
            "SELECT * FROM deep_dives WHERE post_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (post_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_export_rows(
        self,
        *,
        subreddit: str | None = None,
        min_wtp: int = 8,
        include_favorites: bool = True,
        opportunity_bucket: str | None = None,
        max_source_age_days: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions = ["triage_status NOT IN ('discarded', 'merged')"]
        params: list[Any] = []
        if subreddit:
            conditions.append("subreddit = ?")
            params.append(subreddit)
        if opportunity_bucket:
            conditions.append("opportunity_bucket = ?")
            params.append(opportunity_bucket)
        if max_source_age_days is not None:
            cutoff_ts = int((datetime.now(timezone.utc).timestamp()) - max(0, max_source_age_days) * 86400)
            conditions.append("source_created_ts IS NOT NULL AND source_created_ts >= ?")
            params.append(cutoff_ts)
        if include_favorites:
            conditions.append("(willingness_to_pay >= ? OR triage_status = 'favorite')")
            params.append(min_wtp)
        else:
            conditions.append("willingness_to_pay >= ?")
            params.append(min_wtp)

        query = "SELECT * FROM pain_points WHERE " + " AND ".join(conditions)  # nosec B608
        query += " ORDER BY CASE WHEN triage_status = 'favorite' THEN 0 ELSE 1 END, willingness_to_pay DESC, pain_level DESC, created_at DESC"  # nosec B608
        async with self._conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def record_analysis_run(
        self,
        *,
        subreddit: str,
        post_count: int,
        pain_count: int,
        monetizable_count: int,
        deep_dive_count: int,
        skipped_existing_count: int = 0,
        dedup_merged_count: int = 0,
        screen_rule_dropped_count: int = 0,
        screen_kept_count: int = 0,
        screen_capped_count: int = 0,
        duration_ms: int | None,
        report_id: int | None,
    ) -> int:
        async with self._conn.execute(
            (
                "INSERT INTO analysis_runs ("
                "subreddit, post_count, pain_count, monetizable_count, deep_dive_count, "
                "skipped_existing_count, dedup_merged_count, screen_rule_dropped_count, "
                "screen_kept_count, screen_capped_count, duration_ms, report_id"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                subreddit,
                post_count,
                pain_count,
                monetizable_count,
                deep_dive_count,
                skipped_existing_count,
                dedup_merged_count,
                screen_rule_dropped_count,
                screen_kept_count,
                screen_capped_count,
                duration_ms,
                report_id,
            ),
        ) as cursor:
            await self._conn.commit()
            return int(cursor.lastrowid)

    async def create_macro_trend_run(self, *, window_days: int, candidate_count: int, cluster_count: int) -> int:
        async with self._conn.execute(
            "INSERT INTO macro_trend_runs (window_days, candidate_count, cluster_count) VALUES (?, ?, ?)",
            (window_days, candidate_count, cluster_count),
        ) as cursor:
            await self._conn.commit()
            return int(cursor.lastrowid)

    async def save_macro_cluster(
        self,
        *,
        run_id: int,
        canonical_key: str | None = None,
        cluster_key: str,
        label: str,
        summary: str,
        estimated_monetization_signal: str,
        item_count: int,
        aggregate_wtp: float,
        fresh_post_count: int = 0,
        evergreen_post_count: int = 0,
        median_buyer_authority: float = 0.0,
        incumbents: list[str] | None = None,
        avg_opportunity_score: float = 0.0,
        cluster_stability_score: float = 0.0,
        representative_examples: list[dict[str, Any]] | None = None,
        verified_quote_count: int = 0,
        independent_source_count: int = 0,
        unique_author_count: int = 0,
        normalized_frequency: dict[str, Any] | None = None,
        pain_mentions_per_1000_posts: float = 0.0,
        pain_mentions_per_1000_comments: float = 0.0,
        unique_authors_count: int = 0,
        unique_threads_count: int = 0,
        weekly_delta: int = 0,
        source_activity_baseline: dict[str, Any] | None = None,
        latest_source_created_ts: int | None = None,
        members: list[tuple[str, float]],
    ) -> int:
        normalized_frequency_payload = normalized_frequency or {
            "pain_mentions_per_1000_posts": float(pain_mentions_per_1000_posts),
            "pain_mentions_per_1000_comments": float(pain_mentions_per_1000_comments),
            "unique_authors_count": int(unique_authors_count),
            "unique_threads_count": int(unique_threads_count),
            "weekly_delta": int(weekly_delta),
            "source_activity_baseline": source_activity_baseline or {},
        }
        if unique_author_count <= 0:
            unique_author_count = int(normalized_frequency_payload.get("unique_authors_count") or unique_authors_count or 0)
        if unique_authors_count <= 0:
            unique_authors_count = int(unique_author_count or normalized_frequency_payload.get("unique_authors_count") or 0)
        async with self._conn.execute(
            """
            INSERT INTO macro_trend_clusters (
                run_id, canonical_key, cluster_key, label, summary, estimated_monetization_signal,
                item_count, aggregate_wtp, fresh_post_count, evergreen_post_count,
                median_buyer_authority, incumbents_json, avg_opportunity_score,
                pain_mentions_per_1000_posts, pain_mentions_per_1000_comments,
                unique_authors_count, unique_threads_count, weekly_delta,
                source_activity_baseline_json, latest_source_created_ts, cluster_stability_score,
                representative_examples_json, verified_quote_count, independent_source_count,
                unique_author_count, normalized_frequency_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                canonical_key,
                cluster_key,
                label,
                summary,
                estimated_monetization_signal,
                item_count,
                aggregate_wtp,
                fresh_post_count,
                evergreen_post_count,
                median_buyer_authority,
                json.dumps(incumbents or [], ensure_ascii=False),
                avg_opportunity_score,
                float(pain_mentions_per_1000_posts),
                float(pain_mentions_per_1000_comments),
                int(unique_authors_count),
                int(unique_threads_count),
                int(weekly_delta),
                json.dumps(source_activity_baseline or {}, ensure_ascii=False),
                latest_source_created_ts,
                self._coerce_unit_float(cluster_stability_score),
                json.dumps(representative_examples or [], ensure_ascii=False, default=str),
                int(verified_quote_count),
                int(independent_source_count),
                int(unique_author_count),
                json.dumps(normalized_frequency_payload, ensure_ascii=False, default=str),
            ),
        ) as cursor:
            cluster_id = int(cursor.lastrowid)
        for post_id, similarity in members:
            await self._conn.execute(
                "INSERT INTO macro_trend_members (run_id, cluster_id, post_id, similarity) VALUES (?, ?, ?, ?)",
                (run_id, cluster_id, post_id, similarity),
            )
        await self._conn.commit()
        return cluster_id

    async def get_latest_macro_trend_run(self) -> dict[str, Any] | None:
        async with self._conn.execute("SELECT * FROM macro_trend_runs ORDER BY created_at DESC, id DESC LIMIT 1") as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def _decode_json_field(raw: Any, default: Any) -> Any:
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return default
        return default

    @classmethod
    def _decode_macro_cluster_row(cls, row_dict: dict[str, Any]) -> dict[str, Any]:
        incumbents = cls._decode_json_field(row_dict.get("incumbents_json"), [])
        row_dict["incumbents"] = incumbents if isinstance(incumbents, list) else []
        baseline = cls._decode_json_field(row_dict.get("source_activity_baseline_json"), {})
        row_dict["source_activity_baseline"] = baseline if isinstance(baseline, dict) else {}
        examples = cls._decode_json_field(row_dict.get("representative_examples_json"), [])
        row_dict["representative_examples"] = examples if isinstance(examples, list) else []
        normalized_frequency = cls._decode_json_field(row_dict.get("normalized_frequency_json"), {})
        if not isinstance(normalized_frequency, dict) or not normalized_frequency:
            normalized_frequency = {
                "pain_mentions_per_1000_posts": float(row_dict.get("pain_mentions_per_1000_posts") or 0.0),
                "pain_mentions_per_1000_comments": float(row_dict.get("pain_mentions_per_1000_comments") or 0.0),
                "unique_authors_count": int(row_dict.get("unique_authors_count") or row_dict.get("unique_author_count") or 0),
                "unique_threads_count": int(row_dict.get("unique_threads_count") or 0),
                "weekly_delta": int(row_dict.get("weekly_delta") or 0),
                "source_activity_baseline": row_dict["source_activity_baseline"],
            }
        row_dict["normalized_frequency"] = normalized_frequency
        row_dict["unique_author_count"] = int(row_dict.get("unique_author_count") or row_dict.get("unique_authors_count") or normalized_frequency.get("unique_authors_count") or 0)
        row_dict["cluster_stability_score"] = float(row_dict.get("cluster_stability_score") or 0.0)
        row_dict["verified_quote_count"] = int(row_dict.get("verified_quote_count") or 0)
        row_dict["independent_source_count"] = int(row_dict.get("independent_source_count") or 0)
        return row_dict

    async def get_macro_clusters(self, run_id: int) -> list[dict[str, Any]]:
        async with self._conn.execute(
            """
            SELECT c.*, GROUP_CONCAT(m.post_id) AS post_ids
            FROM macro_trend_clusters c
            LEFT JOIN macro_trend_members m ON m.cluster_id = c.id
            WHERE c.run_id = ?
            GROUP BY c.id
            ORDER BY c.avg_opportunity_score DESC, c.latest_source_created_ts DESC, c.item_count DESC, c.aggregate_wtp DESC
            """,
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        out = []
        for row in rows:
            row_dict = dict(row)
            post_ids = row_dict.get("post_ids")
            row_dict["post_ids"] = post_ids.split(",") if isinstance(post_ids, str) and post_ids else []
            out.append(self._decode_macro_cluster_row(row_dict))
        return out

    async def get_latest_macro_cluster_for_post(self, post_id: str) -> dict[str, Any] | None:
        async with self._conn.execute(
            """
            SELECT c.*
            FROM macro_trend_members m
            JOIN macro_trend_clusters c ON c.id = m.cluster_id
            JOIN macro_trend_runs r ON r.id = c.run_id
            WHERE m.post_id = ?
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT 1
            """,
            (post_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            row_dict = dict(row)
            return self._decode_macro_cluster_row(row_dict)

    async def get_latest_canonical_clusters(
        self,
        *,
        limit: int = 10,
        post_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        post_filter_sql = ""
        if post_ids:
            placeholders = ",".join("?" * len(post_ids))
            post_filter_sql = f"WHERE EXISTS (SELECT 1 FROM macro_trend_members mf WHERE mf.cluster_id = c.id AND mf.post_id IN ({placeholders}))"  # nosec B608
            params.extend(post_ids)
        async with self._conn.execute(
            f"""
            SELECT c.*, r.created_at AS run_created_at, GROUP_CONCAT(m.post_id) AS post_ids
            FROM macro_trend_clusters c
            JOIN macro_trend_runs r ON r.id = c.run_id
            LEFT JOIN macro_trend_members m ON m.cluster_id = c.id
            {post_filter_sql}
            GROUP BY c.id
            ORDER BY r.created_at DESC, r.id DESC, c.avg_opportunity_score DESC, c.latest_source_created_ts DESC, c.item_count DESC, c.aggregate_wtp DESC
            """,
            tuple(params),
        ) as cursor:
            rows = await cursor.fetchall()
        out = []
        seen_keys: set[str] = set()
        for row in rows:
            row_dict = dict(row)
            canonical_key = str(row_dict.get("canonical_key") or "").strip()
            if not canonical_key or canonical_key in seen_keys:
                continue
            seen_keys.add(canonical_key)
            post_ids = row_dict.get("post_ids")
            row_dict["post_ids"] = post_ids.split(",") if isinstance(post_ids, str) and post_ids else []
            out.append(self._decode_macro_cluster_row(row_dict))
            if len(out) >= limit:
                break
        return out

    async def get_macro_candidates(self, *, window_days: int, min_wtp: int) -> list[dict[str, Any]]:
        async with self._conn.execute(
            """
            SELECT * FROM pain_points
            WHERE datetime(created_at) >= datetime('now', ?)
              AND triage_status NOT IN ('discarded', 'merged')
              AND (triage_status = 'favorite' OR willingness_to_pay >= ?)
            ORDER BY willingness_to_pay DESC, pain_level DESC, created_at DESC
            """,
            (f"-{window_days} days", min_wtp),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_recent_pain_points(
        self,
        *,
        hours: int = 24,
        subreddit: str | None = None,
        limit: int = 200,
        opportunity_bucket: str | None = None,
        max_source_age_days: int | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [f"-{hours} hours"]
        query = "SELECT * FROM pain_points WHERE datetime(created_at) >= datetime('now', ?) AND triage_status NOT IN ('discarded', 'merged')"
        if subreddit:
            query += " AND subreddit = ?"
            params.append(subreddit)
        if opportunity_bucket:
            query += " AND opportunity_bucket = ?"
            params.append(opportunity_bucket)
        if max_source_age_days is not None:
            cutoff_ts = int((datetime.now(timezone.utc).timestamp()) - max(0, max_source_age_days) * 86400)
            query += " AND source_created_ts IS NOT NULL AND source_created_ts >= ?"
            params.append(cutoff_ts)
        query += (
            " ORDER BY opportunity_score DESC, willingness_to_pay DESC, pain_level DESC, "
            "source_created_ts DESC, created_at DESC LIMIT ?"
        )
        params.append(limit)
        async with self._conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_recent_rejected_noise_candidates(
        self,
        *,
        hours: int = 24,
        subreddit: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [f"-{hours} hours"]
        query = "SELECT * FROM pain_points WHERE datetime(created_at) >= datetime('now', ?)"
        if subreddit:
            query += " AND subreddit = ?"
            params.append(subreddit)
        scan_limit = max(int(limit), int(limit) * 5, 50)
        query += (
            " ORDER BY opportunity_score DESC, willingness_to_pay DESC, pain_level DESC, "
            "source_created_ts DESC, created_at DESC LIMIT ?"
        )
        params.append(scan_limit)
        async with self._conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        annotated = annotate_rejected_noise_rows([dict(row) for row in rows])
        return sort_rejected_noise_rows(annotated)[: max(0, int(limit))]

    async def get_latest_analysis_run(self, subreddit: str | None = None) -> dict[str, Any] | None:
        if subreddit:
            query = "SELECT * FROM analysis_runs WHERE subreddit = ? ORDER BY created_at DESC, id DESC LIMIT 1"
            params: tuple[Any, ...] = (subreddit,)
        else:
            query = "SELECT * FROM analysis_runs ORDER BY created_at DESC, id DESC LIMIT 1"
            params = ()
        async with self._conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def record_llm_usage(
        self,
        *,
        model: str,
        operation: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        post_id: str | None = None,
        prompt_hash: str | None = None,
        fallback_reason: str | None = None,
        schema_version: str | None = None,
        provider: str | None = None,
        request_path: str | None = None,
        candidate_stage: str | None = None,
    ) -> int:
        async with self._conn.execute(
            """
            INSERT INTO llm_usage_events (
                model, operation, prompt_tokens, completion_tokens, cost_usd, post_id,
                prompt_hash, fallback_reason, schema_version, provider, request_path, candidate_stage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model,
                operation,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                post_id,
                prompt_hash,
                fallback_reason,
                schema_version,
                provider,
                request_path,
                candidate_stage,
            ),
        ) as cursor:
            await self._conn.commit()
            return int(cursor.lastrowid)

    async def get_cached_llm_payload(self, cache_key: str) -> dict[str, Any] | None:
        async with self._conn.execute(
            "SELECT payload_json FROM llm_response_cache WHERE cache_key = ? LIMIT 1",
            (cache_key,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        try:
            return json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            logger.warning("Invalid cached payload for key=%s, dropping cache row", cache_key)
            await self._conn.execute("DELETE FROM llm_response_cache WHERE cache_key = ?", (cache_key,))
            await self._conn.commit()
            return None

    async def set_cached_llm_payload(
        self,
        *,
        cache_key: str,
        model: str,
        operation: str,
        payload: dict[str, Any],
    ) -> None:
        payload_json = json.dumps(payload, ensure_ascii=False)
        await self._conn.execute(
            """
            INSERT INTO llm_response_cache (cache_key, model, operation, payload_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                model = excluded.model,
                operation = excluded.operation,
                payload_json = excluded.payload_json,
                updated_at = datetime('now')
            """,
            (cache_key, model, operation, payload_json),
        )
        await self._conn.commit()

    async def get_daily_spend_usd(self, day_utc: date | None = None) -> float:
        if day_utc is None:
            day_utc = datetime.now(timezone.utc).date()
        async with self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM llm_usage_events WHERE date(created_at) = ?",
            (day_utc.isoformat(),),
        ) as cursor:
            row = await cursor.fetchone()
            return float(row["total"] if row else 0.0)

    async def get_runtime_flags(self) -> dict[str, Any]:
        await self._ensure_runtime_flags_row()
        async with self._conn.execute("SELECT * FROM runtime_flags WHERE id = 1") as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else {"llm_paused": 0, "pause_reason": None, "resume_override_until": None, "pause_day": None}

    async def pause_llm(self, reason: str, pause_day: date | None = None) -> None:
        pause_day = pause_day or datetime.now(timezone.utc).date()
        await self._conn.execute(
            "UPDATE runtime_flags SET llm_paused = 1, pause_reason = ?, pause_day = ?, resume_override_until = NULL, updated_at = datetime('now') WHERE id = 1",
            (reason, pause_day.isoformat()),
        )
        await self._conn.commit()

    async def clear_llm_pause(self) -> None:
        await self._conn.execute(
            "UPDATE runtime_flags SET llm_paused = 0, pause_reason = NULL, pause_day = NULL, resume_override_until = NULL, updated_at = datetime('now') WHERE id = 1"
        )
        await self._conn.commit()

    async def set_resume_override_until(self, until_dt: datetime) -> None:
        await self._conn.execute(
            "UPDATE runtime_flags SET llm_paused = 0, pause_reason = NULL, pause_day = NULL, resume_override_until = ?, updated_at = datetime('now') WHERE id = 1",
            (until_dt.astimezone(timezone.utc).isoformat(),),
        )
        await self._conn.commit()

    async def is_llm_paused(self, now_utc: datetime | None = None) -> bool:
        flags = await self.get_runtime_flags()
        if not bool(flags.get("llm_paused", 0)):
            return False
        now_utc = now_utc or datetime.now(timezone.utc)
        override_raw = flags.get("resume_override_until")
        if override_raw:
            try:
                override_dt = datetime.fromisoformat(override_raw)
                if override_dt.tzinfo is None:
                    override_dt = override_dt.replace(tzinfo=timezone.utc)
                if now_utc <= override_dt:
                    return False
            except ValueError:
                pass
        return True

    async def save_gtm_asset(self, *, post_id: str, model: str, payload: dict[str, Any]) -> int:
        async with self._conn.execute(
            "INSERT INTO gtm_assets (post_id, model, payload_json) VALUES (?, ?, ?)",
            (post_id, model, json.dumps(payload, ensure_ascii=False)),
        ) as cursor:
            await self._conn.commit()
            return int(cursor.lastrowid)

    async def get_latest_gtm_asset(self, post_id: str) -> dict[str, Any] | None:
        async with self._conn.execute(
            "SELECT * FROM gtm_assets WHERE post_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (post_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def record_feedback(
        self,
        *,
        post_id: str,
        feedback_value: str,
        source: str = "manual",
        actor_id: str | None = None,
        note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        normalized_value = normalize_feedback_value(feedback_value)
        normalized_post_id = str(post_id or "").strip()
        if not normalized_post_id:
            raise ValueError("post_id is required")
        async with self._conn.execute("SELECT 1 FROM pain_points WHERE post_id = ? LIMIT 1", (normalized_post_id,)) as cursor:
            existing = await cursor.fetchone()
        if existing is None:
            return None
        async with self._conn.execute(
            """
            INSERT INTO feedback_events (post_id, feedback_value, source, actor_id, note, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_post_id,
                normalized_value,
                str(source or "manual").strip()[:64] or "manual",
                str(actor_id).strip()[:128] if actor_id is not None else None,
                str(note).strip()[:500] if note is not None else None,
                json.dumps(metadata or {}, ensure_ascii=False, default=str),
            ),
        ) as cursor:
            await self._conn.commit()
            return int(cursor.lastrowid)

    async def list_feedback(self, *, post_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where_sql = ""
        if post_id is not None:
            where_sql = "WHERE post_id = ?"
            params.append(post_id)
        async with self._conn.execute(
            f"""
            SELECT * FROM feedback_events
            {where_sql}
            ORDER BY id ASC
            LIMIT ?
            """,  # nosec B608
            (*params, max(1, int(limit))),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_feedback_summary(self) -> dict[str, int]:
        summary = empty_feedback_summary()
        async with self._conn.execute(
            "SELECT feedback_value, COUNT(*) AS total FROM feedback_events GROUP BY feedback_value"
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            value = row["feedback_value"]
            if value in summary:
                summary[value] = int(row["total"] or 0)
        return summary

    async def enqueue_feedback_label_reviews(self, *, limit: int = 500) -> int:
        async with self._conn.execute(
            """
            SELECT f.*
            FROM feedback_events f
            LEFT JOIN label_review_queue q ON q.feedback_event_id = f.id
            WHERE q.id IS NULL
            ORDER BY f.id ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ) as cursor:
            feedback_rows = [dict(row) for row in await cursor.fetchall()]
        if not feedback_rows:
            return 0
        pain_points_by_id = await self.get_pain_points_by_ids([row["post_id"] for row in feedback_rows])
        created_count = 0
        for feedback_row in feedback_rows:
            pain_point = pain_points_by_id.get(feedback_row["post_id"])
            if pain_point is None:
                continue
            review_payload = build_feedback_label_review_row(feedback_row, pain_point=pain_point)
            cursor = await self._conn.execute(
                """
                INSERT OR IGNORE INTO label_review_queue (
                    feedback_event_id, post_id, review_status, review_payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    feedback_row["id"],
                    feedback_row["post_id"],
                    "pending",
                    json.dumps(review_payload, ensure_ascii=False, default=str),
                ),
            )
            created_count += max(0, cursor.rowcount)
        await self._conn.commit()
        return created_count

    async def list_label_review_queue(
        self,
        *,
        status: str | None = "pending",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where_sql = ""
        if status is not None:
            where_sql = "WHERE review_status = ?"
            params.append(status)
        async with self._conn.execute(
            f"""
            SELECT * FROM label_review_queue
            {where_sql}
            ORDER BY id ASC
            LIMIT ?
            """,  # nosec B608
            (*params, max(1, int(limit))),
        ) as cursor:
            rows = await cursor.fetchall()
        out = []
        for row in rows:
            row_dict = dict(row)
            row_dict["review_payload"] = self._decode_json_field(row_dict.get("review_payload_json"), {})
            out.append(row_dict)
        return out

    async def get_monitoring_summary(self) -> dict[str, Any]:
        async with self._conn.execute("SELECT COUNT(*) AS total FROM monitored_subreddits WHERE active = 1") as cursor:
            monitored_row = await cursor.fetchone()
        async with self._conn.execute("SELECT COUNT(*) AS total FROM pain_points WHERE triage_status = 'favorite'") as cursor:
            favorites_row = await cursor.fetchone()
        paused = await self.is_llm_paused()
        feedback_summary = await self.get_feedback_summary()
        return {
            "monitored": int(monitored_row["total"] if monitored_row else 0),
            "favorites": int(favorites_row["total"] if favorites_row else 0),
            "llm_paused": int(paused),
            "feedback_total": sum(feedback_summary.values()),
            "feedback": feedback_summary,
        }

    async def add_monitored_subreddit(self, name: str, interval_hours: int) -> None:
        await self._conn.execute(
            "INSERT INTO monitored_subreddits (name, interval_hours) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET interval_hours = excluded.interval_hours, active = 1",
            (name, interval_hours),
        )
        await self._conn.commit()

    async def remove_monitored_subreddit(self, name: str) -> None:
        await self._conn.execute("DELETE FROM monitored_subreddits WHERE name = ?", (name,))
        await self._conn.commit()

    async def get_monitored_subreddits(self) -> list[dict[str, Any]]:
        async with self._conn.execute("SELECT * FROM monitored_subreddits WHERE active = 1 ORDER BY name") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_last_checked(self, name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute("UPDATE monitored_subreddits SET last_checked = ? WHERE name = ?", (now, name))
        await self._conn.commit()

    async def save_report(self, *, subreddit: str, post_count: int, pain_count: int, json_path: str) -> int:
        async with self._conn.execute(
            "INSERT INTO reports (subreddit, post_count, pain_count, json_path) VALUES (?, ?, ?, ?)",
            (subreddit, post_count, pain_count, json_path),
        ) as cursor:
            await self._conn.commit()
            return int(cursor.lastrowid)

    async def get_latest_report(self, subreddit: str | None = None) -> dict[str, Any] | None:
        if subreddit:
            query = "SELECT * FROM reports WHERE subreddit = ? ORDER BY run_at DESC, id DESC LIMIT 1"
            params: tuple[Any, ...] = (subreddit,)
        else:
            query = "SELECT * FROM reports ORDER BY run_at DESC, id DESC LIMIT 1"
            params = ()
        async with self._conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
