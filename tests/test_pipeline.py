import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from classifier import PainSignal
from db import Database
from evidence import VerifiedEvidence
from openrouter import DeepDiveResult
from pipeline import AnalysisPipeline, WEAK_SIGNAL_SCORE_CAP
from scraper import Post, RedditComment


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test_pipeline.db"))
    await database.init()
    yield database
    await database.close()


def _wave5_signal(
    post_id: str,
    *,
    intensity_score: float = 0.72,
    frequency_signal: str = "thread_consensus",
    urgency: str = "active_blocker",
    current_workaround: str = "manual",
    wtp_score: float = 0.64,
    incumbent_failure: str = "weak",
    verified: bool = True,
    needs_human_review: bool = False,
) -> PainSignal:
    quote = "manual reconciliation blocks payroll"
    post = Post(
        post_id=post_id,
        subreddit="financeops",
        title="Manual reconciliation blocks payroll",
        body=f"As ops lead, {quote} every Friday and our ERP export keeps failing.",
        url=f"https://example.com/{post_id}",
        score=14,
        top_comments=["Same here, we use spreadsheets too."],
        source_created_ts=1776688800,
        source_created_at="2026-04-20T10:00:00+00:00",
    )
    verified_evidence = [
        VerifiedEvidence(
            quote=quote,
            source_type="body",
            post_id=post_id,
            comment_id=None,
            permalink=f"https://example.com/{post_id}",
            match_type="exact",
            match_confidence=1.0,
            created_utc=1776688800,
        )
    ] if verified else []
    return PainSignal(
        post=post,
        category="complaint",
        summary="Manual reconciliation blocks payroll.",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=round(wtp_score * 10),
        niche_category="Finance Ops",
        competitor_tags=["netsuite"],
        analysis_mode="b2b",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="head_of_ops",
        pain_type="workflow_friction",
        expression_type="complaint",
        user_context="Ops lead at a mid-market finance team",
        user_context_json={"role": "ops_lead", "company_size": "mid_market", "process": "payroll reconciliation"},
        intensity_score=intensity_score,
        frequency_signal=frequency_signal,
        urgency=urgency,
        current_workaround=current_workaround,
        wtp_score=wtp_score,
        incumbent_failure=incumbent_failure,
        opportunity_type="automation",
        evidence_spans=[quote],
        verified_evidence=verified_evidence,
        evidence_quality="exact_quote" if verified else "no_quote",
        evidence_match_rate=1.0 if verified else 0.0,
        confidence=0.88,
        needs_human_review=needs_human_review,
        opportunity_bucket="current_opportunity",
    )


async def test_analyze_subreddit_persists_report_and_rows(db, tmp_path):
    post = Post(
        post_id="p1",
        subreddit="python",
        title="I can't make this work",
        body="Still broken",
        url="https://reddit.com/p1",
        score=10,
        top_comments=[
            "Same here — we still do this every week.",
            "Manual workaround: export CSV and patch rows in Sheets.",
        ],
        source_created_at="2026-04-20T10:00:00+00:00",
        source_created_ts=1776688800,
        author_name="ops_owner",
    )
    signal = PainSignal(
        post=post,
        category="complaint",
        summary="User reports failure",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="DevTools",
        analysis_mode="b2b",
        analysis_payload={"sample": True},
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        evidence_spans=["still broken", "can't make this work"],
        verified_evidence=[
            VerifiedEvidence(
                quote="still broken",
                source_type="body",
                post_id="p1",
                comment_id=None,
                permalink="https://reddit.com/p1",
                match_type="exact",
                match_confidence=1.0,
                created_utc=1776688800,
            )
        ],
        evidence_quality="exact_quote",
        evidence_match_rate=0.5,
        confidence=0.73,
        uncertainty_reason="one evidence span was unmatched",
        needs_human_review=False,
        opportunity_bucket="current_opportunity",
    )

    scraper = AsyncMock()
    scraper.fetch_posts.return_value = [post]
    scraper.fetch_full_thread.return_value = ["comment"]

    openrouter = AsyncMock()
    openrouter.analyze_deep_dive.return_value = DeepDiveResult(
        workarounds=["manual reset"],
        competitors=["Tool A"],
        feature_wishlist=["auto retry"],
        buying_signals=["paying now"],
        icp_hypothesis="SMBs",
        actionable_summary="Build auto retry",
    )

    classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[signal]),
        openrouter=openrouter,
    )

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=8,
    )

    run = await pipeline.analyze_subreddit("python", limit=25)

    assert run.subreddit == "python"
    assert run.post_count == 1
    assert run.pain_count == 1
    assert run.monetizable_count == 1
    assert run.deep_dive_count == 1
    assert run.report_id > 0
    assert run.analysis_run_id > 0
    assert (tmp_path / "reports").exists()

    with open(run.json_path, "r", encoding="utf-8") as handle:
        report_payload = json.load(handle)
    assert report_payload[0]["post_id"] == "p1"
    assert report_payload[0]["source_created_ts"] == 1776688800
    assert report_payload[0]["post_type"] == "first_person_pain"
    assert report_payload[0]["buyer_authority"] == "founder_owner"
    assert report_payload[0]["opportunity_bucket"] == "current_opportunity"
    assert report_payload[0]["comment_same_here_count"] == 1
    assert report_payload[0]["comment_workaround_count"] == 1
    assert report_payload[0]["comment_tool_mentions"] == []
    assert report_payload[0]["opportunity_score"] > 0
    assert report_payload[0]["score_components"]["consensus_score"] > 0
    assert report_payload[0]["evidence_quality"] == "exact_quote"
    assert report_payload[0]["evidence_match_rate"] == 0.5
    assert report_payload[0]["confidence"] == 0.73
    assert report_payload[0]["needs_human_review"] is False
    assert report_payload[0]["verified_evidence"][0]["quote"] == "still broken"

    latest = await db.get_latest_report(subreddit="python")
    assert latest is not None
    assert latest["json_path"] == run.json_path

    rows = await db.get_pain_points("python")
    assert len(rows) == 1
    assert rows[0]["post_id"] == "p1"
    assert rows[0]["deep_dive_status"] == "completed"
    assert rows[0]["comment_same_here_count"] == 1
    assert rows[0]["comment_workaround_count"] == 1
    assert rows[0]["opportunity_score"] > 0
    assert rows[0]["evidence_quality"] == "exact_quote"
    assert rows[0]["evidence_match_rate"] == 0.5
    assert rows[0]["confidence"] == 0.73
    assert rows[0]["needs_human_review"] == 0
    assert json.loads(rows[0]["verified_evidence_json"])[0]["quote"] == "still broken"


