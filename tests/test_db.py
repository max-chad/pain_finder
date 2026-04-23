import pytest_asyncio
import pytest
import sqlite3
from unittest.mock import patch

from db import Database
import json
from datetime import UTC, datetime, timedelta


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()


async def test_insert_and_fetch_pain_point(db):
    await db.insert_pain_point(
        subreddit="python",
        post_id="abc123",
        url="https://reddit.com/r/python/abc123",
        title="Why is X so broken",
        body="I can't get X to work",
        category="complaint",
        summary="User frustrated with X",
        severity="medium",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=9,
        niche_category="DevTools",
        source_created_at="2026-04-20T10:00:00+00:00",
        source_created_ts=1776688800,
        opportunity_bucket="current_opportunity",
    )
    results = await db.get_pain_points(subreddit="python")
    assert len(results) == 1
    assert results[0]["post_id"] == "abc123"
    assert results[0]["category"] == "complaint"
    assert results[0]["willingness_to_pay"] == 9
    assert results[0]["source_created_ts"] == 1776688800
    assert results[0]["opportunity_bucket"] == "current_opportunity"


async def test_duplicate_post_id_upserts(db):
    await db.insert_pain_point(
        subreddit="python",
        post_id="dup1",
        url="",
        title="First",
        body="",
        category="complaint",
        summary="one",
        severity="low",
    )
    await db.insert_pain_point(
        subreddit="python",
        post_id="dup1",
        url="",
        title="Second",
        body="",
        category="wish",
        summary="two",
        severity="high",
        willingness_to_pay=10,
    )

    results = await db.get_pain_points(subreddit="python")
    assert len(results) == 1
    assert results[0]["title"] == "Second"
    assert results[0]["willingness_to_pay"] == 10


async def test_monitor_subreddit_crud(db):
    await db.add_monitored_subreddit("webdev", interval_hours=6)
    subs = await db.get_monitored_subreddits()
    assert any(s["name"] == "webdev" for s in subs)

    await db.remove_monitored_subreddit("webdev")
    subs = await db.get_monitored_subreddits()
    assert not any(s["name"] == "webdev" for s in subs)


async def test_update_last_checked(db):
    await db.add_monitored_subreddit("python", interval_hours=12)
    await db.update_last_checked("python")
    subs = await db.get_monitored_subreddits()
    sub = next(s for s in subs if s["name"] == "python")
    assert sub["last_checked"] is not None


async def test_save_and_get_latest_report(db):
    await db.save_report(
        subreddit="python",
        post_count=1,
        pain_count=1,
        json_path="reports/old.json",
    )
    await db.save_report(
        subreddit="python",
        post_count=2,
        pain_count=2,
        json_path="reports/new.json",
    )
    latest = await db.get_latest_report(subreddit="python")
    assert latest is not None
    assert latest["json_path"] == "reports/new.json"


async def test_pragmas_applied(db):
    async with db._conn.execute("PRAGMA journal_mode") as cursor:
        journal_row = await cursor.fetchone()
    async with db._conn.execute("PRAGMA synchronous") as cursor:
        sync_row = await cursor.fetchone()
    async with db._conn.execute("PRAGMA foreign_keys") as cursor:
        fk_row = await cursor.fetchone()

    assert str(journal_row[0]).lower() == "wal"
    assert int(sync_row[0]) in {1, 2}  # NORMAL varies by sqlite build
    assert int(fk_row[0]) == 1


async def test_migrations_are_idempotent(db):
    await db._run_migrations()
    await db._run_migrations()

    async with db._conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE name = ?",
        ("2026_02_24_expand_pain_points",),
    ) as cursor:
        row = await cursor.fetchone()

    assert row[0] == 1


