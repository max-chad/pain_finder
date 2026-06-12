import json
import logging
import math
from datetime import date, datetime, timezone
from typing import Any

import aiosqlite

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
    opportunity_bucket TEXT DEFAULT 'unknown_age',
    post_type TEXT DEFAULT 'advice_thread',
    first_handness TEXT DEFAULT 'unknown',
    buyer_authority TEXT DEFAULT 'unknown',
    evidence_spans_json TEXT DEFAULT '[]',
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
    created_at TEXT DEFAULT (datetime('now'))
)"""

CREATE_MONITORED = """
CREATE TABLE IF NOT EXISTS monitored_subreddits (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    interval_hours INTEGER NOT NULL,
    last_checked TEXT,
    last_attempted_at TEXT,
    last_error TEXT,
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
    latest_source_created_ts INTEGER,
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

CREATE_SCHEDULED_JOB_STATUS = """
CREATE TABLE IF NOT EXISTS scheduled_job_status (
    job_name TEXT PRIMARY KEY,
    last_attempted_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
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
    "CREATE INDEX IF NOT EXISTS idx_pain_points_opportunity_bucket ON pain_points(opportunity_bucket)",
    "CREATE INDEX IF NOT EXISTS idx_pain_points_source_created_ts ON pain_points(source_created_ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pain_points_opportunity_score ON pain_points(opportunity_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reports_subreddit_run_at ON reports(subreddit, run_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_deep_dives_post_id ON deep_dives(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_runs_created_at ON analysis_runs(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pain_point_competitors_tag ON pain_point_competitors(competitor_tag)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_clusters_run ON macro_trend_clusters(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_clusters_canonical ON macro_trend_clusters(canonical_key)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_members_run ON macro_trend_members(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_members_post ON macro_trend_members(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_llm_usage_events_created ON llm_usage_events(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_llm_usage_events_stage ON llm_usage_events(candidate_stage, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_llm_response_cache_updated ON llm_response_cache(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_gtm_assets_post ON gtm_assets(post_id, created_at DESC)",
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
    "opportunity_bucket": "TEXT DEFAULT 'unknown_age'",
    "post_type": "TEXT DEFAULT 'advice_thread'",
    "first_handness": "TEXT DEFAULT 'unknown'",
    "buyer_authority": "TEXT DEFAULT 'unknown'",
    "evidence_spans_json": "TEXT DEFAULT '[]'",
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

MONITORED_SUBREDDIT_COLUMNS = {
    "last_attempted_at": "TEXT",
    "last_error": "TEXT",
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
    "latest_source_created_ts": "INTEGER",
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
        await self._conn.execute(CREATE_PAIN_POINT_COMPETITORS)
        await self._conn.execute(CREATE_MACRO_TREND_RUNS)
        await self._conn.execute(CREATE_MACRO_TREND_CLUSTERS)
        await self._conn.execute(CREATE_MACRO_TREND_MEMBERS)
        await self._conn.execute(CREATE_LLM_USAGE_EVENTS)
        await self._conn.execute(CREATE_RUNTIME_FLAGS)
        await self._conn.execute(CREATE_LLM_RESPONSE_CACHE)
        await self._conn.execute(CREATE_GTM_ASSETS)
        await self._conn.execute(CREATE_SCHEDULED_JOB_STATUS)
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

        monitored_observability_migration = "2026_05_25_monitored_subreddit_attempt_state"
        if not await self._is_migration_applied(monitored_observability_migration):
            for column_name, ddl in MONITORED_SUBREDDIT_COLUMNS.items():
                await self._ensure_column("monitored_subreddits", column_name, ddl)
            await self._mark_migration_applied(monitored_observability_migration)

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
    def _finite_float(value: Any, field_name: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a number") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"{field_name} must be finite")
        return parsed

    @staticmethod
    def _non_negative_int(value: Any, field_name: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field_name} must be a non-negative integer") from exc
        if parsed < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return parsed

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
        opportunity_bucket: str = "unknown_age",
        post_type: str = "advice_thread",
        first_handness: str = "unknown",
        buyer_authority: str = "unknown",
        evidence_spans: list[str] | None = None,
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
        emb_vector: list[float] | None = None,
    ) -> None:
        if triage_status not in PAIN_POINT_STATUSES:
            triage_status = "new"
        if deep_dive_status not in DEEP_DIVE_STATUSES:
            deep_dive_status = "not_requested"

        normalized_tags = self._normalize_competitor_tags(competitor_tags)
        if opportunity_bucket not in OPPORTUNITY_BUCKETS:
            opportunity_bucket = "unknown_age"
        normalized_evidence_spans = [
            str(item).strip()[:160]
            for item in (evidence_spans or [])
            if isinstance(item, str) and str(item).strip()
        ][:3]
        normalized_comment_sample = [
            str(item).strip()[:240]
            for item in (comment_sample or [])
            if isinstance(item, str) and str(item).strip()
        ][:5]
        normalized_comment_tool_mentions = self._normalize_competitor_tags(comment_tool_mentions)
        score_components_json = json.dumps(score_components or {}, ensure_ascii=False)
        buyer_authority_score_value = self._finite_float(buyer_authority_score, "buyer_authority_score")
        workflow_frequency_score_value = self._finite_float(workflow_frequency_score, "workflow_frequency_score")
        impact_score_value = self._finite_float(impact_score, "impact_score")
        consensus_score_value = self._finite_float(consensus_score, "consensus_score")
        incumbent_failure_score_value = self._finite_float(incumbent_failure_score, "incumbent_failure_score")
        recency_score_value = self._finite_float(recency_score, "recency_score")
        stale_penalty_value = self._finite_float(stale_penalty, "stale_penalty")
        solved_penalty_value = self._finite_float(solved_penalty, "solved_penalty")
        opportunity_score_value = self._finite_float(opportunity_score, "opportunity_score")
        comment_shill_risk_value = self._finite_float(comment_shill_risk, "comment_shill_risk")

        try:
            await self._conn.execute(
                """
                INSERT INTO pain_points (
                    subreddit, post_id, url, title, body, category, summary, severity,
                    is_monetizable, pain_level, willingness_to_pay, niche_category,
                    competitor_tags, source, source_created_at, source_created_ts, author_name,
                    opportunity_bucket, post_type, first_handness, buyer_authority, evidence_spans_json,
                    comment_sample_json, buyer_authority_score, workflow_frequency_score, impact_score,
                    consensus_score, incumbent_failure_score, recency_score, stale_penalty, solved_penalty,
                    opportunity_score, score_components_json, comment_consensus_count, comment_same_here_count,
                    comment_workaround_count, comment_tool_mentions_json, comment_shill_risk,
                    triage_status, analysis_mode, deep_dive_status, deep_dive_summary, analysis_payload_json,
                    emb_vector
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    opportunity_bucket = excluded.opportunity_bucket,
                    post_type = excluded.post_type,
                    first_handness = excluded.first_handness,
                    buyer_authority = excluded.buyer_authority,
                    evidence_spans_json = excluded.evidence_spans_json,
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
                    opportunity_bucket,
                    post_type,
                    first_handness,
                    buyer_authority,
                    json.dumps(normalized_evidence_spans, ensure_ascii=False),
                    json.dumps(normalized_comment_sample, ensure_ascii=False),
                    buyer_authority_score_value,
                    workflow_frequency_score_value,
                    impact_score_value,
                    consensus_score_value,
                    incumbent_failure_score_value,
                    recency_score_value,
                    stale_penalty_value,
                    solved_penalty_value,
                    opportunity_score_value,
                    score_components_json,
                    int(comment_consensus_count),
                    int(comment_same_here_count),
                    int(comment_workaround_count),
                    json.dumps(normalized_comment_tool_mentions, ensure_ascii=False),
                    comment_shill_risk_value,
                    triage_status,
                    analysis_mode,
                    deep_dive_status,
                    deep_dive_summary,
                    json.dumps(analysis_payload, ensure_ascii=False) if analysis_payload else None,
                    json.dumps(emb_vector) if emb_vector is not None else None,
                ),
            )
            await self._replace_competitor_tags(post_id, normalized_tags)
            await self._conn.commit()
        except Exception as e:
            await self._conn.rollback()
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

        async with self._conn.execute(
            "SELECT triage_status, deep_dive_status, deep_dive_summary FROM pain_points WHERE post_id = ?",
            (dup_post_id,),
        ) as cursor:
            dup_row = await cursor.fetchone()

        current_ids: list[str] = json.loads(row["cross_source_ids"] or "[]")
        should_increment_count = dup_post_id not in current_ids
        if should_increment_count:
            current_ids.append(dup_post_id)
        promote_favorite = bool(dup_row and dup_row["triage_status"] == "favorite")
        promote_completed_deep_dive = bool(dup_row and dup_row["deep_dive_status"] == "completed")
        duplicate_deep_dive_summary = dup_row["deep_dive_summary"] if dup_row else None

        try:
            await self._conn.execute(
                "UPDATE pain_points SET cross_source_count = cross_source_count + ?, "
                "cross_source_ids = ?, "
                "triage_status = CASE WHEN ? THEN 'favorite' ELSE triage_status END, "
                "deep_dive_status = CASE "
                "WHEN ? AND deep_dive_status != 'completed' THEN 'completed' "
                "ELSE deep_dive_status END, "
                "deep_dive_summary = CASE "
                "WHEN ? AND (deep_dive_status != 'completed' OR deep_dive_summary IS NULL) "
                "THEN COALESCE(?, deep_dive_summary) "
                "ELSE deep_dive_summary END "
                "WHERE post_id = ?",
                (
                    int(should_increment_count),
                    json.dumps(current_ids),
                    int(promote_favorite),
                    int(promote_completed_deep_dive),
                    int(promote_completed_deep_dive),
                    duplicate_deep_dive_summary,
                    canonical_post_id,
                ),
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
              AND p.triage_status NOT IN ('discarded', 'merged')
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
              AND p.triage_status NOT IN ('discarded', 'merged')
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
        query += (
            " ORDER BY CASE WHEN triage_status = 'favorite' THEN 0 ELSE 1 END, "
            "opportunity_score DESC, willingness_to_pay DESC, pain_level DESC, created_at DESC"
        )  # nosec B608
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
        window_days_value = self._non_negative_int(window_days, "window_days")
        if window_days_value <= 0:
            raise ValueError("window_days must be positive")
        candidate_count_value = self._non_negative_int(candidate_count, "candidate_count")
        cluster_count_value = self._non_negative_int(cluster_count, "cluster_count")
        async with self._conn.execute(
            "INSERT INTO macro_trend_runs (window_days, candidate_count, cluster_count) VALUES (?, ?, ?)",
            (window_days_value, candidate_count_value, cluster_count_value),
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
        latest_source_created_ts: int | None = None,
        members: list[tuple[str, float]],
    ) -> int:
        item_count_value = self._non_negative_int(item_count, "item_count")
        aggregate_wtp_value = self._finite_float(aggregate_wtp, "aggregate_wtp")
        fresh_post_count_value = self._non_negative_int(fresh_post_count, "fresh_post_count")
        evergreen_post_count_value = self._non_negative_int(evergreen_post_count, "evergreen_post_count")
        median_buyer_authority_value = self._finite_float(median_buyer_authority, "median_buyer_authority")
        avg_opportunity_score_value = self._finite_float(avg_opportunity_score, "avg_opportunity_score")
        latest_source_created_ts_value = (
            None
            if latest_source_created_ts is None
            else self._non_negative_int(latest_source_created_ts, "latest_source_created_ts")
        )
        member_rows = [
            (post_id, self._finite_float(similarity, "member similarity"))
            for post_id, similarity in members
        ]
        async with self._conn.execute(
            """
            INSERT INTO macro_trend_clusters (
                run_id, canonical_key, cluster_key, label, summary, estimated_monetization_signal,
                item_count, aggregate_wtp, fresh_post_count, evergreen_post_count,
                median_buyer_authority, incumbents_json, avg_opportunity_score, latest_source_created_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                canonical_key,
                cluster_key,
                label,
                summary,
                estimated_monetization_signal,
                item_count_value,
                aggregate_wtp_value,
                fresh_post_count_value,
                evergreen_post_count_value,
                median_buyer_authority_value,
                json.dumps(incumbents or [], ensure_ascii=False),
                avg_opportunity_score_value,
                latest_source_created_ts_value,
            ),
        ) as cursor:
            cluster_id = int(cursor.lastrowid)
        for post_id, similarity in member_rows:
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
            incumbents_raw = row_dict.get("incumbents_json")
            if isinstance(incumbents_raw, str) and incumbents_raw.strip():
                try:
                    row_dict["incumbents"] = json.loads(incumbents_raw)
                except json.JSONDecodeError:
                    row_dict["incumbents"] = []
            else:
                row_dict["incumbents"] = []
            out.append(row_dict)
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
            incumbents_raw = row_dict.get("incumbents_json")
            if isinstance(incumbents_raw, str) and incumbents_raw.strip():
                try:
                    row_dict["incumbents"] = json.loads(incumbents_raw)
                except json.JSONDecodeError:
                    row_dict["incumbents"] = []
            else:
                row_dict["incumbents"] = []
            return row_dict

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
            incumbents_raw = row_dict.get("incumbents_json")
            if isinstance(incumbents_raw, str) and incumbents_raw.strip():
                try:
                    row_dict["incumbents"] = json.loads(incumbents_raw)
                except json.JSONDecodeError:
                    row_dict["incumbents"] = []
            else:
                row_dict["incumbents"] = []
            out.append(row_dict)
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
            ORDER BY opportunity_score DESC, willingness_to_pay DESC, pain_level DESC, created_at DESC
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
        if prompt_tokens < 0 or completion_tokens < 0:
            raise ValueError("token counts must be non-negative")
        if not math.isfinite(cost_usd) or cost_usd < 0:
            raise ValueError("cost_usd must be finite and non-negative")
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

    async def get_monitoring_summary(self) -> dict[str, int]:
        async with self._conn.execute("SELECT COUNT(*) AS total FROM monitored_subreddits WHERE active = 1") as cursor:
            monitored_row = await cursor.fetchone()
        async with self._conn.execute("SELECT COUNT(*) AS total FROM pain_points WHERE triage_status = 'favorite'") as cursor:
            favorites_row = await cursor.fetchone()
        paused = await self.is_llm_paused()
        return {
            "monitored": int(monitored_row["total"] if monitored_row else 0),
            "favorites": int(favorites_row["total"] if favorites_row else 0),
            "llm_paused": int(paused),
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
        await self._conn.execute(
            "UPDATE monitored_subreddits SET last_checked = ?, last_attempted_at = ?, last_error = NULL WHERE name = ?",
            (now, now, name),
        )
        await self._conn.commit()

    async def mark_monitor_failed(self, name: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE monitored_subreddits SET last_attempted_at = ?, last_error = ? WHERE name = ?",
            (now, error[:1000], name),
        )
        await self._conn.commit()

    async def mark_scheduled_job_success(self, job_name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            """
            INSERT INTO scheduled_job_status (
                job_name, last_attempted_at, last_success_at, last_error, updated_at
            )
            VALUES (?, ?, ?, NULL, ?)
            ON CONFLICT(job_name) DO UPDATE SET
                last_attempted_at = excluded.last_attempted_at,
                last_success_at = excluded.last_success_at,
                last_error = NULL,
                updated_at = excluded.updated_at
            """,
            (job_name, now, now, now),
        )
        await self._conn.commit()

    async def mark_scheduled_job_failure(self, job_name: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            """
            INSERT INTO scheduled_job_status (
                job_name, last_attempted_at, last_success_at, last_error, updated_at
            )
            VALUES (?, ?, NULL, ?, ?)
            ON CONFLICT(job_name) DO UPDATE SET
                last_attempted_at = excluded.last_attempted_at,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (job_name, now, error[:1000], now),
        )
        await self._conn.commit()

    async def get_scheduled_job_statuses(self) -> list[dict[str, Any]]:
        async with self._conn.execute("SELECT * FROM scheduled_job_status ORDER BY job_name") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

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