async def test_pipeline_persists_wave5_taxonomy_fields_to_db_and_report(db, tmp_path):
    signal = _wave5_signal(
        "wave5-pipeline",
        intensity_score=0.82,
        frequency_signal="thread_consensus",
        urgency="active_blocker",
        current_workaround="spreadsheet",
        wtp_score=0.91,
        incumbent_failure="explicit_competitor_failure",
    )
    classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[signal]),
        openrouter=None,
    )
    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=99,
    )

    run = await pipeline.analyze_external_posts(posts=[signal.post], source="reddit", run_scope="financeops")

    row = await db.get_pain_point("wave5-pipeline")
    assert row is not None
    assert row["pain_type"] == "workflow_friction"
    assert row["expression_type"] == "complaint"
    assert json.loads(row["user_context_json"])["role"] == "ops_lead"
    assert row["intensity_score"] == 0.82
    assert row["frequency_signal"] == "thread_consensus"
    assert row["urgency"] == "active_blocker"
    assert row["current_workaround"] == "spreadsheet"
    assert row["wtp_score"] == 0.91
    assert row["incumbent_failure"] == "explicit_competitor_failure"
    assert row["opportunity_type"] == "automation"

    with open(run.json_path, "r", encoding="utf-8") as handle:
        report_payload = json.load(handle)
    report_row = report_payload[0]
    assert report_row["pain_type"] == "workflow_friction"
    assert report_row["expression_type"] == "complaint"
    assert report_row["user_context_json"]["process"] == "payroll reconciliation"
    assert report_row["intensity_score"] == 0.82
    assert report_row["frequency_signal"] == "thread_consensus"
    assert report_row["urgency"] == "active_blocker"
    assert report_row["current_workaround"] == "spreadsheet"
    assert report_row["wtp_score"] == 0.91
    assert report_row["incumbent_failure"] == "explicit_competitor_failure"
    assert report_row["opportunity_type"] == "automation"
    assert "weights" in report_row["score_components"]


async def test_analyze_external_posts_persists_structured_comments_flags_and_coverage(db, tmp_path):
    comment = RedditComment(
        comment_id="reddit:t1_pipeline_c1",
        post_id="reddit:pipeline-post",
        parent_id="reddit:pipeline-post",
        body="[deleted]",
        body_hash="deleted-body-hash",
        author_hash="comment-author-hash",
        score=0,
        created_utc=1713600100,
        depth=0,
        is_op=False,
        is_deleted=True,
        permalink="/r/python/comments/pipeline-post/title/pipeline_c1/",
        fetched_at="2026-04-26T12:00:00+00:00",
        body_available=False,
        deleted_detected_at="2026-04-26T12:00:00+00:00",
    )
    post = Post(
        post_id="reddit:pipeline-post",
        subreddit="python",
        title="Removed workflow pain",
        body="[removed]",
        url="https://reddit.com/r/python/comments/pipeline-post/title/",
        score=10,
        comments=[comment],
        top_comments=[],
        source_created_ts=1713600000,
        is_removed=True,
        body_available=False,
        deleted_detected_at="2026-04-26T12:00:00+00:00",
        author_hash="post-author-hash",
    )
    signal = PainSignal(
        post=post,
        category="complaint",
        summary="Deleted post still produced a durable signal",
        severity="medium",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=8,
        niche_category="DevTools",
        analysis_mode="b2b",
    )
    scraper = AsyncMock()
    scraper.last_source_method_used = "public_json"
    scraper.last_failed_requests = 0
    classifier = SimpleNamespace(classify_batch=AsyncMock(return_value=[signal]), openrouter=None)
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=99,
    )

    run = await pipeline.analyze_external_posts(posts=[post], source="reddit", run_scope="python")

    row = await db.get_pain_point("reddit:pipeline-post")
    stored_comments = await db.get_comments_for_post("reddit:pipeline-post")
    coverage_runs = await db.list_source_coverage_runs(source="reddit", scope="python", limit=1)
    cursor_row = await db.get_source_ingestion_cursor(source="reddit", subreddit="python", timeframe="day")
    with open(run.json_path, "r", encoding="utf-8") as handle:
        report_payload = json.load(handle)

    assert row is not None
    assert row["is_removed"] == 1
    assert row["body_available"] == 0
    assert row["deleted_detected_at"] == "2026-04-26T12:00:00+00:00"
    assert row["author_hash"] == "post-author-hash"
    assert len(stored_comments) == 1
    assert stored_comments[0]["comment_id"] == "reddit:t1_pipeline_c1"
    assert stored_comments[0]["is_deleted"] == 1
    assert stored_comments[0]["is_removed"] == 0
    assert stored_comments[0]["body_available"] == 0
    assert stored_comments[0]["deleted_detected_at"] == "2026-04-26T12:00:00+00:00"
    assert len(coverage_runs) == 1
    assert coverage_runs[0]["fetched_posts"] == 1
    assert coverage_runs[0]["fetched_comments"] == 1
    assert coverage_runs[0]["skipped_deleted"] == 1
    assert coverage_runs[0]["skipped_duplicates"] == 0
    assert coverage_runs[0]["source_method_used"] == "public_json"
    assert cursor_row is not None
    assert cursor_row["last_seen_created_utc"] == 1713600000
    assert json.loads(cursor_row["fetch_errors_json"]) == []
    assert row["pain_mentions_per_1000_posts"] == pytest.approx(1000.0)
    assert row["pain_mentions_per_1000_comments"] == pytest.approx(1000.0)
    assert run.source_coverage["fetched_comments"] == 1
    assert run.normalized_frequency["unique_threads_count"] == 1
    assert report_payload[0]["source_coverage"]["fetched_posts"] == 1
    assert report_payload[0]["source_coverage"]["source_method_used"] == "public_json"
    assert report_payload[0]["normalized_frequency"]["pain_mentions_per_1000_posts"] == pytest.approx(1000.0)
    assert report_payload[0]["pain_mentions_per_1000_comments"] == pytest.approx(1000.0)


async def test_external_source_coverage_does_not_reuse_reddit_fetch_state(db, tmp_path):
    post = Post(
        post_id="hn:1",
        subreddit="frontpage",
        title="HN workflow pain",
        body="manual exports are still painful",
        url="https://news.ycombinator.com/item?id=1",
        score=3,
        source="hackernews",
        source_created_ts=1713600300,
    )
    scraper = AsyncMock()
    scraper.last_source_method_used = "public_json"
    scraper.last_failed_requests = 7
    classifier = SimpleNamespace(classify_batch=AsyncMock(return_value=[]), openrouter=None)
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    run = await pipeline.analyze_external_posts(posts=[post], source="hackernews", run_scope="frontpage")

    coverage_runs = await db.list_source_coverage_runs(source="hackernews", scope="frontpage", limit=1)
    cursor_row = await db.get_source_ingestion_cursor(source="hackernews", subreddit="frontpage", timeframe=None)

    assert run.source_coverage["source_method_used"] == "external"
    assert run.source_coverage["failed_requests"] == 0
    assert coverage_runs[0]["source_method_used"] == "external"
    assert coverage_runs[0]["failed_requests"] == 0
    assert cursor_row is not None
    assert cursor_row["last_seen_created_utc"] == 1713600300


async def test_analyze_subreddit_skips_already_persisted_posts_before_classification(db, tmp_path):
    existing_post = Post(
        post_id="existing1",
        subreddit="python",
        title="Already processed",
        body="still broken",
        url="https://reddit.com/existing1",
        score=7,
    )
    fresh_post = Post(
        post_id="fresh1",
        subreddit="python",
        title="Need better deploy rollback",
        body="current process is manual",
        url="https://reddit.com/fresh1",
        score=12,
    )

    await db.insert_pain_point(
        subreddit="python",
        post_id="existing1",
        url="https://reddit.com/existing1",
        title="Already processed",
        body="still broken",
        category="complaint",
        summary="existing",
        severity="medium",
    )

    signal = PainSignal(
        post=fresh_post,
        category="complaint",
        summary="Rollback process is painful",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="DevOps",
        analysis_mode="b2b",
    )

    scraper = AsyncMock()
    scraper.fetch_posts.return_value = [existing_post, fresh_post]
    classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[signal]),
        openrouter=AsyncMock(),
    )

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    run = await pipeline.analyze_subreddit("python", limit=10)

    classify_arg = classifier.classify_batch.await_args.args[0]
    assert [post.post_id for post in classify_arg] == ["fresh1"]
    assert run.post_count == 2
    assert run.pain_count == 1

    latest_run = await db.get_latest_analysis_run("python")
    assert latest_run is not None
    assert latest_run["skipped_existing_count"] == 1
    assert latest_run["dedup_merged_count"] == 0
    assert latest_run["screen_rule_dropped_count"] == 0
    assert latest_run["screen_kept_count"] == 1
    assert latest_run["screen_capped_count"] == 0


