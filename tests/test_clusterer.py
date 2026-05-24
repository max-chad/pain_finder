from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from clusterer import MacroTrendClusterer
from db import Database
from openrouter import MacroClusterLabel


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "clusterer.db"))
    await database.init()
    yield database
    await database.close()


async def _seed_candidate(
    db: Database,
    *,
    post_id: str,
    title: str,
    summary: str,
    wtp: int,
    triage_status: str = "favorite",
    opportunity_bucket: str = "current_opportunity",
    buyer_authority_score: float = 0.55,
    opportunity_score: float = 0.0,
    source_created_ts: int | None = None,
    competitor_tags: list[str] | None = None,
):
    await db.insert_pain_point(
        subreddit="python",
        post_id=post_id,
        url=f"https://example.com/{post_id}",
        title=title,
        body="body",
        category="complaint",
        summary=summary,
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=wtp,
        niche_category="DevOps",
        competitor_tags=competitor_tags or ["quickbooks", "jira"],
        triage_status=triage_status,
        opportunity_bucket=opportunity_bucket,
        buyer_authority_score=buyer_authority_score,
        opportunity_score=opportunity_score,
        source_created_ts=source_created_ts,
    )


async def test_run_returns_empty_when_no_candidates(db):
    clusterer = MacroTrendClusterer(db=db, openrouter=None, min_cluster_size=2)
    result = await clusterer.run(window_days=7)

    assert result.candidate_count == 0
    assert result.clusters == []
    latest = await db.get_latest_macro_trend_run()
    assert latest is not None
    assert latest["cluster_count"] == 0


def test_fallback_embedding_uses_stable_token_buckets():
    vector = MacroTrendClusterer._embed("quickbooks quickbooks sync")
    quickbooks_bucket = MacroTrendClusterer._stable_token_bucket("quickbooks", 96)
    sync_bucket = MacroTrendClusterer._stable_token_bucket("sync", 96)

    assert quickbooks_bucket == MacroTrendClusterer._stable_token_bucket("quickbooks", 96)
    assert vector[quickbooks_bucket] > vector[sync_bucket]


async def test_run_clusters_candidates_and_persists_fallback_labels(db):
    await _seed_candidate(
        db,
        post_id="reddit:a1",
        title="QuickBooks API webhook failures",
        summary="Sync jobs fail and teams do manual repair",
        wtp=9,
    )
    await _seed_candidate(
        db,
        post_id="reddit:a2",
        title="QuickBooks API keeps timing out",
        summary="Manual reconciliation every week",
        wtp=8,
    )
    # below threshold and not favorite, should be excluded from candidates
    await _seed_candidate(
        db,
        post_id="reddit:a3",
        title="Low signal",
        summary="minor annoyance",
        wtp=1,
        triage_status="new",
    )

    clusterer = MacroTrendClusterer(
        db=db,
        openrouter=None,
        min_cluster_size=2,
        similarity_threshold=0.1,
        min_wtp=8,
    )
    result = await clusterer.run(window_days=30)

    assert result.candidate_count == 2
    assert len(result.clusters) == 1
    assert result.clusters[0].item_count == 2
    assert result.clusters[0].estimated_monetization_signal in {"medium", "high"}

    latest = await db.get_latest_macro_trend_run()
    assert latest is not None
    clusters = await db.get_macro_clusters(latest["id"])
    assert len(clusters) == 1
    assert set(clusters[0]["post_ids"]) == {"reddit:a1", "reddit:a2"}
    post_cluster = await db.get_latest_macro_cluster_for_post("reddit:a1")
    assert post_cluster is not None


async def test_run_uses_openrouter_label_when_available(db):
    await _seed_candidate(
        db,
        post_id="reddit:b1",
        title="Shopify SKU mapping pain",
        summary="Need robust mapping layer",
        wtp=9,
    )
    await _seed_candidate(
        db,
        post_id="reddit:b2",
        title="Shopify API mapping breakages",
        summary="Inventory mismatch costs money",
        wtp=9,
    )

    openrouter = AsyncMock()
    openrouter.label_macro_cluster.return_value = MacroClusterLabel(
        label="Shopify integration failures",
        summary="Recurring breakage in SKU/inventory synchronization.",
        estimated_monetization_signal="high",
        key_complaints=["mapping", "sync delays"],
    )

    clusterer = MacroTrendClusterer(
        db=db,
        openrouter=openrouter,
        min_cluster_size=2,
        similarity_threshold=0.1,
    )
    result = await clusterer.run(window_days=30)

    assert len(result.clusters) == 1
    assert result.clusters[0].label == "Shopify integration failures"
    openrouter.label_macro_cluster.assert_awaited_once()


async def test_run_persists_canonical_cluster_aggregates(db):
    now_ts = int(datetime.now(UTC).timestamp())
    await _seed_candidate(
        db,
        post_id="reddit:c1",
        title="QuickBooks sync failures",
        summary="Manual ledger repair every week",
        wtp=9,
        opportunity_bucket="current_opportunity",
        buyer_authority_score=0.95,
        opportunity_score=91.0,
        source_created_ts=now_ts - 60,
        competitor_tags=["quickbooks", "xero"],
    )
    await _seed_candidate(
        db,
        post_id="reddit:c2",
        title="QuickBooks reconciliation keeps breaking",
        summary="Finance ops team exports CSVs daily",
        wtp=8,
        opportunity_bucket="evergreen_pain",
        buyer_authority_score=0.65,
        opportunity_score=73.0,
        source_created_ts=now_ts - 3600,
        competitor_tags=["quickbooks", "netsuite"],
    )

    clusterer = MacroTrendClusterer(
        db=db,
        openrouter=None,
        min_cluster_size=2,
        similarity_threshold=0.1,
        min_wtp=7,
    )
    result = await clusterer.run(window_days=30)

    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    assert cluster.canonical_key != "reddit:c1"
    assert "quickbooks" in cluster.canonical_key
    assert "trend" not in cluster.canonical_key
    assert "detected" not in cluster.canonical_key
    assert cluster.fresh_post_count == 1
    assert cluster.evergreen_post_count == 1
    assert cluster.median_buyer_authority == pytest.approx(0.8)
    assert cluster.avg_opportunity_score == pytest.approx(82.0)
    assert cluster.latest_source_created_ts == now_ts - 60
    assert cluster.incumbents[:2] == ["quickbooks", "netsuite"] or cluster.incumbents[:2] == ["quickbooks", "xero"]

    latest_clusters = await db.get_latest_canonical_clusters(limit=5)
    assert len(latest_clusters) == 1
    assert latest_clusters[0]["canonical_key"] == cluster.canonical_key
    assert latest_clusters[0]["fresh_post_count"] == 1
    assert latest_clusters[0]["evergreen_post_count"] == 1


def test_compose_candidate_text_handles_invalid_competitor_json():
    text = MacroTrendClusterer._compose_candidate_text(
        {
            "title": "t",
            "summary": "s",
            "deep_dive_summary": "d",
            "competitor_tags": "{invalid",
        }
    )
    assert "t" in text
    assert "s" in text
    assert "d" in text
