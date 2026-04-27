from datetime import UTC, datetime
import json
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
    author_hash: str | None = None,
    source: str = "reddit",
    verified_evidence: list[dict] | None = None,
    evidence_quality: str = "no_quote",
    current_workaround: str = "",
    incumbent_failure: str = "",
    user_context_json: dict | None = None,
    pain_type: str = "unknown",
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
        source=source,
        source_created_ts=source_created_ts,
        author_hash=author_hash,
        verified_evidence=verified_evidence,
        evidence_quality=evidence_quality,
        current_workaround=current_workaround,
        incumbent_failure=incumbent_failure,
        user_context_json=user_context_json,
        pain_type=pain_type,
    )


async def test_run_returns_empty_when_no_candidates(db):
    clusterer = MacroTrendClusterer(db=db, openrouter=None, min_cluster_size=2)
    result = await clusterer.run(window_days=7)

    assert result.candidate_count == 0
    assert result.clusters == []
    latest = await db.get_latest_macro_trend_run()
    assert latest is not None
    assert latest["cluster_count"] == 0


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


async def test_run_persists_normalized_frequency_metrics(db):
    await db.record_source_coverage_run(
        source="reddit",
        scope="python",
        fetched_posts=200,
        fetched_comments=1000,
        source_method_used="public_json",
        duration_ms=100,
    )
    await _seed_candidate(
        db,
        post_id="reddit:n1",
        title="QuickBooks sync failures",
        summary="Manual ledger repair every week",
        wtp=9,
        opportunity_score=80.0,
        author_hash="author-1",
    )
    await _seed_candidate(
        db,
        post_id="reddit:n2",
        title="QuickBooks reconciliation keeps breaking",
        summary="Manual ledger repair every month",
        wtp=8,
        opportunity_score=70.0,
        author_hash="author-2",
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
    assert cluster.pain_mentions_per_1000_posts == pytest.approx(10.0)
    assert cluster.pain_mentions_per_1000_comments == pytest.approx(2.0)
    assert cluster.unique_authors_count == 2
    assert cluster.unique_threads_count == 2
    assert cluster.source_activity_baseline["fetched_posts"] == 200

    latest_clusters = await db.get_latest_canonical_clusters(limit=5)
    assert latest_clusters[0]["pain_mentions_per_1000_posts"] == pytest.approx(10.0)
    assert latest_clusters[0]["pain_mentions_per_1000_comments"] == pytest.approx(2.0)
    assert latest_clusters[0]["unique_authors_count"] == 2
    assert latest_clusters[0]["unique_threads_count"] == 2


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


async def test_run_uses_injected_embedder_for_primary_cluster_embeddings(db):
    await _seed_candidate(
        db,
        post_id="reddit:e1",
        title="QuickBooks payout reconciliation",
        summary="Finance ops cannot reconcile Stripe deposits.",
        wtp=9,
        competitor_tags=["quickbooks", "stripe"],
        verified_evidence=[{"quote": "QuickBooks deposits do not match Stripe payouts", "match_type": "exact"}],
        evidence_quality="exact_quote",
    )
    await _seed_candidate(
        db,
        post_id="reddit:e2",
        title="Stripe payout reconciliation",
        summary="Finance ops exports CSVs for QuickBooks deposits.",
        wtp=8,
        competitor_tags=["quickbooks", "stripe"],
        verified_evidence=[{"quote": "Stripe payout CSVs are required for QuickBooks", "match_type": "exact"}],
        evidence_quality="exact_quote",
    )

    class FakeEmbedder:
        def __init__(self):
            self.texts: list[str] = []

        async def embed_many(self, texts: list[str]) -> list[list[float]]:
            self.texts.extend(texts)
            return [[1.0, 0.0] for _ in texts]

    fake_embedder = FakeEmbedder()
    clusterer = MacroTrendClusterer(
        db=db,
        openrouter=None,
        embedder=fake_embedder,
        min_cluster_size=2,
        similarity_threshold=0.9,
        min_wtp=7,
    )

    result = await clusterer.run(window_days=30)

    assert len(result.clusters) == 1
    assert set(result.clusters[0].post_ids) == {"reddit:e1", "reddit:e2"}
    assert len(fake_embedder.texts) == 2
    assert all("quickbooks" in text.lower() and "stripe" in text.lower() for text in fake_embedder.texts)


def test_compose_problem_statement_uses_verified_evidence_and_context():
    text = MacroTrendClusterer._compose_problem_statement(
        {
            "title": "Generic manual spreadsheet problem",
            "summary": "Manual spreadsheet workaround keeps happening.",
            "verified_evidence_json": json.dumps(
                [{"quote": "QuickBooks payout reconciliation breaks every Friday", "match_type": "exact"}]
            ),
            "current_workaround": "spreadsheet",
            "incumbent_failure": "explicit_competitor_failure",
            "user_context_json": json.dumps({"role": "finance ops", "tool_stack": ["QuickBooks", "Stripe"]}),
            "competitor_tags": json.dumps(["quickbooks", "stripe"]),
            "source": "reddit",
            "subreddit": "accounting",
            "niche_category": "FinOps",
            "pain_type": "integration_gap",
        }
    ).lower()

    assert "manual spreadsheet workaround" in text
    assert "quickbooks payout reconciliation breaks every friday" in text
    assert "spreadsheet" in text
    assert "explicit_competitor_failure" in text
    assert "finance ops" in text
    assert "quickbooks" in text
    assert "reddit" in text
    assert "finops" in text
    assert "integration_gap" in text


async def test_run_clusters_problem_statements_not_generic_titles(db):
    shared_title = "Manual spreadsheet problem"
    shared_summary = "We still use a manual spreadsheet workaround and it keeps breaking."
    await _seed_candidate(
        db,
        post_id="reddit:q1",
        title=shared_title,
        summary=shared_summary,
        wtp=9,
        competitor_tags=["quickbooks", "stripe"],
        verified_evidence=[{"quote": "QuickBooks payout reconciliation breaks every Friday", "match_type": "exact"}],
        evidence_quality="exact_quote",
        current_workaround="spreadsheet",
        incumbent_failure="explicit_competitor_failure",
        user_context_json={"role": "finance ops", "tool_stack": ["QuickBooks", "Stripe"]},
        pain_type="integration_gap",
    )
    await _seed_candidate(
        db,
        post_id="reddit:q2",
        title=shared_title,
        summary=shared_summary,
        wtp=8,
        competitor_tags=["quickbooks", "stripe"],
        verified_evidence=[{"quote": "Stripe fees do not reconcile to QuickBooks deposits", "match_type": "exact"}],
        evidence_quality="exact_quote",
        current_workaround="csv export",
        incumbent_failure="explicit_competitor_failure",
        user_context_json={"role": "finance ops", "tool_stack": ["QuickBooks", "Stripe"]},
        pain_type="integration_gap",
    )
    await _seed_candidate(
        db,
        post_id="reddit:s1",
        title=shared_title,
        summary=shared_summary,
        wtp=9,
        competitor_tags=["salesforce", "hubspot"],
        verified_evidence=[{"quote": "Salesforce HubSpot attribution sync loses lead source", "match_type": "exact"}],
        evidence_quality="exact_quote",
        current_workaround="spreadsheet",
        incumbent_failure="explicit_competitor_failure",
        user_context_json={"role": "marketing ops", "tool_stack": ["Salesforce", "HubSpot"]},
        pain_type="reporting_gap",
    )
    await _seed_candidate(
        db,
        post_id="reddit:s2",
        title=shared_title,
        summary=shared_summary,
        wtp=8,
        competitor_tags=["salesforce", "hubspot"],
        verified_evidence=[{"quote": "HubSpot campaign IDs disappear after Salesforce sync", "match_type": "exact"}],
        evidence_quality="exact_quote",
        current_workaround="spreadsheet",
        incumbent_failure="explicit_competitor_failure",
        user_context_json={"role": "marketing ops", "tool_stack": ["Salesforce", "HubSpot"]},
        pain_type="reporting_gap",
    )

    clusterer = MacroTrendClusterer(db=db, openrouter=None, min_cluster_size=2, similarity_threshold=0.36, min_wtp=7)
    result = await clusterer.run(window_days=30)

    member_sets = {frozenset(cluster.post_ids) for cluster in result.clusters}
    assert member_sets == {frozenset({"reddit:q1", "reddit:q2"}), frozenset({"reddit:s1", "reddit:s2"})}


async def test_run_persists_cluster_quality_and_representative_examples(db):
    await _seed_candidate(
        db,
        post_id="reddit:v1",
        title="QuickBooks payout reconciliation",
        summary="Finance ops manually reconcile payouts.",
        wtp=9,
        opportunity_score=88.0,
        competitor_tags=["quickbooks", "stripe"],
        verified_evidence=[{"quote": "QuickBooks payout reconciliation breaks every Friday", "match_type": "exact"}],
        evidence_quality="exact_quote",
        current_workaround="manual CSV payout reconciliation",
        incumbent_failure="Stripe deposits do not match QuickBooks payouts",
        user_context_json={"persona": "finance ops lead", "workflow": "weekly payout close"},
        author_hash="author-a",
        source="reddit",
    )
    await _seed_candidate(
        db,
        post_id="hn:v2",
        title="Stripe deposits fail QuickBooks reconciliation",
        summary="Finance teams export CSVs for the same payout mismatch.",
        wtp=8,
        opportunity_score=82.0,
        competitor_tags=["quickbooks", "stripe"],
        verified_evidence=[{"quote": "Stripe deposits never match QuickBooks", "match_type": "exact"}],
        evidence_quality="exact_quote",
        author_hash="author-b",
        source="hn",
    )

    clusterer = MacroTrendClusterer(db=db, openrouter=None, min_cluster_size=2, similarity_threshold=0.2, min_wtp=7)
    result = await clusterer.run(window_days=30)

    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    assert 0.0 < cluster.cluster_stability_score <= 1.0
    assert cluster.verified_quote_count == 2
    assert cluster.independent_source_count == 2
    assert cluster.unique_author_count == 2
    representative = cluster.representative_examples[0]
    assert representative["post_id"] in {"reddit:v1", "hn:v2"}
    if representative["post_id"] == "reddit:v1":
        assert representative["current_workaround"] == "manual CSV payout reconciliation"
        assert representative["incumbent_failure"] == "Stripe deposits do not match QuickBooks payouts"
        assert representative["user_context"] == {"persona": "finance ops lead", "workflow": "weekly payout close"}
        assert representative["willingness_to_pay"] == 9
        assert representative["opportunity_score"] == 88.0
        assert representative["buyer_authority_score"] == 0.55
    assert cluster.normalized_frequency["unique_authors_count"] == 2

    stored = await db.get_macro_clusters(result.run_id)
    assert stored[0]["cluster_stability_score"] == cluster.cluster_stability_score
    assert stored[0]["verified_quote_count"] == 2
    assert stored[0]["independent_source_count"] == 2
    assert stored[0]["unique_author_count"] == 2
    assert stored[0]["representative_examples"][0]["post_id"] in {"reddit:v1", "hn:v2"}
    assert stored[0]["representative_examples"][0]["current_workaround"] == "manual CSV payout reconciliation"
    assert stored[0]["representative_examples"][0]["incumbent_failure"] == "Stripe deposits do not match QuickBooks payouts"
    assert stored[0]["representative_examples"][0]["user_context"] == {"persona": "finance ops lead", "workflow": "weekly payout close"}
    assert stored[0]["normalized_frequency"]["unique_authors_count"] == 2


def test_representative_examples_preserve_competitor_failure_metadata():
    examples = MacroTrendClusterer._representative_examples(
        [
            {
                "post_id": "reddit:r1",
                "title": "HubSpot renewal pricing and workflow lock-in",
                "summary": "RevOps wants to switch after the renewal doubled.",
                "willingness_to_pay": 9,
                "opportunity_score": 93.0,
                "competitor_tags": json.dumps(["hubspot", "airtable"]),
                "verified_evidence_json": json.dumps(
                    [{"quote": "HubSpot renewal doubled and we cannot export workflows", "match_type": "exact"}]
                ),
                "evidence_quality": "exact_quote",
                "current_workaround": "exporting CSVs to Airtable",
                "incumbent_failure": "HubSpot renewal pricing doubled and contract lock-in blocks switching",
                "pain_type": "pricing_pain",
                "user_context_json": json.dumps({"persona": "RevOps lead"}),
            },
            {
                "post_id": "reddit:r2",
                "title": "HubSpot missing approvals forces workarounds",
                "summary": "Ops teams route approvals through Airtable.",
                "willingness_to_pay": 8,
                "opportunity_score": 84.0,
                "competitor_tags": json.dumps(["hubspot", "airtable"]),
                "verified_evidence_json": json.dumps(
                    [{"quote": "HubSpot is missing approval routing so we use Airtable", "match_type": "exact"}]
                ),
                "evidence_quality": "exact_quote",
                "current_workaround": "Airtable approval workaround",
                "incumbent_failure": "HubSpot is missing approval routing and support keeps stalling",
                "pain_type": "missing_feature",
                "user_context_json": json.dumps({"persona": "RevOps lead"}),
            },
        ]
    )

    representative = examples[0]
    assert representative["competitor_tags"] == ["hubspot", "airtable"]
    assert representative["failure_signals"] == [
        "pricing_pain",
        "lock_in_switching_churn",
        "workaround",
        "alternative_tool_mentions",
    ]