async def test_analyze_subreddit_applies_llm_classification_cap_per_run(db, tmp_path):
    posts = [
        Post(
            post_id=f"fresh{i}",
            subreddit="python",
            title=f"pain {i}",
            body="manual process",
            url=f"https://reddit.com/fresh{i}",
            score=10 - i,
        )
        for i in range(3)
    ]

    capped_signal = PainSignal(
        post=posts[0],
        category="complaint",
        summary="Manual process hurts",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="DevOps",
        analysis_mode="b2b",
    )

    scraper = AsyncMock()
    scraper.fetch_posts.return_value = posts
    classifier = SimpleNamespace(
        prescreen_posts=MagicMock(return_value=(posts[:1], {"screen_rule_dropped_count": 0, "screen_kept_count": 3, "screen_capped_count": 2})),
        classify_batch=AsyncMock(return_value=[capped_signal]),
        openrouter=AsyncMock(),
    )

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
        llm_max_classifications_per_run=1,
        screen_max_llm_candidates_per_run=5,
    )

    run = await pipeline.analyze_subreddit("python", limit=10)

    classifier.prescreen_posts.assert_called_once()
    classify_arg = classifier.classify_batch.await_args.args[0]
    assert [post.post_id for post in classify_arg] == ["fresh0"]
    assert run.post_count == 3
    assert run.pain_count == 1

    latest_run = await db.get_latest_analysis_run("python")
    assert latest_run is not None
    assert latest_run["screen_rule_dropped_count"] == 0
    assert latest_run["screen_kept_count"] == 3
    assert latest_run["screen_capped_count"] == 2


async def test_analyze_subreddit_cleans_tmp_file_on_atomic_write_error(db, tmp_path, monkeypatch):
    post = Post(
        post_id="p2",
        subreddit="python",
        title="Wish this existed",
        body="Need feature",
        url="https://reddit.com/p2",
        score=4,
    )
    signal = PainSignal(
        post=post,
        category="wish",
        summary="Feature request",
        severity="low",
        is_monetizable=False,
        pain_level=2,
        willingness_to_pay=1,
        niche_category="Uncategorized",
        analysis_mode="legacy",
    )

    scraper = AsyncMock()
    scraper.fetch_posts.return_value = [post]
    classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[signal]),
        openrouter=AsyncMock(),
    )

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    def fail_replace(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr("pipeline.os.replace", fail_replace)

    with pytest.raises(OSError):
        await pipeline.analyze_subreddit("python", limit=5)

    tmp_files = list((tmp_path / "reports").glob("*.tmp"))
    assert tmp_files == []


async def test_run_deep_dive_manual_success(db, tmp_path):
    await db.insert_pain_point(
        subreddit="python",
        post_id="manual1",
        url="https://reddit.com/manual1",
        title="Need better billing sync",
        body="body",
        category="complaint",
        summary="billing sync pain",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=9,
        niche_category="FinOps",
    )

    scraper = AsyncMock()
    scraper.fetch_full_thread.return_value = ["comment A", "comment B"]

    openrouter = AsyncMock()
    openrouter.analyze_deep_dive.return_value = DeepDiveResult(
        workarounds=["manual spreadsheets"],
        competitors=["Tool B"],
        feature_wishlist=["real-time sync"],
        buying_signals=["ready to pay"],
        icp_hypothesis="SMB agencies",
        actionable_summary="Build real-time sync",
    )

    classifier = SimpleNamespace(classify_batch=AsyncMock(return_value=[]), openrouter=openrouter)
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    outcome = await pipeline.run_deep_dive(
        post_id="manual1",
        subreddit="python",
        source="manual",
        title="Need better billing sync",
        body="Body",
    )

    assert outcome.status == "completed"
    row = await db.get_pain_point("manual1")
    assert row is not None
    assert row["deep_dive_status"] == "completed"
    assert "real-time sync" in (row["deep_dive_summary"] or "")


async def test_generate_digest_returns_ranked_rows(db, tmp_path):
    await db.insert_pain_point(
        subreddit="python",
        post_id="d1",
        url="",
        title="t1",
        body="",
        category="complaint",
        summary="s1",
        severity="high",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=7,
        niche_category="DevOps",
        deep_dive_summary="Need better alerts",
        opportunity_score=87.5,
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        verified_evidence=[
            VerifiedEvidence(
                quote="Need better alerts",
                source_type="body",
                post_id="d1",
                comment_id=None,
                permalink="",
                match_type="exact",
                match_confidence=1.0,
                created_utc=None,
            )
        ],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        score_components={"consensus_score": 0.9, "impact_score": 0.8, "promotion_eligible": True},
    )
    await db.insert_pain_point(
        subreddit="python",
        post_id="d2",
        url="",
        title="t2",
        body="",
        category="wish",
        summary="s2",
        severity="medium",
        is_monetizable=True,
        pain_level=9,
        willingness_to_pay=9,
        niche_category="DevOps",
        opportunity_score=61.0,
        score_components={
            "consensus_score": 0.2,
            "impact_score": 0.5,
            "promotion_eligible": False,
            "evidence_rejection_reason": "no_verified_exact_quote",
        },
    )
    await db.insert_pain_point(
        subreddit="python",
        post_id="d3",
        url="",
        title="t3",
        body="",
        category="wish",
        summary="s3",
        severity="high",
        is_monetizable=True,
        pain_level=10,
        willingness_to_pay=10,
        niche_category="DevOps",
        opportunity_score=99.0,
        score_components={"consensus_score": 1.0, "impact_score": 1.0, "promotion_eligible": True},
    )

    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    run_id = await db.create_macro_trend_run(window_days=30, candidate_count=3, cluster_count=1)
    await db.save_macro_cluster(
        run_id=run_id,
        canonical_key="alert-fatigue",
        cluster_key="d1",
        label="Alert fatigue",
        summary="Multiple teams complain about noisy alerting and weak escalation.",
        estimated_monetization_signal="high",
        item_count=2,
        aggregate_wtp=16.0,
        fresh_post_count=2,
        evergreen_post_count=0,
        median_buyer_authority=0.75,
        incumbents=["pagerduty"],
        avg_opportunity_score=74.25,
        latest_source_created_ts=1713772800,
        members=[("d1", 0.9), ("d2", 0.88)],
    )

    digest = await pipeline.generate_digest(subreddit="python", hours=24)
    assert digest["total"] == 3
    assert digest["top_items"][0]["post_id"] == "d1"
    assert digest["top_items"][0]["opportunity_score"] == 87.5
    assert [item["post_id"] for item in digest["needs_review_items"]] == ["d3", "d2"]
    assert digest["needs_review_items"][0]["evidence_rejection_reason"] == "no_verified_exact_quote"
    assert digest["needs_review_items"][1]["evidence_rejection_reason"] == "no_verified_exact_quote"
    assert digest["niche_counts"]["DevOps"] == 3
    assert digest["top_clusters"][0]["canonical_key"] == "alert-fatigue"
    assert "Need better alerts" in digest["recurring_blockers"]


async def test_generate_digest_adds_evidence_gated_research_actions_to_top_clusters(db, tmp_path):
    await db.insert_pain_point(
        subreddit="salesops",
        post_id="action-supported",
        url="https://example.com/action-supported",
        title="Approval CSV handoffs keep breaking onboarding",
        body="As RevOps owner, approval CSV handoffs break onboarding every week.",
        category="complaint",
        summary="Approval CSV handoffs break onboarding.",
        severity="high",
        is_monetizable=True,
        pain_level=9,
        willingness_to_pay=9,
        niche_category="RevOps",
        source="reddit",
        opportunity_score=91.0,
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="head_of_ops",
        current_workaround="manual CSV reconciliation before approval",
        incumbent_failure="CRM sync misses approval status changes",
        user_context_json={"persona": "RevOps manager", "workflow": "customer onboarding approvals"},
        verified_evidence=[
            VerifiedEvidence(
                quote="approval CSV handoffs break onboarding every week",
                source_type="body",
                post_id="action-supported",
                comment_id=None,
                permalink="https://example.com/action-supported",
                match_type="exact",
                match_confidence=1.0,
                created_utc=None,
            )
        ],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        score_components={"promotion_eligible": True},
    )
    await db.insert_pain_point(
        subreddit="salesops",
        post_id="action-weak",
        url="https://example.com/action-weak",
        title="Unsupported high-score workflow idea",
        body="Maybe teams need workflow automation.",
        category="wish",
        summary="No exact evidence backs this action.",
        severity="high",
        is_monetizable=True,
        pain_level=10,
        willingness_to_pay=10,
        niche_category="RevOps",
        source="reddit",
        opportunity_score=99.0,
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        current_workaround="unsupported weak workaround should not render",
        incumbent_failure="unsupported weak incumbent failure should not render",
        verified_evidence=[],
        evidence_quality="no_quote",
        evidence_match_rate=0.0,
        score_components={"promotion_eligible": True},
    )

    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )
    run_id = await db.create_macro_trend_run(window_days=30, candidate_count=2, cluster_count=1)
    await db.save_macro_cluster(
        run_id=run_id,
        canonical_key="revops-approval-csv-handoffs",
        cluster_key="action-supported",
        label="RevOps approval CSV handoffs",
        summary="RevOps teams lose onboarding time when approval CSV handoffs break.",
        estimated_monetization_signal="high",
        item_count=2,
        aggregate_wtp=19.0,
        fresh_post_count=2,
        evergreen_post_count=0,
        median_buyer_authority=0.9,
        incumbents=["hubspot"],
        avg_opportunity_score=95.0,
        representative_examples=[
            {
                "post_id": "action-supported",
                "title": "Approval CSV handoffs keep breaking onboarding",
                "verified_quotes": ["approval CSV handoffs break onboarding every week"],
                "current_workaround": "stale representative workaround should not render",
                "incumbent_failure": "stale representative incumbent failure should not render",
                "user_context": {"persona": "Stale persona", "workflow": "stale workflow"},
            },
            {
                "post_id": "action-weak",
                "title": "Unsupported high-score workflow idea",
                "verified_quotes": ["unsupported weak quote should not feed action"],
                "current_workaround": "unsupported weak workaround should not render",
            },
        ],
        research_action={
            "interview_questions": ["Ask only the unsupported weak row"],
            "icp_hypothesis": "Unsupported weak persona",
            "mvp_wedge": "Unsupported weak automation",
            "messaging_angle": "Unsupported weak messaging",
            "why_now": "Unsupported weak why now",
            "risks_unknowns": ["Unsupported weak risk"],
            "manual_validation_step": "Unsupported weak validation",
            "evidence_post_ids": ["action-weak"],
        },
        members=[("action-supported", 0.95), ("action-weak", 0.8)],
    )

    digest = await pipeline.generate_digest(subreddit="salesops", hours=24)

    action = digest["top_clusters"][0]["next_research_action"]
    assert action["evidence_post_ids"] == ["action-supported"]
    assert action["interview_questions"]
    action_text = json.dumps(action, ensure_ascii=False)
    cluster_text = json.dumps(digest["top_clusters"][0], ensure_ascii=False)
    assert "manual CSV reconciliation before approval" in action_text
    assert "Unsupported weak" not in action_text
    assert "Unsupported weak" not in cluster_text
    assert "stale representative" not in cluster_text
    assert "Stale persona" not in cluster_text


