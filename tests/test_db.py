import pytest_asyncio
import pytest
import sqlite3
from unittest.mock import patch

from db import Database
from scraper import RedditComment
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


async def test_insert_pain_point_persists_deletion_flags_and_author_hash(db):
    await db.insert_pain_point(
        subreddit="python",
        post_id="deleted-post",
        url="https://reddit.com/r/python/comments/deleted-post",
        title="Removed body",
        body="[removed]",
        category="complaint",
        summary="Post body is unavailable",
        severity="medium",
        is_removed=True,
        body_available=False,
        deleted_detected_at="2026-04-26T12:00:00+00:00",
        author_hash="abc123hash",
    )

    row = await db.get_pain_point("deleted-post")

    assert row is not None
    assert row["is_deleted"] == 0
    assert row["is_removed"] == 1
    assert row["body_available"] == 0
    assert row["deleted_detected_at"] == "2026-04-26T12:00:00+00:00"
    assert row["author_hash"] == "abc123hash"


async def test_comments_upsert_is_idempotent_and_updates_existing_rows(db):
    first = RedditComment(
        comment_id="reddit:t1_c1",
        post_id="reddit:p1",
        parent_id="reddit:p1",
        body="First version",
        body_hash="hash-one",
        author_hash="author-one",
        score=1,
        created_utc=1713600100,
        depth=0,
        is_op=False,
        is_deleted=False,
        permalink="/r/python/comments/p1/post/c1/",
        fetched_at="2026-04-26T12:00:00+00:00",
    )
    second = RedditComment(
        comment_id="reddit:t1_c1",
        post_id="reddit:p1",
        parent_id="reddit:p1",
        body="[deleted]",
        body_hash="hash-two",
        author_hash="author-one",
        score=5,
        created_utc=1713600100,
        depth=0,
        is_op=False,
        is_deleted=True,
        permalink="/r/python/comments/p1/post/c1/",
        fetched_at="2026-04-26T12:05:00+00:00",
        body_available=False,
        deleted_detected_at="2026-04-26T12:05:00+00:00",
    )

    await db.upsert_comments([first])
    await db.upsert_comments([second])
    rows = await db.get_comments_for_post("reddit:p1")

    assert len(rows) == 1
    assert rows[0]["comment_id"] == "reddit:t1_c1"
    assert rows[0]["body"] == "[deleted]"
    assert rows[0]["score"] == 5
    assert rows[0]["is_deleted"] == 1
    assert rows[0]["is_removed"] == 0
    assert rows[0]["body_available"] == 0
    assert rows[0]["deleted_detected_at"] == "2026-04-26T12:05:00+00:00"
    assert rows[0]["fetched_at"] == "2026-04-26T12:05:00+00:00"


async def test_insert_pain_point_persists_verified_evidence_quality(db):
    verified = [
        {
            "quote": "stock sync lags",
            "source_type": "body",
            "post_id": "verified1",
            "comment_id": None,
            "permalink": "https://reddit.com/r/shopify/comments/verified1",
            "match_type": "exact",
            "match_confidence": 1.0,
            "created_utc": 1776688800,
        }
    ]

    await db.insert_pain_point(
        subreddit="shopify",
        post_id="verified1",
        url="https://reddit.com/r/shopify/comments/verified1",
        title="Shopify sync broken",
        body="stock sync lags every day",
        category="complaint",
        summary="Inventory sync lag",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=9,
        verified_evidence=verified,
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        confidence=0.82,
        uncertainty_reason="",
        needs_human_review=False,
    )

    row = await db.get_pain_point("verified1")
    assert row is not None
    assert json.loads(row["verified_evidence_json"]) == verified
    assert row["evidence_quality"] == "exact_quote"
    assert row["evidence_match_rate"] == 1.0