async def test_init_migrates_legacy_pain_points_before_creating_new_indexes(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE pain_points (
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
        )
        """
    )
    conn.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now'))) ")
    conn.commit()
    conn.close()

    database = Database(str(db_path))
    await database.init()
    row = await database.get_pain_point("missing")
    assert row is None
    await database.close()


async def test_triage_and_deep_dive_helpers(db):
    await db.insert_pain_point(
        subreddit="python",
        post_id="deep1",
        url="https://reddit.com/deep1",
        title="Need better sync",
        body="",
        category="wish",
        summary="Need inventory sync",
        severity="medium",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=8,
        niche_category="E-commerce",
    )

    updated = await db.update_triage_status("deep1", "favorite")
    assert updated is True

    await db.save_deep_dive(
        post_id="deep1",
        subreddit="python",
        source="manual",
        status="completed",
        payload={"actionable_summary": "Use SKU mapping"},
    )
    marked = await db.mark_deep_dive_status(
        "deep1",
        "completed",
        summary="Use SKU mapping",
    )
    assert marked is True

    row = await db.get_pain_point("deep1")
    assert row is not None
    assert row["triage_status"] == "favorite"
    assert row["deep_dive_status"] == "completed"


async def test_list_export_rows_filters_discarded_and_wtp(db):
    await db.insert_pain_point(
        subreddit="python",
        post_id="r1",
        url="",
        title="low",
        body="",
        category="complaint",
        summary="low",
        severity="low",
        willingness_to_pay=2,
        pain_level=2,
        source_created_ts=1776688800,
        opportunity_bucket="evergreen_pain",
    )
    await db.insert_pain_point(
        subreddit="python",
        post_id="r2",
        url="",
        title="high",
        body="",
        category="complaint",
        summary="high",
        severity="high",
        willingness_to_pay=9,
        pain_level=8,
        is_monetizable=True,
        source_created_ts=1776775200,
        opportunity_bucket="current_opportunity",
    )
    await db.insert_pain_point(
        subreddit="python",
        post_id="r3",
        url="",
        title="fav",
        body="",
        category="wish",
        summary="fav",
        severity="medium",
        willingness_to_pay=1,
        pain_level=2,
        is_monetizable=False,
        triage_status="favorite",
        source_created_ts=1776775201,
        opportunity_bucket="current_opportunity",
    )
    await db.insert_pain_point(
        subreddit="python",
        post_id="r4",
        url="",
        title="discarded",
        body="",
        category="wish",
        summary="discarded",
        severity="low",
        willingness_to_pay=10,
        pain_level=10,
        triage_status="discarded",
        source_created_ts=1776775202,
        opportunity_bucket="current_opportunity",
    )

    rows = await db.list_export_rows(
        subreddit="python",
        min_wtp=8,
        include_favorites=True,
        opportunity_bucket="current_opportunity",
    )
    ids = {row["post_id"] for row in rows}
    assert "r2" in ids
    assert "r3" in ids
    assert "r1" not in ids
    assert "r4" not in ids


async def test_get_recent_pain_points_filters_by_opportunity_bucket_and_source_age(db):
    now = datetime.now(UTC)
    fresh_ts = int((now - timedelta(days=5)).timestamp())
    stale_ts = int((now - timedelta(days=400)).timestamp())

    await db.insert_pain_point(
        subreddit="ops",
        post_id="fresh-current",
        url="",
        title="Need better approvals",
        body="",
        category="complaint",
        summary="fresh",
        severity="high",
        willingness_to_pay=9,
        pain_level=8,
        is_monetizable=True,
        source_created_ts=fresh_ts,
        source_created_at=datetime.fromtimestamp(fresh_ts, UTC).isoformat(),
        opportunity_bucket="current_opportunity",
    )
    await db.insert_pain_point(
        subreddit="ops",
        post_id="stale-evergreen",
        url="",
        title="Still migrating QuickBooks",
        body="",
        category="complaint",
        summary="stale",
        severity="high",
        willingness_to_pay=8,
        pain_level=8,
        is_monetizable=True,
        source_created_ts=stale_ts,
        source_created_at=datetime.fromtimestamp(stale_ts, UTC).isoformat(),
        opportunity_bucket="evergreen_pain",
    )

    current_rows = await db.get_recent_pain_points(hours=24 * 24, opportunity_bucket="current_opportunity")
    evergreen_rows = await db.get_recent_pain_points(hours=24 * 24, opportunity_bucket="evergreen_pain")
    aged_rows = await db.get_recent_pain_points(hours=24 * 24, max_source_age_days=180)

    assert {row["post_id"] for row in current_rows} == {"fresh-current"}
    assert {row["post_id"] for row in evergreen_rows} == {"stale-evergreen"}
    assert {row["post_id"] for row in aged_rows} == {"fresh-current"}


async def test_record_analysis_run_and_get_latest(db):
    run_id = await db.record_analysis_run(
        subreddit="python",
        post_count=100,
        pain_count=20,
        monetizable_count=5,
        deep_dive_count=2,
        skipped_existing_count=11,
        dedup_merged_count=3,
        screen_rule_dropped_count=17,
        screen_kept_count=21,
        screen_capped_count=4,
        duration_ms=1200,
        report_id=10,
    )
    assert run_id > 0

    latest = await db.get_latest_analysis_run("python")
    assert latest is not None
    assert latest["id"] == run_id
    assert latest["monetizable_count"] == 5
    assert latest["skipped_existing_count"] == 11
    assert latest["dedup_merged_count"] == 3
    assert latest["screen_rule_dropped_count"] == 17
    assert latest["screen_kept_count"] == 21
    assert latest["screen_capped_count"] == 4


async def test_init_migrates_existing_analysis_runs_with_old_migration_marker(tmp_path):
    db_path = tmp_path / "legacy_analysis_runs.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE analysis_runs (
            id INTEGER PRIMARY KEY,
            subreddit TEXT NOT NULL,
            post_count INTEGER NOT NULL,
            pain_count INTEGER NOT NULL,
            monetizable_count INTEGER NOT NULL,
            deep_dive_count INTEGER NOT NULL,
            skipped_existing_count INTEGER DEFAULT 0,
            dedup_merged_count INTEGER DEFAULT 0,
            duration_ms INTEGER,
            report_id INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE pain_points (
            id INTEGER PRIMARY KEY,
            subreddit TEXT NOT NULL,
            post_id TEXT UNIQUE NOT NULL,
            willingness_to_pay INTEGER DEFAULT 0,
            source TEXT DEFAULT 'reddit',
            source_created_ts INTEGER,
            opportunity_bucket TEXT DEFAULT 'unknown_age',
            triage_status TEXT DEFAULT 'new',
            emb_vector TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE TABLE monitored_subreddits (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, interval_hours INTEGER NOT NULL, last_checked TEXT, active INTEGER DEFAULT 1)")
    conn.execute("CREATE TABLE reports (id INTEGER PRIMARY KEY, subreddit TEXT NOT NULL, run_at TEXT DEFAULT (datetime('now')), post_count INTEGER, pain_count INTEGER, json_path TEXT)")
    conn.execute(
        """
        CREATE TABLE deep_dives (
            id INTEGER PRIMARY KEY,
            post_id TEXT UNIQUE NOT NULL,
            subreddit TEXT NOT NULL,
            source TEXT DEFAULT 'auto',
            status TEXT NOT NULL,
            payload_json TEXT,
            error TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE TABLE pain_point_competitors (post_id TEXT NOT NULL, competitor_tag TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')), PRIMARY KEY (post_id, competitor_tag))")
    conn.execute("CREATE TABLE macro_trend_runs (id INTEGER PRIMARY KEY, window_days INTEGER NOT NULL, candidate_count INTEGER NOT NULL, cluster_count INTEGER NOT NULL, created_at TEXT DEFAULT (datetime('now'))) ")
    conn.execute(
        """
        CREATE TABLE macro_trend_clusters (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            cluster_key TEXT,
            label TEXT,
            summary TEXT,
            estimated_monetization_signal TEXT,
            item_count INTEGER NOT NULL,
            aggregate_wtp REAL NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE TABLE macro_trend_members (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, cluster_id INTEGER NOT NULL, post_id TEXT NOT NULL, similarity REAL DEFAULT 0, created_at TEXT DEFAULT (datetime('now'))) ")
    conn.execute(
        """
        CREATE TABLE llm_usage_events (
            id INTEGER PRIMARY KEY,
            model TEXT NOT NULL,
            operation TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            post_id TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE TABLE runtime_flags (id INTEGER PRIMARY KEY CHECK (id = 1), llm_paused INTEGER DEFAULT 0, pause_reason TEXT, pause_day TEXT, resume_override_until TEXT, updated_at TEXT DEFAULT (datetime('now'))) ")
    conn.execute("CREATE TABLE llm_response_cache (cache_key TEXT PRIMARY KEY, model TEXT NOT NULL, operation TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))) ")
    conn.execute("CREATE TABLE gtm_assets (id INTEGER PRIMARY KEY, post_id TEXT NOT NULL, model TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now'))) ")
    conn.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now'))) ")
    conn.execute("INSERT INTO schema_migrations (name) VALUES ('2026_04_15_analysis_run_efficiency_metrics')")
    conn.commit()
    conn.close()

    database = Database(str(db_path))
    await database.init()
    try:
        run_id = await database.record_analysis_run(
            subreddit="ops",
            post_count=10,
            pain_count=4,
            monetizable_count=2,
            deep_dive_count=1,
            screen_rule_dropped_count=3,
            screen_kept_count=5,
            screen_capped_count=1,
            duration_ms=42,
            report_id=None,
        )
        latest = await database.get_latest_analysis_run("ops")
        assert run_id > 0
        assert latest is not None
        assert latest["screen_rule_dropped_count"] == 3
        assert latest["screen_kept_count"] == 5
        assert latest["screen_capped_count"] == 1
    finally:
        await database.close()


async def test_competitor_tags_are_normalized_and_queryable(db):
    await db.insert_pain_point(
        subreddit="python",
        post_id="reddit:comp1",
        url="",
        title="Shopify billing pain",
        body="",
        category="complaint",
        summary="Shopify API breaks often",
        severity="high",
        competitor_tags=["Shopify", "shopify", " jira ", ""],
        willingness_to_pay=9,
        pain_level=8,
        is_monetizable=True,
    )

    row = await db.get_pain_point("reddit:comp1")
    assert row is not None
    tags = json.loads(row["competitor_tags"])
    assert tags == ["shopify", "jira"]

    by_tag = await db.get_competitor_pain("shopify", days=30, limit=10)
    assert len(by_tag) == 1
    assert by_tag[0]["post_id"] == "reddit:comp1"

    top_tags = await db.get_top_competitor_tags(days=30, limit=10)
    assert any(item["tag"] == "shopify" for item in top_tags)


async def test_macro_tables_persist_and_query(db):
    await db.insert_pain_point(
        subreddit="python",
        post_id="reddit:m1",
        url="",
        title="API timeout",
        body="",
        category="complaint",
        summary="timeouts",
        severity="high",
        triage_status="favorite",
        willingness_to_pay=8,
        pain_level=8,
    )
    await db.insert_pain_point(
        subreddit="python",
        post_id="reddit:m2",
        url="",
        title="API timeout",
        body="",
        category="complaint",
        summary="timeouts 2",
        severity="high",
        triage_status="favorite",
        willingness_to_pay=9,
        pain_level=9,
    )

    run_id = await db.create_macro_trend_run(window_days=30, candidate_count=2, cluster_count=1)
    cluster_id = await db.save_macro_cluster(
        run_id=run_id,
        cluster_key="reddit:m1",
        label="API trend",
        summary="Recurring API failures",
        estimated_monetization_signal="high",
        item_count=2,
        aggregate_wtp=17.0,
        members=[("reddit:m1", 0.9), ("reddit:m2", 0.88)],
    )
    assert cluster_id > 0

    latest_run = await db.get_latest_macro_trend_run()
    assert latest_run is not None
    assert latest_run["id"] == run_id

    clusters = await db.get_macro_clusters(run_id)
    assert len(clusters) == 1
    assert set(clusters[0]["post_ids"]) == {"reddit:m1", "reddit:m2"}

    by_post = await db.get_latest_macro_cluster_for_post("reddit:m1")
    assert by_post is not None
    assert by_post["label"] == "API trend"

    candidates = await db.get_macro_candidates(window_days=30, min_wtp=8)
    ids = {row["post_id"] for row in candidates}
    assert {"reddit:m1", "reddit:m2"}.issubset(ids)


async def test_llm_response_cache_roundtrip(db):
    cache_key = "classify_primary:test-model:abc123"
    payload = {"category": "complaint", "summary": "Cached summary", "severity": "low"}

    await db.set_cached_llm_payload(cache_key=cache_key, model="test-model", operation="classify_primary", payload=payload)

    cached = await db.get_cached_llm_payload(cache_key)
    assert cached == payload


async def test_usage_ledger_and_runtime_flags(db):
    await db.record_llm_usage(
        model="model-a",
        operation="classify_primary",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.12,
        post_id="reddit:u1",
        prompt_hash="abc123",
        fallback_reason=None,
        schema_version="primary_v2",
        provider="openai-codex",
        request_path="https://chatgpt.com/backend-api/codex/responses",
        candidate_stage="primary",
    )
    await db.record_llm_usage(
        model="model-a",
        operation="deep_dive",
        prompt_tokens=200,
        completion_tokens=75,
        cost_usd=0.34,
        post_id="reddit:u2",
        prompt_hash="def456",
        fallback_reason="primary_invalid",
        schema_version="deep_dive_v1",
        provider="openrouter",
        request_path="https://openrouter.ai/api/v1/chat/completions",
        candidate_stage="deep_dive",
    )

    async with db._conn.execute(
        "SELECT prompt_hash, fallback_reason, schema_version, provider, request_path, candidate_stage "
        "FROM llm_usage_events WHERE post_id = ?",
        ("reddit:u2",),
    ) as cursor:
        usage_row = await cursor.fetchone()

    assert usage_row["prompt_hash"] == "def456"
    assert usage_row["fallback_reason"] == "primary_invalid"
    assert usage_row["schema_version"] == "deep_dive_v1"
    assert usage_row["provider"] == "openrouter"
    assert usage_row["candidate_stage"] == "deep_dive"

    spend = await db.get_daily_spend_usd()
    assert spend >= 0.46

    await db.pause_llm(reason="cap hit")
    assert await db.is_llm_paused() is True

    override_until = datetime.now(UTC) + timedelta(hours=1)
    await db.set_resume_override_until(override_until)
    assert await db.is_llm_paused() is False

    flags = await db.get_runtime_flags()
    assert flags["resume_override_until"] is not None

    await db.clear_llm_pause()
    assert await db.is_llm_paused() is False


async def test_gtm_assets_persist(db):
    asset_id = await db.save_gtm_asset(
        post_id="reddit:g1",
        model="model-g",
        payload={"name_options": ["A", "B", "C"]},
    )
    assert asset_id > 0

    latest = await db.get_latest_gtm_asset("reddit:g1")
    assert latest is not None
    assert latest["model"] == "model-g"


async def test_insert_pain_point_propagates_unexpected_db_errors(db):
    """Unexpected DB errors (e.g. disk full) must propagate, not be swallowed."""
    import aiosqlite

    fake_error = aiosqlite.OperationalError("disk I/O error")

    with patch.object(db._conn, "execute", side_effect=fake_error):
        with pytest.raises(aiosqlite.OperationalError, match="disk I/O error"):
            await db.insert_pain_point(
                subreddit="python",
                post_id="err1",
                url="",
                title="Trigger error",
                body="",
                category="complaint",
                summary="",
                severity="low",
            )


async def test_insert_pain_point_duplicate_post_id_does_not_raise(db):
    """ON CONFLICT DO UPDATE for duplicate post_id is expected behaviour and must not raise."""
    kwargs = dict(
        subreddit="python",
        post_id="dup_ok",
        url="",
        title="First insert",
        body="",
        category="complaint",
        summary="s",
        severity="low",
    )
    await db.insert_pain_point(**kwargs)
    # Second insert with the same post_id must succeed silently (upsert path).
    kwargs["title"] = "Second insert"
    await db.insert_pain_point(**kwargs)

    row = await db.get_pain_point("dup_ok")
    assert row is not None
    assert row["title"] == "Second insert"


async def test_get_pain_points_by_ids_returns_matching_rows(db):
    """get_pain_points_by_ids fetches all matching rows in a single query."""
    for post_id, title in [("batch1", "Alpha"), ("batch2", "Beta"), ("batch3", "Gamma")]:
        await db.insert_pain_point(
            subreddit="python",
            post_id=post_id,
            url="",
            title=title,
            body="",
            category="complaint",
            summary=title,
            severity="low",
            willingness_to_pay=5,
        )

    result = await db.get_pain_points_by_ids(["batch1", "batch3"])
    assert set(result.keys()) == {"batch1", "batch3"}
    assert result["batch1"]["title"] == "Alpha"
    assert result["batch3"]["title"] == "Gamma"


async def test_get_pain_points_by_ids_empty_input_returns_empty_dict(db):
    """get_pain_points_by_ids with an empty list must return {} without querying the DB."""
    result = await db.get_pain_points_by_ids([])
    assert result == {}


async def test_get_pain_points_by_ids_missing_ids_not_in_result(db):
    """post_ids that do not exist in the DB are simply absent from the returned dict."""
    await db.insert_pain_point(
        subreddit="python",
        post_id="exists1",
        url="",
        title="Existing",
        body="",
        category="complaint",
        summary="exists",
        severity="low",
    )

    result = await db.get_pain_points_by_ids(["exists1", "ghost_id"])
    assert "exists1" in result
    assert "ghost_id" not in result


async def test_dedup_columns_exist(db):
    """New columns exist after init."""
    row = await db.get_pain_point("nonexistent")
    assert row is None  # DB initialised cleanly

    await db.insert_pain_point(
        subreddit="test", post_id="col_check", url="", title="t", body="b",
        category="complaint", summary="s", severity="low",
    )
    row = await db.get_pain_point("col_check")
    assert row is not None
    assert "emb_vector" in row
    assert "cross_source_count" in row
    assert "cross_source_ids" in row
    assert row["cross_source_count"] == 1
    assert row["cross_source_ids"] == "[]"
    assert row["emb_vector"] is None


async def _insert_test_point(db, post_id, source="reddit"):
    """Helper to insert a minimal pain point."""
    await db.insert_pain_point(
        subreddit="test", post_id=post_id, url="", title="Test title",
        body="Test body", category="complaint", summary="s", severity="low",
        source=source,
    )


async def test_store_and_retrieve_embedding(db):
    await _insert_test_point(db, "emb1")
    vector = [0.1, 0.2, 0.3]
    await db.store_embedding("emb1", vector)
    rows = await db.get_pain_points_with_embeddings()
    assert len(rows) == 1
    assert rows[0]["post_id"] == "emb1"
    assert rows[0]["emb_vector"] == vector


async def test_get_pain_points_without_embeddings(db):
    await _insert_test_point(db, "no_emb1")
    await _insert_test_point(db, "no_emb2")
    await db.store_embedding("no_emb1", [0.5, 0.5])
    rows = await db.get_pain_points_without_embeddings()
    assert len(rows) == 1
    assert rows[0]["post_id"] == "no_emb2"
    assert "title" in rows[0]
    assert "body" in rows[0]


async def test_merge_duplicate_increments_count(db):
    await _insert_test_point(db, "canonical", source="reddit")
    await _insert_test_point(db, "dup1", source="hn")
    dup_vec = [0.9, 0.1]
    await db.merge_duplicate(
        canonical_post_id="canonical",
        dup_post_id="dup1",
        dup_emb_vector=dup_vec,
    )
    canonical = await db.get_pain_point("canonical")
    assert canonical["cross_source_count"] == 2
    cross_source_ids = json.loads(canonical["cross_source_ids"])
    assert "dup1" in cross_source_ids
    assert canonical["cross_source_count"] == len(cross_source_ids) + 1
    assert len(cross_source_ids) == len(set(cross_source_ids))

    dup = await db.get_pain_point("dup1")
    assert dup["triage_status"] == "merged"
    stored_vec = json.loads(dup["emb_vector"])
    assert stored_vec == dup_vec


async def test_merge_duplicate_same_id_is_idempotent_for_count(db):
    await _insert_test_point(db, "canonical_idem", source="reddit")
    await _insert_test_point(db, "dup_idem", source="hn")
    dup_vec = [0.3, 0.7]

    await db.merge_duplicate(
        canonical_post_id="canonical_idem",
        dup_post_id="dup_idem",
        dup_emb_vector=dup_vec,
    )
    await db.merge_duplicate(
        canonical_post_id="canonical_idem",
        dup_post_id="dup_idem",
        dup_emb_vector=dup_vec,
    )

    canonical = await db.get_pain_point("canonical_idem")
    assert canonical is not None
    assert canonical["cross_source_count"] == 2
    cross_source_ids = json.loads(canonical["cross_source_ids"])
    assert cross_source_ids == ["dup_idem"]
    assert canonical["cross_source_count"] == len(cross_source_ids) + 1
    assert len(cross_source_ids) == len(set(cross_source_ids))

    dup = await db.get_pain_point("dup_idem")
    assert dup is not None
    assert dup["triage_status"] == "merged"
    assert json.loads(dup["emb_vector"]) == dup_vec


async def test_merge_duplicate_multistep_sequence_preserves_invariants(db):
    await _insert_test_point(db, "canonical_multi", source="reddit")
    await _insert_test_point(db, "dup_a", source="hn")
    await _insert_test_point(db, "dup_b", source="twitter")

    await db.merge_duplicate(
        canonical_post_id="canonical_multi",
        dup_post_id="dup_a",
        dup_emb_vector=[0.11, 0.89],
    )
    await db.merge_duplicate(
        canonical_post_id="canonical_multi",
        dup_post_id="dup_b",
        dup_emb_vector=[0.22, 0.78],
    )
    await db.merge_duplicate(
        canonical_post_id="canonical_multi",
        dup_post_id="dup_a",
        dup_emb_vector=[0.11, 0.89],
    )

    canonical = await db.get_pain_point("canonical_multi")
    assert canonical is not None
    cross_source_ids = json.loads(canonical["cross_source_ids"])
    assert set(cross_source_ids) == {"dup_a", "dup_b"}
    assert canonical["cross_source_count"] == len(cross_source_ids) + 1
    assert len(cross_source_ids) == len(set(cross_source_ids))

    dup_a = await db.get_pain_point("dup_a")
    dup_b = await db.get_pain_point("dup_b")
    assert dup_a is not None
    assert dup_b is not None
    assert dup_a["triage_status"] == "merged"
    assert dup_b["triage_status"] == "merged"