def test_attach_research_actions_sorts_digest_clusters_by_row_grounded_eligible_score():
    promoted_rows_by_id = {
        "low-eligible": {
            "post_id": "low-eligible",
            "title": "Verified low-score approval pain",
            "summary": "Exact evidence exists, but the current row score is modest.",
            "source": "reddit",
            "url": "https://reddit.com/low-eligible",
            "opportunity_score": 55.0,
            "confidence": 0.72,
            "pain_level": 6,
            "willingness_to_pay": 7,
            "buyer_authority": "manager",
            "current_workaround": "manual CSV approval check",
            "verified_evidence_json": '[{"quote":"approvals still require a manual CSV check","source_type":"body","match_type":"exact"}]',
        },
        "missing-representative": {
            "post_id": "missing-representative",
            "title": "Verified but not representative approval pain",
            "summary": "The canonical cluster lists this promoted row even when representative examples omit it.",
            "source": "hn",
            "url": "https://news.ycombinator.com/item?id=missing-representative",
            "opportunity_score": 65.0,
            "confidence": 0.73,
            "pain_level": 7,
            "willingness_to_pay": 7,
            "buyer_authority": "manager",
            "current_workaround": "manual approval queue audit",
            "verified_evidence_json": '[{"quote":"approval queue audits still happen manually","source_type":"body","match_type":"exact"}]',
        },
        "high-eligible": {
            "post_id": "high-eligible",
            "title": "Verified high-score invoice pain",
            "summary": "Exact evidence supports a stronger currently monetizable pain.",
            "source": "reddit",
            "url": "https://reddit.com/high-eligible",
            "opportunity_score": 92.0,
            "confidence": 0.91,
            "pain_level": 9,
            "willingness_to_pay": 9,
            "buyer_authority": "founder_owner",
            "current_workaround": "weekly invoice spreadsheet reconciliation",
            "verified_evidence_json": '[{"quote":"invoice reconciliation blocks payroll every week","source_type":"body","match_type":"exact"}]',
        },
    }
    clusters = [
        {
            "canonical_key": "weak-boosted-cluster",
            "label": "Weak boosted cluster",
            "avg_opportunity_score": 99.0,
            "post_ids": ["low-eligible", "missing-representative", "weak-only"],
            "representative_examples": [
                {
                    "post_id": "low-eligible",
                    "title": "Verified low-score approval pain",
                    "verified_quotes": ["approvals still require a manual CSV check"],
                    "opportunity_score": 99.0,
                    "confidence": 0.99,
                },
                {
                    "post_id": "weak-only",
                    "title": "Unsupported weak member",
                    "verified_quotes": [],
                },
            ],
        },
        {
            "canonical_key": "strong-eligible-cluster",
            "label": "Strong eligible cluster",
            "avg_opportunity_score": 70.0,
            "post_ids": ["high-eligible"],
            "representative_examples": [
                {
                    "post_id": "high-eligible",
                    "title": "Verified high-score invoice pain",
                    "verified_quotes": ["invoice reconciliation blocks payroll every week"],
                }
            ],
        },
    ]

    enriched = AnalysisPipeline._attach_research_actions_to_clusters(clusters, promoted_rows_by_id=promoted_rows_by_id)

    assert [cluster["label"] for cluster in enriched] == ["Strong eligible cluster", "Weak boosted cluster"]
    assert enriched[0]["eligible_examples"][0]["opportunity_score"] == 92.0
    assert enriched[1]["eligible_examples"][0]["opportunity_score"] == 55.0
    assert [example["post_id"] for example in enriched[1]["eligible_examples"]] == [
        "low-eligible",
        "missing-representative",
    ]
    assert enriched[1]["avg_opportunity_score"] == pytest.approx(60.0)
    assert enriched[1]["opportunity_score"] == pytest.approx(60.0)
    assert set(enriched[1]["next_research_action"]["evidence_post_ids"]) == {
        "low-eligible",
        "missing-representative",
    }
    assert "Unsupported weak member" not in json.dumps(enriched, ensure_ascii=False)