async def test_insert_pain_point_persists_wave5_taxonomy_fields(db):
    user_context = {
        "role": "ops_lead",
        "industry": "ecommerce",
        "company_size": "50-200",
        "tool_stack": ["shopify", "netsuite"],
        "process": "inventory reconciliation",
    }
    score_components = {
        "weights": {"intensity": 0.18, "frequency": 0.14},
        "raw_score": 71.2,
        "promotion_eligible": True,
    }

    await db.insert_pain_point(
        subreddit="shopify",
        post_id="wave5-taxonomy",
        url="https://reddit.com/r/shopify/comments/wave5-taxonomy",
        title="Inventory sync blocks fulfillment",
        body="Ops lead here. We still reconcile inventory in spreadsheets before every fulfillment run.",
        category="complaint",
        summary="Inventory reconciliation is blocking fulfillment.",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=9,
        pain_type="integration_gap",
        expression_type="feature_request",
        user_context_json=user_context,
        intensity_score=0.82,
        frequency_signal="thread_consensus",
        urgency="active_blocker",
        current_workaround="spreadsheet",
        wtp_score=0.91,
        incumbent_failure="explicit_competitor_failure",
        opportunity_type="automation",
        opportunity_score=71.2,
        score_components=score_components,
        confidence=0.82,
        needs_human_review=False,
    )

    row = await db.get_pain_point("wave5-taxonomy")

    assert row is not None
    assert row["pain_type"] == "integration_gap"
    assert row["expression_type"] == "feature_request"
    assert json.loads(row["user_context_json"]) == user_context
    assert row["intensity_score"] == 0.82
    assert row["frequency_signal"] == "thread_consensus"
    assert row["urgency"] == "active_blocker"
    assert row["current_workaround"] == "spreadsheet"
    assert row["wtp_score"] == 0.91
    assert row["incumbent_failure"] == "explicit_competitor_failure"
    assert row["opportunity_type"] == "automation"
    assert json.loads(row["score_components_json"]) == score_components
    assert row["confidence"] == 0.82
    assert row["needs_human_review"] == 0


async def test_insert_pain_point_coerces_evidence_quality_numbers_and_review_flag(db):
    await db.insert_pain_point(
        subreddit="shopify",
        post_id="coerce-evidence",
        url="https://reddit.com/r/shopify/comments/coerce-evidence",
        title="Shopify sync broken",
        body="stock sync lags every day",
        category="complaint",
        summary="Inventory sync lag",
        severity="high",
        evidence_match_rate="-0.2",
        confidence="1.5",
        needs_human_review="yes",
    )

    row = await db.get_pain_point("coerce-evidence")
    assert row is not None
    assert row["evidence_match_rate"] == 0.0
    assert row["confidence"] == 1.0
    assert row["needs_human_review"] == 1


async def test_insert_pain_point_preserves_linked_multi_source_evidence_quality(db):
    await db.insert_pain_point(
        subreddit="shopify",
        post_id="linked-multi-source",
        url="https://reddit.com/r/shopify/comments/linked-multi-source",
        title="Shopify sync broken",
        body="stock sync lags every day",
        category="complaint",
        summary="Inventory sync lag",
        severity="high",
        verified_evidence=[{"quote": "stock sync lags", "match_type": "exact"}],
        evidence_quality="linked_multi_source",
        evidence_match_rate=1.0,
        confidence=0.9,
    )

    row = await db.get_pain_point("linked-multi-source")
    assert row is not None
    assert row["evidence_quality"] == "linked_multi_source"


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


async def test_wave3_tables_and_columns_exist_after_init(db):
    async with db._conn.execute("PRAGMA table_info(pain_points)") as cursor:
        pain_columns = {row["name"] for row in await cursor.fetchall()}
    async with db._conn.execute("PRAGMA table_info(comments)") as cursor:
        comment_columns = {row["name"] for row in await cursor.fetchall()}
    async with db._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
        tables = {row["name"] for row in await cursor.fetchall()}
    assert {"comments", "source_ingestion_cursors", "source_coverage_runs"}.issubset(tables)
    assert {
        "is_deleted",
        "is_removed",
        "body_available",
        "deleted_detected_at",
        "author_hash",
    }.issubset(pain_columns)
    assert {"is_deleted", "is_removed", "body_available", "deleted_detected_at", "author_hash"}.issubset(comment_columns)


