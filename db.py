import json
import logging
from datetime import date, datetime, timezone
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

PAIN_POINT_STATUSES = {"new", "favorite", "discarded"}
DEEP_DIVE_STATUSES = {"not_requested", "queued", "running", "completed", "failed"}

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
    cluster_key TEXT,
    label TEXT,
    summary TEXT,
    estimated_monetization_signal TEXT,
    item_count INTEGER NOT NULL,
    aggregate_wtp REAL NOT NULL,
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

CREATE_GTM_ASSETS = """
CREATE TABLE IF NOT EXISTS gtm_assets (
    id INTEGER PRIMARY KEY,
    post_id TEXT NOT NULL,
    model TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
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
    "CREATE INDEX IF NOT EXISTS idx_reports_subreddit_run_at ON reports(subreddit, run_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_deep_dives_post_id ON deep_dives(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_runs_created_at ON analysis_runs(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pain_point_competitors_tag ON pain_point_competitors(competitor_tag)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_clusters_run ON macro_trend_clusters(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_macro_trend_members_run ON macro_trend_members(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_llm_usage_events_created ON llm_usage_events(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_gtm_assets_post ON gtm_assets(post_id, created_at DESC)",
]

PAIN_POINT_COLUMNS = {
    "is_monetizable": "INTEGER DEFAULT 0",
    "pain_level": "INTEGER DEFAULT 0",
    "willingness_to_pay": "INTEGER DEFAULT 0",
    "niche_category": "TEXT DEFAULT ''",
    "competitor_tags": "TEXT DEFAULT '[]'",
    "source": "TEXT DEFAULT 'reddit'",
    "triage_status": "TEXT DEFAULT 'new'",
    "analysis_mode": "TEXT DEFAULT 'legacy'",
    "deep_dive_status": "TEXT DEFAULT 'not_requested'",
    "deep_dive_summary": "TEXT",
    "analysis_payload_json": "TEXT",
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
        await self._conn.execute(CREATE_GTM_ASSETS)
        await self._conn.execute(CREATE_SCHEMA_MIGRATIONS)

        for query in CREATE_INDEXES:
            await self._conn.execute(query)

        await self._run_migrations()
        await self._ensure_runtime_flags_row()
        await self._conn.commit()

    async def _apply_pragmas(self) -> None:
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._conn.execute("PRAGMA busy_timeout=5000;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")

    async def _run_migrations(self) -> None:
        migration_names = ["2026_02_24_expand_pain_points", "2026_02_25_phase_5_8_expansion"]
        for migration_name in migration_names:
            if await self._is_migration_applied(migration_name):
                continue
            for column_name, ddl in PAIN_POINT_COLUMNS.items():
                await self._ensure_column("pain_points", column_name, ddl)
            await self._mark_migration_applied(migration_name)

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
        triage_status: str = "new",
        analysis_mode: str = "legacy",
        deep_dive_status: str = "not_requested",
        deep_dive_summary: str | None = None,
        analysis_payload: dict[str, Any] | None = None,
    ) -> None:
        if triage_status not in PAIN_POINT_STATUSES:
            triage_status = "new"
        if deep_dive_status not in DEEP_DIVE_STATUSES:
            deep_dive_status = "not_requested"

        normalized_tags = self._normalize_competitor_tags(competitor_tags)

        try:
            await self._conn.execute(
                """
                INSERT INTO pain_points (
                    subreddit, post_id, url, title, body, category, summary, severity,
                    is_monetizable, pain_level, willingness_to_pay, niche_category,
                    competitor_tags, source, triage_status, analysis_mode,
                    deep_dive_status, deep_dive_summary, analysis_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    triage_status,
                    analysis_mode,
                    deep_dive_status,
                    deep_dive_summary,
                    json.dumps(analysis_payload, ensure_ascii=False) if analysis_payload else None,
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
    ) -> list[dict[str, Any]]:
        conditions = ["triage_status != 'discarded'"]
        params: list[Any] = []
        if subreddit:
            conditions.append("subreddit = ?")
            params.append(subreddit)
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
        duration_ms: int | None,
        report_id: int | None,
    ) -> int:
        async with self._conn.execute(
            "INSERT INTO analysis_runs (subreddit, post_count, pain_count, monetizable_count, deep_dive_count, duration_ms, report_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (subreddit, post_count, pain_count, monetizable_count, deep_dive_count, duration_ms, report_id),
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
        cluster_key: str,
        label: str,
        summary: str,
        estimated_monetization_signal: str,
        item_count: int,
        aggregate_wtp: float,
        members: list[tuple[str, float]],
    ) -> int:
        async with self._conn.execute(
            "INSERT INTO macro_trend_clusters (run_id, cluster_key, label, summary, estimated_monetization_signal, item_count, aggregate_wtp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, cluster_key, label, summary, estimated_monetization_signal, item_count, aggregate_wtp),
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

    async def get_macro_clusters(self, run_id: int) -> list[dict[str, Any]]:
        async with self._conn.execute(
            """
            SELECT c.*, GROUP_CONCAT(m.post_id) AS post_ids
            FROM macro_trend_clusters c
            LEFT JOIN macro_trend_members m ON m.cluster_id = c.id
            WHERE c.run_id = ?
            GROUP BY c.id
            ORDER BY c.item_count DESC, c.aggregate_wtp DESC
            """,
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        out = []
        for row in rows:
            row_dict = dict(row)
            post_ids = row_dict.get("post_ids")
            row_dict["post_ids"] = post_ids.split(",") if isinstance(post_ids, str) and post_ids else []
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
            return dict(row) if row else None

    async def get_macro_candidates(self, *, window_days: int, min_wtp: int) -> list[dict[str, Any]]:
        async with self._conn.execute(
            """
            SELECT * FROM pain_points
            WHERE datetime(created_at) >= datetime('now', ?)
              AND triage_status != 'discarded'
              AND (triage_status = 'favorite' OR willingness_to_pay >= ?)
            ORDER BY willingness_to_pay DESC, pain_level DESC, created_at DESC
            """,
            (f"-{window_days} days", min_wtp),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_recent_pain_points(self, *, hours: int = 24, subreddit: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        params: list[Any] = [f"-{hours} hours"]
        query = "SELECT * FROM pain_points WHERE datetime(created_at) >= datetime('now', ?) AND triage_status != 'discarded'"
        if subreddit:
            query += " AND subreddit = ?"
            params.append(subreddit)
        query += " ORDER BY willingness_to_pay DESC, pain_level DESC, created_at DESC LIMIT ?"
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
    ) -> int:
        async with self._conn.execute(
            "INSERT INTO llm_usage_events (model, operation, prompt_tokens, completion_tokens, cost_usd, post_id) VALUES (?, ?, ?, ?, ?, ?)",
            (model, operation, prompt_tokens, completion_tokens, cost_usd, post_id),
        ) as cursor:
            await self._conn.commit()
            return int(cursor.lastrowid)

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