async def test_generate_digest_exposes_recent_source_coverage_and_frequency_metrics(db, tmp_path):
    await db.record_source_coverage_run(
        source="reddit",
        scope="python",
        fetched_posts=100,
        fetched_comments=500,
        skipped_deleted=2,
        skipped_duplicates=1,
        failed_requests=0,
        source_method_used="public_json",
        duration_ms=200,
    )
    await db.insert_pain_point(
        subreddit="python",
        post_id="digest-frequency",
        url="",
        title="Need better CSV automation",
        body="Manual CSV work keeps breaking",
        category="complaint",
        summary="CSV workflows are still manual",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="Ops",
        source="reddit",
        author_hash="digest-author",
        opportunity_score=75.0,
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        verified_evidence=[
            VerifiedEvidence(
                quote="Manual CSV work keeps breaking",
                source_type="body",
                post_id="digest-frequency",
                comment_id=None,
                permalink="",
                match_type="exact",
                match_confidence=1.0,
                created_utc=None,
            )
        ],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        score_components={"promotion_eligible": True},
    )

    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    digest = await pipeline.generate_digest(subreddit="python", hours=24)

    assert digest["source_coverage_runs"][0]["source_method_used"] == "public_json"
    assert digest["top_items"][0]["normalized_frequency"]["pain_mentions_per_1000_posts"] == pytest.approx(10.0)
    assert digest["top_items"][0]["normalized_frequency"]["pain_mentions_per_1000_comments"] == pytest.approx(2.0)
    assert digest["top_items"][0]["normalized_frequency"]["unique_authors_count"] == 1


async def test_evidence_first_promotion_demotes_unverified_high_wtp_signals(db, tmp_path):
    supported_post = Post(
        post_id="supported",
        subreddit="python",
        title="Manual invoice reconciliation breaks every week",
        body="As founder, I manually reconcile vendor invoices every week because the ERP sync fails.",
        url="https://reddit.com/supported",
        score=8,
        top_comments=["Same here — this manual workaround costs us hours."],
    )
    unsupported_post = Post(
        post_id="unsupported",
        subreddit="python",
        title="ERP automation is painful",
        body="I need better automation for operations.",
        url="https://reddit.com/unsupported",
        score=18,
        top_comments=[],
    )
    supported_signal = PainSignal(
        post=supported_post,
        category="complaint",
        summary="Invoice reconciliation breaks weekly",
        severity="high",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=7,
        niche_category="FinOps",
        analysis_mode="b2b",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        evidence_spans=["I manually reconcile vendor invoices every week"],
        verified_evidence=[
            VerifiedEvidence(
                quote="I manually reconcile vendor invoices every week",
                source_type="body",
                post_id="supported",
                comment_id=None,
                permalink="https://reddit.com/supported",
                match_type="exact",
                match_confidence=1.0,
                created_utc=None,
            )
        ],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        confidence=0.82,
    )
    unsupported_signal = PainSignal(
        post=unsupported_post,
        category="complaint",
        summary="Unsupported but attractive ERP claim",
        severity="high",
        is_monetizable=True,
        pain_level=10,
        willingness_to_pay=10,
        niche_category="FinOps",
        analysis_mode="b2b",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        evidence_spans=["invented quote not present in source"],
        verified_evidence=[],
        evidence_quality="no_quote",
        evidence_match_rate=0.0,
        confidence=0.96,
        needs_human_review=True,
    )

    scraper = AsyncMock()
    classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[unsupported_signal, supported_signal]),
        openrouter=None,
    )
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=99,
    )

    await pipeline.analyze_external_posts(posts=[unsupported_post, supported_post], source="reddit", run_scope="python")

    supported_row = await db.get_pain_point("supported")
    unsupported_row = await db.get_pain_point("unsupported")
    assert supported_row is not None
    assert unsupported_row is not None
    supported_components = json.loads(supported_row["score_components_json"])
    unsupported_components = json.loads(unsupported_row["score_components_json"])
    assert supported_components["promotion_eligible"] is True
    assert unsupported_components["promotion_eligible"] is False
    assert unsupported_components["evidence_rejection_reason"] == "no_verified_exact_quote"
    assert unsupported_row["opportunity_score"] < supported_row["opportunity_score"]

    digest = await pipeline.generate_digest(subreddit="python", hours=24)
    assert [item["post_id"] for item in digest["top_items"]] == ["supported"]
    assert [item["post_id"] for item in digest["needs_review_items"]] == ["unsupported"]