async def test_cursor_upsert_and_get_roundtrip(db):
    await db.upsert_source_ingestion_cursor(
        source="reddit",
        subreddit="python",
        feed="top",
        query="manual workaround",
        timeframe="week",
        after="t3_after",
        before="t3_before",
        time_window="2026-W17",
        last_seen_created_utc=1713600100,
        last_success_at="2026-04-26T12:00:00+00:00",
        fetch_errors=["timeout"],
    )
    await db.upsert_source_ingestion_cursor(
        source="reddit",
        subreddit="python",
        feed="top",
        query="manual workaround",
        timeframe="week",
        after="t3_after2",
        before=None,
        time_window="2026-W17",
        last_seen_created_utc=1713600200,
        last_success_at="2026-04-26T12:05:00+00:00",
        fetch_errors=[],
    )

    cursor_row = await db.get_source_ingestion_cursor(
        source="reddit",
        subreddit="python",
        feed="top",
        query="manual workaround",
        timeframe="week",
    )

    assert cursor_row is not None
    assert cursor_row["after"] == "t3_after2"
    assert cursor_row["before"] is None
    assert cursor_row["last_seen_created_utc"] == 1713600200
    assert json.loads(cursor_row["fetch_errors_json"]) == []


async def test_coverage_run_record_and_list_roundtrip(db):
    run_id = await db.record_source_coverage_run(
        source="reddit",
        scope="python",
        fetched_posts=25,
        fetched_comments=75,
        skipped_deleted=3,
        skipped_duplicates=4,
        failed_requests=1,
        source_method_used="public_json",
        duration_ms=1234,
    )

    rows = await db.list_source_coverage_runs(source="reddit", scope="python", limit=5)

    assert run_id > 0
    assert len(rows) == 1
    assert rows[0]["id"] == run_id
    assert rows[0]["fetched_posts"] == 25
    assert rows[0]["fetched_comments"] == 75
    assert rows[0]["skipped_deleted"] == 3
    assert rows[0]["skipped_duplicates"] == 4
    assert rows[0]["failed_requests"] == 1
    assert rows[0]["source_method_used"] == "public_json"


async def test_normalized_frequency_helper_uses_coverage_and_unique_hashes(db):
    await db.record_source_coverage_run(
        source="reddit",
        scope="python",
        fetched_posts=200,
        fetched_comments=800,
        source_method_used="public_json",
        duration_ms=50,
    )
    for post_id, author_hash in [
        ("freq-1", "author-a"),
        ("freq-2", "author-a"),
        ("freq-3", "author-b"),
    ]:
        await db.insert_pain_point(
            subreddit="python",
            post_id=post_id,
            url="",
            title=f"Pain {post_id}",
            body="manual workflow",
            category="complaint",
            summary="manual workflow pain",
            severity="high",
            source="reddit",
            author_hash=author_hash,
        )

    metrics = await db.calculate_normalized_frequency(
        source="reddit",
        scope="python",
        post_ids=["freq-1", "freq-2", "freq-3"],
    )

    await db.update_pain_points_frequency_metrics(post_ids=["freq-1", "freq-2", "freq-3"], metrics=metrics)
    updated = await db.get_pain_point("freq-1")

    assert metrics["pain_mentions_per_1000_posts"] == pytest.approx(15.0)
    assert metrics["pain_mentions_per_1000_comments"] == pytest.approx(3.75)
    assert metrics["unique_authors_count"] == 2
    assert metrics["unique_threads_count"] == 3
    assert metrics["source_activity_baseline"]["fetched_posts"] == 200
    assert metrics["source_activity_baseline"]["fetched_comments"] == 800
    assert updated is not None
    assert updated["pain_mentions_per_1000_posts"] == pytest.approx(15.0)
    assert json.loads(updated["source_activity_baseline_json"])["fetched_comments"] == 800


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


