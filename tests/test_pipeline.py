import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from classifier import PainSignal
from db import Database
from openrouter import DeepDiveResult
from pipeline import AnalysisPipeline
from scraper import Post


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test_pipeline.db"))
    await database.init()
    yield database
    await database.close()


async def test_analyze_subreddit_persists_report_and_rows(db, tmp_path):
    post = Post(
        post_id="p1",
        subreddit="python",
        title="I can't make this work",
        body="Still broken",
        url="https://reddit.com/p1",
        score=10,
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

    latest = await db.get_latest_report(subreddit="python")
    assert latest is not None
    assert latest["json_path"] == run.json_path

    rows = await db.get_pain_points("python")
    assert len(rows) == 1
    assert rows[0]["post_id"] == "p1"
    assert rows[0]["deep_dive_status"] == "completed"


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
        classify_batch=AsyncMock(return_value=[capped_signal]),
        openrouter=AsyncMock(),
    )

    pipeline = AnalysisPipeline(
        scraper=scraper,
        classifier=classifier,
        db=db,
        reports_dir=str(tmp_path / "reports"),
        llm_max_classifications_per_run=1,
    )

    run = await pipeline.analyze_subreddit("python", limit=10)

    classify_arg = classifier.classify_batch.await_args.args[0]
    assert [post.post_id for post in classify_arg] == ["fresh0"]
    assert run.post_count == 3
    assert run.pain_count == 1


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
        pain_level=9,
        willingness_to_pay=8,
        niche_category="DevOps",
        deep_dive_summary="Need better alerts",
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
        pain_level=7,
        willingness_to_pay=7,
        niche_category="DevOps",
    )

    pipeline = AnalysisPipeline(
        scraper=AsyncMock(),
        classifier=SimpleNamespace(classify_batch=AsyncMock(), openrouter=None),
        db=db,
        reports_dir=str(tmp_path / "reports"),
    )

    digest = await pipeline.generate_digest(subreddit="python", hours=24)
    assert digest["total"] == 2
    assert digest["top_items"][0]["post_id"] == "d1"
    assert digest["niche_counts"]["DevOps"] == 2
    assert "Need better alerts" in digest["recurring_blockers"]


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