async def test_generate_digest_includes_bounded_rejected_noise_examples_with_reasons(db, tmp_path):
    async def insert_row(
        post_id: str,
        *,
        title: str,
        reason: str,
        triage_status: str = "new",
        category: str = "question",
        pain_type: str = "generic_question",
        niche_category: str = "Ops",
        confidence: float = 0.2,
        solved_penalty: float = 0.0,
        comment_shill_risk: float = 0.0,
        opportunity_score: float = 80.0,
    ) -> None:
        await db.insert_pain_point(
            subreddit="python",
            post_id=post_id,
            url=f"https://example.com/{post_id}",
            title=title,
            body="Rejected candidate fixture body.",
            category=category,
            summary=title,
            severity="low",
            is_monetizable=False,
            pain_level=4,
            willingness_to_pay=4,
            niche_category=niche_category,
            source="reddit",
            opportunity_bucket="current_opportunity",
            post_type="advice_thread",
            first_handness="unknown",
            buyer_authority="unknown",
            pain_type=pain_type,
            evidence_quality="no_quote",
            evidence_match_rate=0.0,
            confidence=confidence,
            needs_human_review=True,
            solved_penalty=solved_penalty,
            comment_shill_risk=comment_shill_risk,
            opportunity_score=opportunity_score,
            triage_status=triage_status,
            score_components={"promotion_eligible": False, "evidence_rejection_reason": reason},
        )

    await db.insert_pain_point(
        subreddit="python",
        post_id="eligible",
        url="https://example.com/eligible",
        title="Verified invoice reconciliation pain",
        body="As founder, invoice reconciliation breaks payroll every week.",
        category="complaint",
        summary="Invoice reconciliation breaks payroll.",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="FinOps",
        source="reddit",
        opportunity_bucket="current_opportunity",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        pain_type="generic_question",
        verified_evidence=[{"quote": "invoice reconciliation breaks payroll", "source_type": "body", "match_type": "exact"}],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        confidence=0.9,
        opportunity_score=82.0,
        score_components={"promotion_eligible": True, "evidence_rejection_reason": ""},
    )
    await insert_row("generic", title="Generic CRM automation question", reason="generic_question")
    await insert_row("consumer", title="Consumer app rant", reason="consumer_rant", niche_category="B2C-noise")
    await insert_row("low-context", title="Too little context to evaluate", reason="low_context")
    await insert_row("no-evidence", title="High score but no exact quote", reason="no_verified_exact_quote")
    await insert_row("solved", title="Solved issue after switching tools", reason="solved_issue", solved_penalty=0.35)
    await insert_row("shill", title="Looks like vendor promotion", reason="shill_risk", comment_shill_risk=0.9)
    await insert_row("duplicate", title="Duplicate of existing invoice thread", reason="duplicate", triage_status="merged")
    for index in range(20):
        await insert_row(f"overflow-{index}", title=f"Overflow rejected item {index}", reason="no_verified_exact_quote", opportunity_score=40 - index)

    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    digest = await pipeline.generate_digest(subreddit="python", hours=24)

    assert [item["post_id"] for item in digest["top_items"]] == ["eligible"]
    rejected = digest["rejected_noise_items"]
    assert len(rejected) == 12
    assert "eligible" not in {item["post_id"] for item in rejected}
    assert {item["rejection_reason"] for item in rejected} >= {
        "generic_question",
        "consumer_rant",
        "low_context",
        "no_evidence",
        "solved_issue",
        "shill_risk",
        "duplicate",
    }
    assert {item["post_id"] for item in rejected} >= {"duplicate", "generic", "consumer", "low-context"}
    assert all(item["rejection_reason_label"] for item in rejected)
    assert digest["rejected_noise_counts"]["duplicate"] == 1
    assert digest["rejected_noise_counts"]["no_evidence"] >= 1


def test_wave5_score_components_include_weights_and_raw_score_increases_with_wtp_workaround_failure(tmp_path):
    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(), openrouter=None),
        db=AsyncMock(),
        reports_dir=str(tmp_path),
    )
    lower_signal = _wave5_signal(
        "wave5-score-lower",
        wtp_score=0.2,
        current_workaround="none",
        incumbent_failure="none",
        frequency_signal="single",
        urgency="mild",
    )
    higher_signal = _wave5_signal(
        "wave5-score-higher",
        wtp_score=0.9,
        current_workaround="paid_tool",
        incumbent_failure="explicit_competitor_failure",
        frequency_signal="thread_consensus",
        urgency="active_blocker",
    )

    pipeline._enrich_signal(lower_signal)
    pipeline._enrich_signal(higher_signal)

    components = higher_signal.score_components
    assert components is not None
    assert components["weights"] == {
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
    assert set(components["factors"]) == set(components["weights"])
    assert {"noise", "shill_risk", "solved", "stale", "type"} <= set(components["penalties"])
    assert components["raw_score"] == components["pre_promotion_score"]
    assert components["raw_opportunity_score"] == components["pre_promotion_score"]
    assert components["promotion_eligible"] is True
    assert components["evidence_rejection_reason"] == ""
    assert higher_signal.score_components["raw_score"] > lower_signal.score_components["raw_score"]


def test_wave5_unsupported_evidence_is_capped_and_not_promoted(tmp_path):
    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(), openrouter=None),
        db=AsyncMock(),
        reports_dir=str(tmp_path),
    )
    signal = _wave5_signal(
        "wave5-score-unsupported",
        intensity_score=1.0,
        wtp_score=1.0,
        current_workaround="paid_tool",
        incumbent_failure="switching",
        urgency="revenue_critical",
        verified=False,
        needs_human_review=True,
    )

    pipeline._enrich_signal(signal)

    assert signal.promotion_eligible is False
    assert signal.evidence_rejection_reason == "no_verified_exact_quote"
    assert signal.opportunity_score <= WEAK_SIGNAL_SCORE_CAP
    assert signal.score_components["promotion_eligible"] is False
    assert signal.score_components["evidence_rejection_reason"] == "no_verified_exact_quote"
    assert signal.score_components["pre_promotion_score"] >= signal.opportunity_score


async def test_pipeline_uses_semantic_candidates_and_routes_low_confidence_to_review(db, tmp_path):
    post = Post(
        post_id="semantic-low-confidence",
        subreddit="financeops",
        title="Expense approval routing takes days",
        body="As ops lead, expense approval routing takes days and blocks vendor payments.",
        url="https://example.com/semantic-low-confidence",
        score=6,
    )
    signal = PainSignal(
        post=post,
        category="wish",
        summary="Expense approvals are slow",
        severity="medium",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=7,
        niche_category="Finance Ops",
        analysis_mode="b2b",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="team_lead",
        evidence_spans=["expense approval routing takes days"],
        verified_evidence=[
            VerifiedEvidence(
                quote="expense approval routing takes days",
                source_type="body",
                post_id="semantic-low-confidence",
                comment_id=None,
                permalink="https://example.com/semantic-low-confidence",
                match_type="exact",
                match_confidence=1.0,
                created_utc=None,
            )
        ],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        confidence=0.42,
        needs_human_review=False,
        analysis_payload={"confidence": 0.42},
    )
    fake_embedder = object()
    classifier = SimpleNamespace(
        select_candidates=AsyncMock(
            return_value=(
                [post],
                {
                    "screen_rule_dropped_count": 1,
                    "screen_kept_count": 1,
                    "screen_capped_count": 0,
                    "screen_high_recall_candidate_count": 1,
                    "screen_semantic_candidate_count": 1,
                    "screen_semantic_scored_count": 2,
                    "screen_semantic_dropped_count": 1,
                    "screen_semantic_rescued_count": 1,
                    "screen_semantic_max_similarity": 0.91,
                    "screen_candidate_cap": 5,
                },
            )
        ),
        classify_batch=AsyncMock(return_value=[signal]),
        openrouter=None,
    )
    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=99,
        screen_max_llm_candidates_per_run=5,
        semantic_candidate_retrieval_enabled=True,
        semantic_embedder=fake_embedder,
        semantic_candidate_max_per_run=2,
        semantic_candidate_min_similarity=0.3,
        semantic_candidate_max_pool=50,
        min_confidence_for_promotion=0.55,
    )

    run = await pipeline.analyze_external_posts(posts=[post], source="hn", run_scope="financeops")

    classifier.select_candidates.assert_awaited_once()
    select_kwargs = classifier.select_candidates.await_args.kwargs
    assert select_kwargs["semantic_embedder"] is fake_embedder
    assert select_kwargs["semantic_max_candidates"] == 2
    assert run.source_coverage["candidate_generation"]["screen_semantic_rescued_count"] == 1
    assert run.pain_count == 1

    row = await db.get_pain_point("semantic-low-confidence")
    assert row is not None
    components = json.loads(row["score_components_json"])
    assert row["needs_human_review"] == 1
    assert components["promotion_eligible"] is False
    assert components["evidence_rejection_reason"] == "low_confidence_needs_review"
    assert components["low_confidence"] is True

    with open(run.json_path, "r", encoding="utf-8") as handle:
        report_payload = json.load(handle)
    candidate_generation = report_payload[0]["source_coverage"]["candidate_generation"]
    assert candidate_generation["screen_semantic_candidate_count"] == 1
    assert candidate_generation["screen_high_recall_candidate_count"] == 1