async def test_list_export_rows_adds_cluster_coverage_and_feedback_research_fields(db):
    await db.insert_pain_point(
        subreddit="ops",
        post_id="reddit:research-export",
        url="https://reddit.com/r/ops/comments/research-export",
        title="Manual reconciliation blocks fulfillment",
        body="We reconcile inventory in spreadsheets every Friday.",
        category="complaint",
        summary="Manual reconciliation blocks fulfillment.",
        severity="high",
        willingness_to_pay=9,
        pain_level=8,
        is_monetizable=True,
        evidence_quality="exact_quote",
        verified_evidence=[{"quote": "reconcile inventory in spreadsheets", "match_type": "exact"}],
        confidence=0.88,
        opportunity_score=72.5,
        score_components={"weights": {"evidence": 0.24}, "raw_score": 72.5},
        pain_mentions_per_1000_posts=12.5,
        pain_mentions_per_1000_comments=4.5,
        unique_authors_count=7,
        unique_threads_count=4,
        weekly_delta=2,
        source_activity_baseline={"posts_scanned": 400},
    )
    run_id = await db.create_macro_trend_run(window_days=30, candidate_count=1, cluster_count=1)
    await db.save_macro_cluster(
        run_id=run_id,
        canonical_key="inventory-sync-reconciliation",
        cluster_key="inventory-sync-reconciliation:v1",
        label="Inventory sync reconciliation",
        summary="Ops teams reconcile inventory manually.",
        estimated_monetization_signal="high",
        item_count=1,
        aggregate_wtp=9.0,
        avg_opportunity_score=72.5,
        cluster_stability_score=0.91,
        verified_quote_count=5,
        independent_source_count=2,
        members=[("reddit:research-export", 0.87)],
    )
    await db.record_feedback(post_id="reddit:research-export", feedback_value="useful", source="telegram")
    await db.record_feedback(post_id="reddit:research-export", feedback_value="bad_evidence", source="telegram")

    rows = await db.list_export_rows(subreddit="ops", min_wtp=8, include_favorites=True)

    row = next(item for item in rows if item["post_id"] == "reddit:research-export")
    assert row["canonical_cluster_key"] == "inventory-sync-reconciliation"
    assert row["cluster_key"] == "inventory-sync-reconciliation:v1"
    assert row["cluster_label"] == "Inventory sync reconciliation"
    assert row["cluster_stability_score"] == 0.91
    assert row["cluster_verified_quote_count"] == 5
    assert row["cluster_independent_source_count"] == 2
    assert row["cluster_similarity"] == 0.87
    assert row["pain_mentions_per_1000_posts"] == 12.5
    assert row["pain_mentions_per_1000_comments"] == 4.5
    assert row["unique_authors_count"] == 7
    assert row["unique_threads_count"] == 4
    assert row["weekly_delta"] == 2
    assert json.loads(row["source_activity_baseline_json"]) == {"posts_scanned": 400}
    assert row["feedback_status"] == "needs_review"
    assert row["feedback_total"] == 2
    assert json.loads(row["feedback_counts_json"]) == {"bad_evidence": 1, "useful": 1}
    assert row["latest_feedback_value"] == "bad_evidence"
    assert row["latest_feedback_at"]


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


async def test_list_competitor_failure_candidates_requires_promotion_eligible_exact_evidence(db):
    await db.insert_pain_point(
        subreddit="salesops",
        post_id="reddit:radar-good",
        url="https://reddit.com/r/salesops/comments/radar-good",
        title="HubSpot renewal pricing and lock-in hurt RevOps",
        body="HubSpot renewal doubled and we cannot export workflows without rebuilding them.",
        category="complaint",
        summary="HubSpot pricing and workflow lock-in are pushing RevOps toward alternatives.",
        severity="high",
        willingness_to_pay=9,
        pain_level=9,
        opportunity_score=91.0,
        competitor_tags=["HubSpot"],
        current_workaround="exporting CSVs to Airtable",
        incumbent_failure="HubSpot pricing doubled and contract lock-in blocks switching",
        verified_evidence=[{"quote": "HubSpot renewal doubled and we cannot export workflows", "match_type": "exact"}],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        first_handness="first_hand",
        buyer_authority="head_of_ops",
        buyer_authority_score=0.94,
        confidence=0.9,
    )
    await db.insert_pain_point(
        subreddit="salesops",
        post_id="reddit:radar-weak",
        url="https://reddit.com/r/salesops/comments/radar-weak",
        title="High score but no quote for HubSpot",
        body="unsupported",
        category="complaint",
        summary="Looks important, but no verified quote backs it.",
        severity="high",
        willingness_to_pay=10,
        pain_level=10,
        opportunity_score=99.0,
        competitor_tags=["HubSpot"],
        incumbent_failure="HubSpot support is bad",
        verified_evidence=[],
        evidence_quality="no_quote",
        evidence_match_rate=0.0,
        first_handness="first_hand",
        buyer_authority="founder_owner",
        buyer_authority_score=1.0,
        score_components={"promotion_eligible": True},
    )
    await db.insert_pain_point(
        subreddit="salesops",
        post_id="reddit:radar-low-authority",
        url="https://reddit.com/r/salesops/comments/radar-low-authority",
        title="Exact quote but no buyer signal",
        body="Salesforce support fails every renewal.",
        category="complaint",
        summary="Unsupported by first-hand or buyer authority.",
        severity="medium",
        willingness_to_pay=9,
        pain_level=8,
        opportunity_score=85.0,
        competitor_tags=["Salesforce"],
        incumbent_failure="Salesforce support fails every renewal",
        verified_evidence=[{"quote": "Salesforce support fails every renewal", "match_type": "exact"}],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        first_handness="unknown",
        buyer_authority="unknown",
        buyer_authority_score=0.2,
    )
    await db.insert_pain_point(
        subreddit="salesops",
        post_id="reddit:radar-rejected",
        url="https://reddit.com/r/salesops/comments/radar-rejected",
        title="Exact quote but rejected as solved",
        body="HubSpot support failed but the team already switched.",
        category="complaint",
        summary="Rejected rows must not enter the primary competitor radar.",
        severity="high",
        willingness_to_pay=10,
        pain_level=10,
        opportunity_score=97.0,
        competitor_tags=["HubSpot"],
        incumbent_failure="HubSpot support failed before switching",
        verified_evidence=[{"quote": "HubSpot support failed but the team already switched", "match_type": "exact"}],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        first_handness="first_hand",
        buyer_authority="founder_owner",
        buyer_authority_score=1.0,
        score_components={"promotion_eligible": False, "evidence_rejection_reason": "solved_issue"},
    )

    candidates = await db.list_competitor_failure_candidates(hours=24, limit=10)

    assert [row["post_id"] for row in candidates] == ["reddit:radar-good"]
    assert candidates[0]["competitor_tags"] == '["hubspot"]'
    assert "HubSpot renewal doubled" in candidates[0]["verified_evidence_json"]


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
        canonical_key="api-timeout-failures",
        cluster_key="reddit:m1",
        label="API trend",
        summary="Recurring API failures",
        estimated_monetization_signal="high",
        item_count=2,
        aggregate_wtp=17.0,
        fresh_post_count=1,
        evergreen_post_count=1,
        median_buyer_authority=0.8,
        incumbents=["quickbooks", "jira"],
        avg_opportunity_score=84.5,
        cluster_stability_score=0.84,
        representative_examples=[
            {
                "post_id": "reddit:m1",
                "title": "API timeout",
                "verified_quotes": ["Timeouts break reconciliation"],
            }
        ],
        verified_quote_count=2,
        independent_source_count=1,
        unique_author_count=2,
        normalized_frequency={"pain_mentions_per_1000_posts": 4.0, "unique_authors_count": 2},
        latest_source_created_ts=1713772800,
        members=[("reddit:m1", 0.9), ("reddit:m2", 0.88)],
    )
    assert cluster_id > 0

    latest_run = await db.get_latest_macro_trend_run()
    assert latest_run is not None
    assert latest_run["id"] == run_id

    clusters = await db.get_macro_clusters(run_id)
    assert len(clusters) == 1
    assert set(clusters[0]["post_ids"]) == {"reddit:m1", "reddit:m2"}
    assert clusters[0]["canonical_key"] == "api-timeout-failures"
    assert clusters[0]["fresh_post_count"] == 1
    assert clusters[0]["evergreen_post_count"] == 1
    assert clusters[0]["incumbents"] == ["quickbooks", "jira"]
    assert clusters[0]["cluster_stability_score"] == 0.84
    assert clusters[0]["verified_quote_count"] == 2
    assert clusters[0]["independent_source_count"] == 1
    assert clusters[0]["unique_author_count"] == 2
    assert clusters[0]["representative_examples"] == [
        {"post_id": "reddit:m1", "title": "API timeout", "verified_quotes": ["Timeouts break reconciliation"]}
    ]
    assert clusters[0]["normalized_frequency"] == {"pain_mentions_per_1000_posts": 4.0, "unique_authors_count": 2}

    by_post = await db.get_latest_macro_cluster_for_post("reddit:m1")
    assert by_post is not None
    assert by_post["label"] == "API trend"
    assert by_post["canonical_key"] == "api-timeout-failures"

    latest_canonical = await db.get_latest_canonical_clusters(limit=5)
    assert len(latest_canonical) == 1
    assert latest_canonical[0]["canonical_key"] == "api-timeout-failures"
    assert latest_canonical[0]["avg_opportunity_score"] == 84.5
    assert latest_canonical[0]["cluster_stability_score"] == 0.84
    assert latest_canonical[0]["representative_examples"][0]["post_id"] == "reddit:m1"
    assert latest_canonical[0]["normalized_frequency"]["unique_authors_count"] == 2

    candidates = await db.get_macro_candidates(window_days=30, min_wtp=8)
    ids = {row["post_id"] for row in candidates}
    assert {"reddit:m1", "reddit:m2"}.issubset(ids)