async def test_generate_digest_returns_no_clusters_when_no_rows(db, tmp_path):
    run_id = await db.create_macro_trend_run(window_days=30, candidate_count=1, cluster_count=1)
    await db.save_macro_cluster(
        run_id=run_id,
        canonical_key="unrelated-cluster",
        cluster_key="x1",
        label="Unrelated cluster",
        summary="No matching posts in this digest window.",
        estimated_monetization_signal="medium",
        item_count=1,
        aggregate_wtp=9.0,
        fresh_post_count=1,
        evergreen_post_count=0,
        median_buyer_authority=0.6,
        incumbents=["asana"],
        avg_opportunity_score=55.0,
        latest_source_created_ts=1713772800,
        members=[("x1", 0.9)],
    )

    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    digest = await pipeline.generate_digest(subreddit="missing", hours=24)

    assert digest["total"] == 0
    assert digest["top_clusters"] == []


async def test_analyze_external_posts_records_source(db, tmp_path):
    post = Post(
        post_id="hn:123",
        subreddit="hackernews",
        title="Internal tool pain",
        body="We built our own ETL tooling",
        url="https://news.ycombinator.com/item?id=123",
        score=12,
        source="hn",
    )
    signal = PainSignal(
        post=post,
        category="complaint",
        summary="HN complaint",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="Data",
        analysis_mode="b2b",
    )
    scraper = AsyncMock()
    classifier = SimpleNamespace(classify_batch=AsyncMock(return_value=[signal]), openrouter=AsyncMock())
    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    run = await pipeline.analyze_external_posts(posts=[post], source="hn", run_scope="hackernews")

    assert run.source == "hn"
    assert run.subreddit == "hackernews"
    stored = await db.get_pain_point("hn:123")
    assert stored is not None
    assert stored["source"] == "hn"


async def test_external_report_includes_source_family_without_promoting_weak_evidence(db, tmp_path):
    post = Post(
        post_id="review:g2:quickbooks-sync:1",
        subreddit="reviews_g2",
        title="QuickBooks Sync 1.0 star review",
        body="Manual payout reconciliation is still painful.",
        url="https://example.com/reviews",
        score=15,
        source="review:g2",
    )
    signal = PainSignal(
        post=post,
        category="complaint",
        summary="Manual payout reconciliation remains painful.",
        severity="high",
        is_monetizable=True,
        pain_level=9,
        willingness_to_pay=9,
        niche_category="FinOps",
        analysis_mode="b2b",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        verified_evidence=[],
        evidence_quality="no_quote",
        evidence_match_rate=0.0,
        confidence=0.9,
    )
    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(return_value=[signal]), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=99,
    )

    run = await pipeline.analyze_external_posts(posts=[post], source="review:g2", run_scope="quickbooks-sync")

    with open(run.json_path, "r", encoding="utf-8") as handle:
        report_payload = json.load(handle)
    assert report_payload[0]["source_family"] == "review:g2"
    assert report_payload[0]["promotion_eligible"] is False
    assert report_payload[0]["score_components"]["evidence_rejection_reason"] == "no_verified_exact_quote"

    digest = await pipeline.generate_digest(subreddit="reviews_g2", hours=24)
    assert digest["top_items"] == []
    assert [item["post_id"] for item in digest["needs_review_items"]] == ["review:g2:quickbooks-sync:1"]


async def test_analyze_posts_respects_llm_pause_without_budget_guard(db, tmp_path):
    await db.pause_llm(reason="cap hit")
    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(return_value=[]), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
        budget_guard=None,
    )
    with pytest.raises(RuntimeError):
        await pipeline.analyze_external_posts(posts=[], source="hn", run_scope="hn")


async def test_cross_source_dedup_skips_second_insert(db, tmp_path):
    """When deduplicator marks a signal as a dup, DB insert is skipped.

    Two separate ingestion runs simulate real cross-source dedup: a Reddit post
    is ingested first, then a semantically-identical HN post is processed and
    should be merged into the canonical reddit row rather than inserted.
    """
    import math
    from deduplicator import Deduplicator
    from embedder import Embedder

    post_reddit = Post(
        post_id="r_post1", subreddit="test", title="Stripe webhooks unreliable",
        body="They keep failing randomly", url="https://reddit.com/r_post1", score=5,
    )
    post_hn = Post(
        post_id="hn_post1", subreddit="hackernews", title="Stripe reliability is terrible",
        body="Webhooks drop all the time", url="https://news.ycombinator.com/hn_post1", score=3,
        source="hn",
    )
    signal_reddit = PainSignal(
        post=post_reddit, category="complaint", summary="Stripe webhook failures",
        severity="high", is_monetizable=True, pain_level=7, willingness_to_pay=7,
        niche_category="Payments", analysis_mode="b2b",
    )
    signal_hn = PainSignal(
        post=post_hn, category="complaint", summary="Stripe webhook failures",
        severity="high", is_monetizable=True, pain_level=7, willingness_to_pay=7,
        niche_category="Payments", analysis_mode="b2b",
    )

    scraper = AsyncMock()
    scraper.fetch_full_thread.return_value = []

    shared_vec = [1.0 / math.sqrt(96)] * 96
    embedder = MagicMock(spec=Embedder)
    embedder.embed = AsyncMock(return_value=shared_vec)

    deduplicator = Deduplicator(db=db, embedder=embedder, threshold=0.88)

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=SimpleNamespace(classify_batch=AsyncMock(return_value=[signal_reddit]), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=99,  # disable deep dive
        deduplicator=deduplicator,
    )

    # First ingestion: Reddit post → inserted as canonical, source="reddit"
    first_run = await pipeline.analyze_external_posts(posts=[post_reddit], source="reddit", run_scope="test")

    # Second ingestion: HN post (source="hn") → semantically identical, should merge
    pipeline.classifier = SimpleNamespace(classify_batch=AsyncMock(return_value=[signal_hn]), openrouter=None)
    second_run = await pipeline.analyze_external_posts(posts=[post_hn], source="hn", run_scope="hackernews")

    # Regression: run-level pain accounting must exclude dedup-merged non-persisted items.
    # Previously this run incorrectly reported pain_count=1 with one returned signal.
    assert first_run.pain_count == 1
    assert len(first_run.signals) == 1
    assert second_run.post_count == 1
    assert second_run.pain_count == 0
    assert second_run.signals == []

    with open(second_run.json_path, "r", encoding="utf-8") as handle:
        report_payload = json.load(handle)
    assert report_payload == []

    latest_report = await db.get_latest_report(subreddit="hackernews")
    assert latest_report is not None
    assert latest_report["pain_count"] == 0

    latest_analysis_run = await db.get_latest_analysis_run("hackernews")
    assert latest_analysis_run is not None
    assert latest_analysis_run["pain_count"] == 0

    # Only the canonical reddit row should exist; HN post was never inserted
    canonical = await db.get_pain_point("r_post1")
    assert canonical is not None
    assert canonical["cross_source_count"] == 2

    # The HN post was detected as a dup and skipped entirely — not in DB
    hn_row = await db.get_pain_point("hn_post1")
    assert hn_row is None