async def test_get_latest_canonical_clusters_filters_before_limit(db):
    run_id = await db.create_macro_trend_run(window_days=30, candidate_count=4, cluster_count=2)
    await db.save_macro_cluster(
        run_id=run_id,
        canonical_key="high-score-unrelated",
        cluster_key="reddit:z1",
        label="Unrelated cluster",
        summary="Not relevant to the requested digest slice.",
        estimated_monetization_signal="high",
        item_count=2,
        aggregate_wtp=18.0,
        fresh_post_count=2,
        evergreen_post_count=0,
        median_buyer_authority=0.9,
        incumbents=["salesforce"],
        avg_opportunity_score=99.0,
        latest_source_created_ts=1713772800,
        members=[("reddit:z1", 0.93), ("reddit:z2", 0.91)],
    )
    await db.save_macro_cluster(
        run_id=run_id,
        canonical_key="target-cluster",
        cluster_key="reddit:t1",
        label="Target cluster",
        summary="Relevant cluster that should survive post-id filtering.",
        estimated_monetization_signal="medium",
        item_count=2,
        aggregate_wtp=14.0,
        fresh_post_count=1,
        evergreen_post_count=1,
        median_buyer_authority=0.7,
        incumbents=["quickbooks"],
        avg_opportunity_score=61.0,
        latest_source_created_ts=1713770000,
        members=[("reddit:t1", 0.89), ("reddit:t2", 0.88)],
    )

    filtered = await db.get_latest_canonical_clusters(limit=1, post_ids=["reddit:t1"])

    assert len(filtered) == 1
    assert filtered[0]["canonical_key"] == "target-cluster"


async def test_get_latest_canonical_clusters_deduplicates_duplicate_keys(db):
    run_id = await db.create_macro_trend_run(window_days=30, candidate_count=3, cluster_count=2)
    await db.save_macro_cluster(
        run_id=run_id,
        canonical_key="duplicate-key",
        cluster_key="reddit:d1",
        label="Primary cluster",
        summary="Higher scoring duplicate key entry.",
        estimated_monetization_signal="high",
        item_count=2,
        aggregate_wtp=15.0,
        fresh_post_count=2,
        evergreen_post_count=0,
        median_buyer_authority=0.8,
        incumbents=["hubspot"],
        avg_opportunity_score=88.0,
        latest_source_created_ts=1713772800,
        members=[("reddit:d1", 0.9), ("reddit:d2", 0.87)],
    )
    await db.save_macro_cluster(
        run_id=run_id,
        canonical_key="duplicate-key",
        cluster_key="reddit:d3",
        label="Secondary duplicate",
        summary="Lower scoring duplicate key entry.",
        estimated_monetization_signal="medium",
        item_count=1,
        aggregate_wtp=7.0,
        fresh_post_count=1,
        evergreen_post_count=0,
        median_buyer_authority=0.5,
        incumbents=["hubspot"],
        avg_opportunity_score=44.0,
        latest_source_created_ts=1713770000,
        members=[("reddit:d3", 0.84)],
    )

    clusters = await db.get_latest_canonical_clusters(limit=5)

    assert len(clusters) == 1
    assert clusters[0]["label"] == "Primary cluster"


async def test_get_latest_canonical_clusters_can_return_older_matching_run(db):
    older_run = await db.create_macro_trend_run(window_days=30, candidate_count=1, cluster_count=1)
    await db.save_macro_cluster(
        run_id=older_run,
        canonical_key="older-target",
        cluster_key="reddit:o1",
        label="Older target cluster",
        summary="Relevant cluster from an earlier run.",
        estimated_monetization_signal="high",
        item_count=1,
        aggregate_wtp=9.0,
        fresh_post_count=1,
        evergreen_post_count=0,
        median_buyer_authority=0.7,
        incumbents=["quickbooks"],
        avg_opportunity_score=72.0,
        latest_source_created_ts=1713772800,
        members=[("reddit:o1", 0.9)],
    )
    newer_run = await db.create_macro_trend_run(window_days=30, candidate_count=1, cluster_count=1)
    await db.save_macro_cluster(
        run_id=newer_run,
        canonical_key="newer-unrelated",
        cluster_key="reddit:n1",
        label="Newer unrelated cluster",
        summary="Different run without matching membership.",
        estimated_monetization_signal="medium",
        item_count=1,
        aggregate_wtp=7.0,
        fresh_post_count=1,
        evergreen_post_count=0,
        median_buyer_authority=0.5,
        incumbents=["asana"],
        avg_opportunity_score=65.0,
        latest_source_created_ts=1713772900,
        members=[("reddit:n1", 0.85)],
    )

    clusters = await db.get_latest_canonical_clusters(limit=5, post_ids=["reddit:o1"])

    assert len(clusters) == 1
    assert clusters[0]["canonical_key"] == "older-target"


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