async def test_analyze_external_posts_mixed_outcomes_contract(db, tmp_path):
    """Mixed batch contract: only persisted canonical inserts count as pain."""
    import math
    from deduplicator import Deduplicator
    from embedder import Embedder

    canonical = Post(
        post_id="reddit_seed",
        subreddit="test",
        title="Stripe webhooks fail often",
        body="Production incidents every week",
        url="https://reddit.com/reddit_seed",
        score=10,
        source="reddit",
    )
    merge_candidate = Post(
        post_id="hn_dup2",
        subreddit="hackernews",
        title="Stripe webhook outages are frequent",
        body="Teams hit reliability issues repeatedly",
        url="https://news.ycombinator.com/item?id=dup2",
        score=4,
        source="hn",
    )
    inserted_post = Post(
        post_id="hn_new_insert",
        subreddit="hackernews",
        title="Need better vendor invoice reconciliation",
        body="Manual CSV work is painful",
        url="https://news.ycombinator.com/item?id=new_insert",
        score=6,
        source="hn",
    )
    non_pain_post = Post(
        post_id="hn_non_pain",
        subreddit="hackernews",
        title="Show and tell",
        body="Not a pain point",
        url="https://news.ycombinator.com/item?id=non_pain",
        score=1,
        source="hn",
    )

    canonical_signal = PainSignal(
        post=canonical,
        category="complaint",
        summary="Webhook reliability pain",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="Payments",
        analysis_mode="b2b",
    )
    merge_signal = PainSignal(
        post=merge_candidate,
        category="complaint",
        summary="Webhook reliability pain",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="Payments",
        analysis_mode="b2b",
    )
    inserted_signal = PainSignal(
        post=inserted_post,
        category="complaint",
        summary="Invoice reconciliation is manual",
        severity="medium",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=7,
        niche_category="FinOps",
        analysis_mode="b2b",
    )

    scraper = AsyncMock()
    scraper.fetch_full_thread.return_value = []

    shared_vec = [1.0 / math.sqrt(96)] * 96
    unique_vec = [0.0] * 96
    unique_vec[0] = 1.0

    embedder = MagicMock(spec=Embedder)

    async def embed_for_text(text: str) -> list[float]:
        if "webhook" in text.lower():
            return shared_vec
        return unique_vec

    embedder.embed = AsyncMock(side_effect=embed_for_text)
    deduplicator = Deduplicator(db=db, embedder=embedder, threshold=0.88)

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=SimpleNamespace(classify_batch=AsyncMock(return_value=[canonical_signal]), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=99,
        deduplicator=deduplicator,
    )

    seed_run = await pipeline.analyze_external_posts(posts=[canonical], source="reddit", run_scope="test")
    assert seed_run.pain_count == 1

    pipeline.classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[merge_signal, inserted_signal]),
        openrouter=None,
    )

    mixed_run = await pipeline.analyze_external_posts(
        posts=[merge_candidate, inserted_post, non_pain_post],
        source="hn",
        run_scope="hackernews",
    )

    assert mixed_run.post_count == 3
    assert mixed_run.pain_count == 1
    assert [signal.post.post_id for signal in mixed_run.signals] == ["hn_new_insert"]

    with open(mixed_run.json_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert len(payload) == 1
    assert payload[0]["post_id"] == "hn_new_insert"

    latest_report = await db.get_latest_report(subreddit="hackernews")
    assert latest_report is not None
    assert latest_report["pain_count"] == 1

    latest_analysis_run = await db.get_latest_analysis_run("hackernews")
    assert latest_analysis_run is not None
    assert latest_analysis_run["pain_count"] == 1

    canonical_row = await db.get_pain_point("reddit_seed")
    assert canonical_row is not None
    assert canonical_row["cross_source_count"] == 2

    inserted_row = await db.get_pain_point("hn_new_insert")
    assert inserted_row is not None

    merged_row = await db.get_pain_point("hn_dup2")
    assert merged_row is None

    non_pain_row = await db.get_pain_point("hn_non_pain")
    assert non_pain_row is None


async def test_analyze_external_posts_logs_dedup_outcome_metrics(db, tmp_path, caplog):
    """Completion log includes inserted/dedup/discarded counters."""
    import math
    from deduplicator import Deduplicator
    from embedder import Embedder

    post_reddit = Post(
        post_id="r_metrics", subreddit="test", title="API keeps failing", body="Broken often", url="https://reddit.com/r_metrics", score=5
    )
    post_hn_dup = Post(
        post_id="hn_metrics_dup", subreddit="hackernews", title="API failures are frequent", body="Broken often", url="https://news.ycombinator.com/dup", score=3, source="hn"
    )
    post_hn_new = Post(
        post_id="hn_metrics_new", subreddit="hackernews", title="Need onboarding automation", body="Manual setup takes hours", url="https://news.ycombinator.com/new", score=4, source="hn"
    )
    post_non_pain = Post(
        post_id="hn_metrics_non_pain", subreddit="hackernews", title="Launch post", body="No issue", url="https://news.ycombinator.com/non_pain", score=1, source="hn"
    )

    signal_reddit = PainSignal(
        post=post_reddit,
        category="complaint",
        summary="API reliability issue",
        severity="high",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=7,
        niche_category="DevTools",
        analysis_mode="b2b",
    )
    signal_hn_dup = PainSignal(
        post=post_hn_dup,
        category="complaint",
        summary="API reliability issue",
        severity="high",
        is_monetizable=True,
        pain_level=7,
        willingness_to_pay=7,
        niche_category="DevTools",
        analysis_mode="b2b",
    )
    signal_hn_new = PainSignal(
        post=post_hn_new,
        category="wish",
        summary="Needs onboarding automation",
        severity="medium",
        is_monetizable=True,
        pain_level=6,
        willingness_to_pay=6,
        niche_category="Operations",
        analysis_mode="b2b",
    )

    scraper = AsyncMock()
    scraper.fetch_full_thread.return_value = []

    shared_vec = [1.0 / math.sqrt(96)] * 96
    unique_vec = [0.0] * 96
    unique_vec[1] = 1.0

    embedder = MagicMock(spec=Embedder)

    async def embed_for_text(text: str) -> list[float]:
        if "api" in text.lower():
            return shared_vec
        return unique_vec

    embedder.embed = AsyncMock(side_effect=embed_for_text)
    deduplicator = Deduplicator(db=db, embedder=embedder, threshold=0.88)

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=SimpleNamespace(classify_batch=AsyncMock(return_value=[signal_reddit]), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
        deep_dive_wtp_threshold=99,
        deduplicator=deduplicator,
    )

    await pipeline.analyze_external_posts(posts=[post_reddit], source="reddit", run_scope="test")

    pipeline.classifier = SimpleNamespace(
        classify_batch=AsyncMock(return_value=[signal_hn_dup, signal_hn_new]),
        openrouter=None,
    )

    with caplog.at_level("INFO"):
        await pipeline.analyze_external_posts(
            posts=[post_hn_dup, post_hn_new, post_non_pain],
            source="hn",
            run_scope="hackernews",
        )

    completion_logs = [rec.message for rec in caplog.records if "analysis_complete stage=analyze" in rec.message]
    assert any("inserted_count=1" in message for message in completion_logs)
    assert any("dedup_merged_count=1" in message for message in completion_logs)
    assert any("discarded_non_pain_count=1" in message for message in completion_logs)