async def test_feedback_storage_summary_and_label_review_queue(db):
    await db.insert_pain_point(
        subreddit="ops",
        post_id="reddit:feedback1",
        url="https://reddit.com/r/ops/comments/feedback1",
        title="Manual invoice review takes too long",
        body="We still review invoices by hand every week.",
        category="complaint",
        summary="Manual invoice review is slow.",
        severity="high",
        willingness_to_pay=9,
        pain_level=8,
        evidence_quality="exact_quote",
        verified_evidence=[{"quote": "review invoices by hand", "match_type": "exact"}],
    )

    useful_id = await db.record_feedback(
        post_id="reddit:feedback1",
        feedback_value="useful",
        source="telegram",
        metadata={"message_id": "42"},
    )
    bad_evidence_id = await db.record_feedback(
        post_id="reddit:feedback1",
        feedback_value="bad_evidence",
        source="telegram",
    )

    assert useful_id > 0
    assert bad_evidence_id > useful_id
    with pytest.raises(ValueError, match="Unsupported feedback"):
        await db.record_feedback(post_id="reddit:feedback1", feedback_value="interesting", source="telegram")

    feedback_rows = await db.list_feedback(post_id="reddit:feedback1")
    assert [row["feedback_value"] for row in feedback_rows] == ["useful", "bad_evidence"]
    assert json.loads(feedback_rows[0]["metadata_json"]) == {"message_id": "42"}

    summary = await db.get_feedback_summary()
    assert summary["useful"] == 1
    assert summary["bad_evidence"] == 1
    assert summary["not_a_pain"] == 0

    monitoring_summary = await db.get_monitoring_summary()
    assert monitoring_summary["feedback_total"] == 2
    assert monitoring_summary["feedback"]["useful"] == 1
    assert monitoring_summary["feedback"]["bad_evidence"] == 1

    created_count = await db.enqueue_feedback_label_reviews()
    assert created_count == 2
    assert await db.enqueue_feedback_label_reviews() == 0

    review_rows = await db.list_label_review_queue(limit=10)
    assert [row["feedback_event_id"] for row in review_rows] == [useful_id, bad_evidence_id]
    useful_payload = review_rows[0]["review_payload"]
    bad_evidence_payload = review_rows[1]["review_payload"]
    assert useful_payload["review_type"] == "feedback_label_review"
    assert useful_payload["review_status"] == "pending"
    assert useful_payload["post_id"] == "reddit:feedback1"
    assert useful_payload["feedback_value"] == "useful"
    assert useful_payload["label_suggestions"] == {"feedback_useful": True}
    assert useful_payload["requires_human_review"] is True
    assert useful_payload["promotion_eligible"] is False
    assert useful_payload["source"]["evidence_quality"] == "exact_quote"
    assert "is_monetizable" not in useful_payload
    assert bad_evidence_payload["label_suggestions"] == {
        "feedback_useful": False,
        "evidence_relevance": "irrelevant",
    }


async def test_useful_feedback_does_not_promote_weak_or_rejected_rows_to_macro_candidates(db):
    await db.insert_pain_point(
        subreddit="ops",
        post_id="reddit:weak-feedback",
        url="",
        title="Weak no-quote row",
        body="",
        category="complaint",
        summary="weak",
        severity="low",
        willingness_to_pay=0,
        pain_level=0,
        evidence_quality="no_quote",
    )
    await db.insert_pain_point(
        subreddit="ops",
        post_id="reddit:discarded-feedback",
        url="",
        title="Discarded row",
        body="",
        category="complaint",
        summary="discarded",
        severity="high",
        willingness_to_pay=10,
        pain_level=10,
        evidence_quality="exact_quote",
        triage_status="discarded",
    )

    await db.record_feedback(post_id="reddit:weak-feedback", feedback_value="useful", source="telegram")
    await db.record_feedback(post_id="reddit:discarded-feedback", feedback_value="useful", source="telegram")

    candidates = await db.get_macro_candidates(window_days=30, min_wtp=8)
    candidate_ids = {row["post_id"] for row in candidates}

    assert "reddit:weak-feedback" not in candidate_ids
    assert "reddit:discarded-feedback" not in candidate_ids


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
