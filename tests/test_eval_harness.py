import json
import runpy
import sys
from pathlib import Path

import pytest

from classifier import PainSignal
from evidence import VerifiedEvidence
from scraper import Post


REFERENCE_NOW_TS = 1776816000  # 2026-04-21T00:00:00Z


@pytest.fixture
def eval_harness_module():
    import importlib

    module = importlib.import_module("eval_harness")
    return importlib.reload(module)


@pytest.fixture
def sample_posts():
    return [
        Post(
            post_id="reddit:p1",
            subreddit="ops",
            title="We still reconcile invoices in spreadsheets every week",
            body="Founder here. This manual workflow is awful and takes hours.",
            url="https://reddit.com/p1",
            score=15,
            source_created_at="2026-04-18T00:00:00+00:00",
            source_created_ts=1776470400,
        ),
        Post(
            post_id="reddit:p2",
            subreddit="saas",
            title="What newsletter should I read about pricing?",
            body="Just looking for resources.",
            url="https://reddit.com/p2",
            score=4,
            source_created_at="2025-08-01T00:00:00+00:00",
            source_created_ts=1754006400,
        ),
        Post(
            post_id="reddit:p3",
            subreddit="devops",
            title="PagerDuty exports keep failing and we built a CSV workaround",
            body="My team does this every day and it still breaks.",
            url="https://reddit.com/p3",
            score=11,
            source_created_at="2025-07-15T00:00:00+00:00",
            source_created_ts=1752537600,
        ),
    ]


@pytest.fixture
def sample_labels():
    return [
        _label(
            "reddit:p1",
            is_pain=True,
            is_monetizable=True,
            post_type="first_person_pain",
            is_current_opportunity=True,
            first_handness="first_hand",
            buyer_authority="founder_owner",
            intensity_label="high",
            urgency_label="high",
            wtp_label="high",
            expected_cluster_key="invoice_reconciliation",
            feedback_useful=True,
        ),
        _label(
            "reddit:p2",
            is_pain=False,
            is_monetizable=False,
            post_type="advice_thread",
            is_current_opportunity=False,
            first_handness="unknown",
            buyer_authority="unknown",
            pain_type="unknown",
            expression_type="unknown",
            intensity_label="none",
            urgency_label="none",
            wtp_label="none",
            current_workaround="",
            incumbent_failure="",
            evidence_quality="no_quote",
            opportunity_type="not_opportunity",
            hard_negative_type="generic_recommendation",
            expected_cluster_key="",
            evidence_relevance="not_applicable",
            source_link_validity="valid",
            feedback_useful=False,
        ),
        _label(
            "reddit:p3",
            is_pain=True,
            is_monetizable=False,
            post_type="vendor_rant",
            is_current_opportunity=False,
            first_handness="first_hand",
            buyer_authority="manager",
            pain_type="integration",
            expression_type="vendor_rant",
            intensity_label="medium",
            urgency_label="low",
            wtp_label="low",
            opportunity_type="evergreen_pain",
            hard_negative_type="none",
            expected_cluster_key="incident_export_failure",
            evidence_relevance="relevant",
            source_link_validity="valid",
            feedback_useful=False,
        ),
    ]


@pytest.fixture
def sample_predictions():
    return [
        {
            "post_id": "reddit:p1",
            "prediction_status": "classified",
            "prescreen_score": 6,
            "is_pain": True,
            "is_monetizable": True,
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "opportunity_bucket": "current_opportunity",
            "analysis_mode": "dspy_b2b",
            "verified_evidence": [
                {
                    "quote": "manual workflow is awful",
                    "source_type": "body",
                    "post_id": "reddit:p1",
                    "match_type": "exact",
                    "match_confidence": 1.0,
                }
            ],
            "evidence_quality": "exact_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.82,
            "needs_human_review": False,
            "cluster_key": "invoice_reconciliation_v1",
            "opportunity_score": 88.0,
            "cost_usd": 0.12,
            "latency_ms": 900,
        },
        {
            "post_id": "reddit:p2",
            "prediction_status": "classified",
            "prescreen_score": 3,
            "is_pain": True,
            "is_monetizable": False,
            "post_type": "advice_thread",
            "first_handness": "unknown",
            "buyer_authority": "unknown",
            "opportunity_bucket": "current_opportunity",
            "analysis_mode": "legacy_llm",
            "verified_evidence": [],
            "evidence_quality": "no_quote",
            "evidence_match_rate": 0.0,
            "confidence": 0.32,
            "needs_human_review": True,
            "cluster_key": "generic_advice_false_positive",
            "opportunity_score": 41.0,
            "cost_usd": 0.08,
            "latency_ms": 650,
        },
        {
            "post_id": "reddit:p3",
            "prediction_status": "screened_out",
            "prescreen_score": 1,
            "is_pain": False,
            "is_monetizable": False,
            "post_type": "unclassified",
            "first_handness": "unknown",
            "buyer_authority": "unknown",
            "opportunity_bucket": "evergreen_pain",
            "analysis_mode": "screened_out",
            "cluster_key": "incident_export_failure_a",
            "opportunity_score": 0.0,
            "cost_usd": 0.0,
            "latency_ms": 0,
        },
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _label(
    post_id: str,
    *,
    is_pain: bool,
    is_monetizable: bool,
    post_type: str,
    is_current_opportunity: bool,
    first_handness: str,
    buyer_authority: str,
    pain_type: str = "workflow",
    expression_type: str = "first_person_complaint",
    intensity_label: str = "medium",
    urgency_label: str = "medium",
    wtp_label: str = "medium",
    current_workaround: str = "manual spreadsheet workaround",
    incumbent_failure: str = "incumbent workflow is brittle",
    evidence_quality: str = "exact_quote",
    opportunity_type: str = "current_opportunity",
    hard_negative_type: str = "none",
    expected_cluster_key: str = "ops_manual_workflow",
    evidence_relevance: str = "relevant",
    source_link_validity: str = "valid",
    feedback_useful: bool | None = None,
) -> dict:
    row = {
        "post_id": post_id,
        "is_pain": is_pain,
        "is_monetizable": is_monetizable,
        "post_type": post_type,
        "pain_type": pain_type,
        "expression_type": expression_type,
        "first_handness": first_handness,
        "buyer_authority": buyer_authority,
        "intensity_label": intensity_label,
        "urgency_label": urgency_label,
        "wtp_label": wtp_label,
        "current_workaround": current_workaround,
        "incumbent_failure": incumbent_failure,
        "evidence_quality": evidence_quality,
        "evidence_expected": evidence_quality != "no_quote",
        "opportunity_type": opportunity_type,
        "is_current_opportunity": is_current_opportunity,
        "hard_negative_type": hard_negative_type,
        "expected_cluster_key": expected_cluster_key,
        "evidence_relevance": evidence_relevance,
        "source_link_validity": source_link_validity,
        "reference_now_ts": REFERENCE_NOW_TS,
    }
    if feedback_useful is not None:
        row["feedback_useful"] = feedback_useful
    return row


def test_evaluate_predictions_computes_core_metrics(eval_harness_module, sample_posts, sample_labels, sample_predictions):
    metrics = eval_harness_module.evaluate_predictions(
        posts=sample_posts,
        labels=sample_labels,
        predictions=sample_predictions,
        reference_now_ts=REFERENCE_NOW_TS,
    )

    assert metrics["dataset_size"] == 3
    assert metrics["pain"]["tp"] == 1
    assert metrics["pain"]["fp"] == 1
    assert metrics["pain"]["fn"] == 1
    assert metrics["pain"]["precision"] == pytest.approx(0.5)
    assert metrics["pain"]["recall"] == pytest.approx(0.5)
    assert metrics["pain"]["f1"] == pytest.approx(0.5)
    assert metrics["monetizable"]["precision"] == pytest.approx(1.0)
    assert metrics["stale_leakage"]["count"] == 0
    assert metrics["stale_leakage"]["candidate_count"] == 1
    assert metrics["stale_leakage"]["rate"] == pytest.approx(0.0)
    assert metrics["screening_false_negative_count"] == 1
    assert metrics["screening_false_negative_post_ids"] == ["reddit:p3"]
    assert metrics["post_type_confusion"]["vendor_rant"]["unclassified"] == 1
    assert metrics["first_handness_accuracy"] == pytest.approx(0.667)
    assert metrics["buyer_authority_accuracy"] == pytest.approx(0.667)
    assert metrics["evidence"]["predicted_pain_count"] == 2
    assert metrics["evidence"]["coverage_count"] == 1
    assert metrics["evidence"]["coverage_rate"] == pytest.approx(0.5)
    assert metrics["evidence"]["exact_match_count"] == 1
    assert metrics["evidence"]["exact_match_rate"] == pytest.approx(0.5)
    assert metrics["evidence"]["needs_human_review_count"] == 1
    assert metrics["evidence"]["quality_counts"]["exact_quote"] == 1
    assert metrics["evidence"]["quality_counts"]["no_quote"] == 1
    assert metrics["evidence"]["manual_relevance"]["evaluated_count"] == 1
    assert metrics["evidence"]["manual_relevance"]["relevant_count"] == 1
    assert metrics["evidence"]["source_link_validity"]["valid_rate"] == pytest.approx(1.0)
    assert metrics["hard_negatives"]["false_positive_count"] == 1
    assert "screening_false_negative_count" not in metrics["hard_negatives"]
    assert metrics["hard_negatives"]["by_type"]["generic_recommendation"]["false_positive_rate"] == pytest.approx(1.0)
    assert "screening_false_negative_count" not in metrics["hard_negatives"]["by_type"]["generic_recommendation"]
    assert metrics["clusters"]["evaluated_count"] == 2
    assert metrics["clusters"]["purity"] == pytest.approx(1.0)
    assert metrics["clusters"]["duplicate_rate"] == pytest.approx(0.0)
    assert metrics["top_n_useful_rate"]["top_1"] == pytest.approx(1.0)
    assert metrics["cost_per_useful_insight"] == pytest.approx(0.2)
    assert metrics["latency_ms_per_prediction"] == pytest.approx(516.667)


def test_missing_predictions_do_not_create_usefulness_or_stale_leakage(eval_harness_module, sample_posts, sample_labels):
    metrics = eval_harness_module.evaluate_predictions(
        posts=sample_posts,
        labels=sample_labels,
        predictions=[],
        reference_now_ts=REFERENCE_NOW_TS,
    )

    assert metrics["pain"]["fn"] == 2
    assert metrics["stale_leakage"]["candidate_count"] == 1
    assert metrics["stale_leakage"]["count"] == 0
    assert metrics["stale_leakage"]["rate"] == pytest.approx(0.0)
    assert metrics["evidence"]["manual_relevance"]["evaluated_count"] == 0
    assert metrics["evidence"]["source_link_validity"]["evaluated_count"] == 0
    assert metrics["top_n_useful_rate"]["top_1"] is None
    assert metrics["cost_per_useful_insight"] is None


def test_unranked_predictions_do_not_fabricate_topn_or_cost(eval_harness_module, sample_posts, sample_labels):
    predictions = [
        {
            "post_id": "reddit:p1",
            "prediction_status": "classified",
            "is_pain": True,
            "is_monetizable": True,
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "opportunity_bucket": "current_opportunity",
            "verified_evidence": [{"quote": sample_posts[0].title, "match_type": "exact"}],
            "evidence_quality": "exact_quote",
        }
    ]

    metrics = eval_harness_module.evaluate_predictions(
        posts=sample_posts[:1],
        labels=sample_labels[:1],
        predictions=predictions,
        reference_now_ts=REFERENCE_NOW_TS,
    )

    assert metrics["pain"]["tp"] == 1
    assert metrics["top_n_useful_rate"]["top_1"] is None
    assert metrics["cost_per_useful_insight"] is None


def test_cluster_fragmentation_rate_is_bounded(eval_harness_module, sample_posts):
    labels = [
        _label(
            post.post_id,
            is_pain=True,
            is_monetizable=True,
            post_type="first_person_pain",
            is_current_opportunity=True,
            first_handness="first_hand",
            buyer_authority="manager",
            expected_cluster_key="same_problem",
            feedback_useful=True,
        )
        for post in sample_posts
    ]
    predictions = [
        {
            "post_id": post.post_id,
            "prediction_status": "classified",
            "is_pain": True,
            "is_monetizable": True,
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "manager",
            "opportunity_bucket": "current_opportunity",
            "verified_evidence": [{"quote": post.title, "match_type": "exact"}],
            "evidence_quality": "exact_quote",
            "cluster_key": f"split_{idx}",
        }
        for idx, post in enumerate(sample_posts)
    ]

    metrics = eval_harness_module.evaluate_predictions(
        posts=sample_posts,
        labels=labels,
        predictions=predictions,
        reference_now_ts=REFERENCE_NOW_TS,
    )

    assert metrics["clusters"]["duplicate_count"] == 2
    assert metrics["clusters"]["duplicate_rate"] == pytest.approx(0.667)


def test_evaluate_predictions_does_not_count_fuzzy_only_evidence_as_exact(eval_harness_module, sample_posts, sample_labels):
    predictions = [
        {
            "post_id": "reddit:p1",
            "prediction_status": "classified",
            "prescreen_score": 6,
            "is_pain": True,
            "is_monetizable": True,
            "post_type": "first_person_pain",
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "opportunity_bucket": "current_opportunity",
            "verified_evidence": [
                {"quote": "manual workflow is awful", "match_type": "fuzzy"},
                {"quote": "takes hours", "match_type": "fuzzy"},
            ],
            "evidence_quality": "multi_quote",
            "evidence_match_rate": 1.0,
            "confidence": 0.8,
        }
    ]

    metrics = eval_harness_module.evaluate_predictions(
        posts=sample_posts[:1],
        labels=sample_labels[:1],
        predictions=predictions,
        reference_now_ts=REFERENCE_NOW_TS,
    )

    assert metrics["evidence"]["coverage_count"] == 1
    assert metrics["evidence"]["exact_match_count"] == 0
    assert metrics["evidence"]["exact_match_rate"] == pytest.approx(0.0)


def test_feedback_events_convert_to_label_review_rows_without_full_labels(eval_harness_module, tmp_path):
    feedback_rows = [
        {
            "id": 10,
            "post_id": "reddit:p1",
            "feedback_value": "useful",
            "source": "telegram",
            "created_at": "2026-04-27T12:00:00+00:00",
        },
        {
            "id": 11,
            "post_id": "reddit:p2",
            "feedback_value": "too_generic",
            "source": "telegram",
            "created_at": "2026-04-27T12:01:00+00:00",
        },
        {
            "id": 12,
            "post_id": "reddit:p3",
            "feedback_value": "bad_evidence",
            "source": "telegram",
            "created_at": "2026-04-27T12:02:00+00:00",
        },
    ]
    pain_points_by_id = {
        "reddit:p1": {
            "post_id": "reddit:p1",
            "subreddit": "ops",
            "title": "Manual invoices",
            "body": "We still review invoices manually.",
            "url": "https://reddit.com/p1",
            "source": "reddit",
            "triage_status": "new",
            "evidence_quality": "exact_quote",
            "verified_evidence_json": json.dumps([{"quote": "review invoices manually", "match_type": "exact"}]),
            "opportunity_score": 88.0,
        },
        "reddit:p2": {
            "post_id": "reddit:p2",
            "subreddit": "ops",
            "title": "What tool should I use?",
            "body": "Looking for generic recommendations.",
            "url": "https://reddit.com/p2",
            "source": "reddit",
            "triage_status": "discarded",
            "evidence_quality": "no_quote",
            "verified_evidence_json": "[]",
            "opportunity_score": 0.0,
        },
    }

    review_rows = eval_harness_module.feedback_events_to_label_review_rows(
        feedback_rows,
        pain_points_by_id=pain_points_by_id,
    )

    assert [row["feedback_event_id"] for row in review_rows] == [10, 11, 12]
    assert review_rows[0]["review_type"] == "feedback_label_review"
    assert review_rows[0]["review_status"] == "pending"
    assert review_rows[0]["requires_human_review"] is True
    assert review_rows[0]["promotion_eligible"] is False
    assert review_rows[0]["label_suggestions"] == {"feedback_useful": True}
    assert review_rows[0]["source"]["verified_evidence"][0]["quote"] == "review invoices manually"
    assert "is_monetizable" not in review_rows[0]
    assert review_rows[1]["label_suggestions"] == {
        "feedback_useful": False,
        "hard_negative_type": "generic_recommendation",
    }
    assert review_rows[1]["source"]["triage_status"] == "discarded"
    assert review_rows[2]["label_suggestions"] == {
        "feedback_useful": False,
        "evidence_relevance": "irrelevant",
    }
    assert review_rows[2]["source"]["title"] == ""

    output_path = tmp_path / "feedback-label-review.jsonl"
    exported_rows = eval_harness_module.write_feedback_label_review_jsonl(
        output_path,
        feedback_rows,
        pain_points_by_id=pain_points_by_id,
    )
    written_rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert exported_rows == review_rows
    assert written_rows == review_rows


def test_feedback_events_reject_unknown_feedback_values(eval_harness_module):
    with pytest.raises(ValueError, match="feedback_value"):
        eval_harness_module.feedback_events_to_label_review_rows(
            [{"id": 1, "post_id": "reddit:p1", "feedback_value": "interesting"}],
            pain_points_by_id={},
        )


@pytest.mark.asyncio
async def test_generate_live_predictions_tracks_prescreener_and_bucket(eval_harness_module):
    fresh_post = Post(
        post_id="reddit:fresh",
        subreddit="ops",
        title="Manual approvals still block deals",
        body="Founder here and this still hurts every week.",
        url="https://reddit.com/fresh",
        score=10,
        source_created_at="2026-04-17T00:00:00+00:00",
        source_created_ts=1776384000,
    )
    stale_post = Post(
        post_id="reddit:stale",
        subreddit="ops",
        title="Any good newsletter for revops?",
        body="Just collecting links.",
        url="https://reddit.com/stale",
        score=2,
        source_created_at="2025-07-10T00:00:00+00:00",
        source_created_ts=1752105600,
    )
    signal = PainSignal(
        post=fresh_post,
        category="complaint",
        summary="Manual approvals keep blocking deals",
        severity="high",
        is_monetizable=True,
        pain_level=8,
        willingness_to_pay=8,
        niche_category="RevOps",
        analysis_mode="b2b",
        post_type="first_person_pain",
        first_handness="first_hand",
        buyer_authority="founder_owner",
        verified_evidence=[
            VerifiedEvidence(
                quote="Manual approvals still block deals",
                source_type="title",
                post_id="reddit:fresh",
                comment_id=None,
                permalink="https://reddit.com/fresh",
                match_type="exact",
                match_confidence=1.0,
                created_utc=1776384000,
            )
        ],
        evidence_quality="exact_quote",
        evidence_match_rate=1.0,
        confidence=0.88,
        uncertainty_reason="",
        needs_human_review=False,
    )

    class FakeClassifier:
        screen_min_rule_score = 2

        def prescreen_score(self, post):
            return 5 if post.post_id == "reddit:fresh" else 1

        def prescreen_posts(self, posts, *, max_candidates=None):
            assert [post.post_id for post in posts] == ["reddit:fresh", "reddit:stale"]
            assert max_candidates is None
            return [fresh_post], {"screen_rule_dropped_count": 1, "screen_kept_count": 1, "screen_capped_count": 0}

        async def classify_batch(self, posts):
            assert [post.post_id for post in posts] == ["reddit:fresh"]
            return [signal]

    predictions = await eval_harness_module.generate_live_predictions(
        posts=[fresh_post, stale_post],
        classifier=FakeClassifier(),
        reference_now_ts=REFERENCE_NOW_TS,
        current_opportunity_max_age_days=180,
    )

    assert [row["post_id"] for row in predictions] == ["reddit:fresh", "reddit:stale"]
    assert predictions[0]["prediction_status"] == "classified"
    assert predictions[0]["is_pain"] is True
    assert predictions[0]["opportunity_bucket"] == "current_opportunity"
    assert predictions[0]["prescreen_score"] == 5
    assert predictions[0]["verified_evidence"][0]["quote"] == "Manual approvals still block deals"
    assert predictions[0]["evidence_quality"] == "exact_quote"
    assert predictions[0]["evidence_match_rate"] == 1.0
    assert predictions[0]["confidence"] == 0.88
    assert predictions[0]["needs_human_review"] is False
    assert predictions[1]["prediction_status"] == "screened_out"
    assert predictions[1]["is_pain"] is False
    assert predictions[1]["opportunity_bucket"] == "evergreen_pain"
    assert predictions[1]["prescreen_score"] == 1
    assert predictions[1]["evidence_quality"] == "no_quote"
    assert predictions[1]["needs_human_review"] is False


def test_run_eval_offline_writes_artifacts(tmp_path, monkeypatch, capsys):
    dataset_path = tmp_path / "dataset.jsonl"
    labels_path = tmp_path / "labels.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    output_dir = tmp_path / "artifacts"

    _write_jsonl(
        dataset_path,
        [
            {
                "post_id": "reddit:p1",
                "subreddit": "ops",
                "title": "Invoices still require manual review",
                "body": "Founder here. This takes hours every week.",
                "url": "https://reddit.com/p1",
                "score": 12,
                "source_created_at": "2026-04-18T00:00:00+00:00",
                "source_created_ts": 1776470400,
            }
        ],
    )
    _write_jsonl(
        labels_path,
        [
            _label(
                "reddit:p1",
                is_pain=True,
                is_monetizable=True,
                post_type="first_person_pain",
                is_current_opportunity=True,
                first_handness="first_hand",
                buyer_authority="founder_owner",
                intensity_label="high",
                urgency_label="high",
                wtp_label="high",
                expected_cluster_key="invoice_reconciliation",
                feedback_useful=True,
            )
        ],
    )
    _write_jsonl(
        predictions_path,
        [
            {
                "post_id": "reddit:p1",
                "prediction_status": "classified",
                "prescreen_score": 5,
                "is_pain": True,
                "is_monetizable": True,
                "post_type": "first_person_pain",
                "first_handness": "first_hand",
                "buyer_authority": "founder_owner",
                "opportunity_bucket": "current_opportunity",
                "analysis_mode": "dspy_b2b",
                "verified_evidence": [
                    {
                        "quote": "This takes hours every week",
                        "source_type": "body",
                        "post_id": "reddit:p1",
                        "match_type": "exact",
                        "match_confidence": 1.0,
                    }
                ],
                "evidence_quality": "exact_quote",
                "evidence_match_rate": 1.0,
                "confidence": 0.9,
                "needs_human_review": False,
            }
        ],
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_eval.py",
            "--dataset",
            str(dataset_path),
            "--labels",
            str(labels_path),
            "--predictions-path",
            str(predictions_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    run_eval_path = Path(__file__).resolve().parents[1] / "eval" / "run_eval.py"
    runpy.run_path(str(run_eval_path), run_name="__main__")

    metrics_path = output_dir / "metrics.json"
    written_predictions_path = output_dir / "predictions.jsonl"
    assert metrics_path.exists()
    assert written_predictions_path.exists()

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["dataset_size"] == 1
    assert metrics["pain"]["precision"] == pytest.approx(1.0)
    assert metrics["stale_leakage"]["count"] == 0
    assert metrics["evidence"]["coverage_rate"] == pytest.approx(1.0)
    assert metrics["evidence"]["exact_match_rate"] == pytest.approx(1.0)

    stdout = capsys.readouterr().out
    assert "dataset_size=1" in stdout
    assert "pain_precision=1.000" in stdout
    assert "evidence_coverage=1.000" in stdout


def test_run_eval_offline_writes_baseline_artifacts(tmp_path, monkeypatch):
    dataset_path = tmp_path / "dataset.jsonl"
    labels_path = tmp_path / "labels.jsonl"
    current_predictions_path = tmp_path / "current.jsonl"
    rules_only_predictions_path = tmp_path / "rules_only.jsonl"
    output_dir = tmp_path / "baseline-artifacts"

    _write_jsonl(
        dataset_path,
        [
            {
                "post_id": "reddit:p1",
                "subreddit": "ops",
                "title": "Invoices still require manual review",
                "body": "Founder here. This takes hours every week.",
                "url": "https://reddit.com/p1",
                "score": 12,
                "source_created_at": "2026-04-18T00:00:00+00:00",
                "source_created_ts": 1776470400,
            }
        ],
    )
    _write_jsonl(
        labels_path,
        [
            _label(
                "reddit:p1",
                is_pain=True,
                is_monetizable=True,
                post_type="first_person_pain",
                is_current_opportunity=True,
                first_handness="first_hand",
                buyer_authority="founder_owner",
                expected_cluster_key="invoice_reconciliation",
                feedback_useful=True,
            )
        ],
    )
    current_prediction = {
        "post_id": "reddit:p1",
        "prediction_status": "classified",
        "prescreen_score": 5,
        "is_pain": True,
        "is_monetizable": True,
        "post_type": "first_person_pain",
        "first_handness": "first_hand",
        "buyer_authority": "founder_owner",
        "opportunity_bucket": "current_opportunity",
        "verified_evidence": [{"quote": "This takes hours every week", "match_type": "exact"}],
        "evidence_quality": "exact_quote",
        "evidence_match_rate": 1.0,
        "confidence": 0.9,
        "opportunity_score": 80,
        "cluster_key": "invoice_reconciliation_v1",
        "cost_usd": 0.04,
        "latency_ms": 500,
    }
    _write_jsonl(current_predictions_path, [current_prediction])
    _write_jsonl(rules_only_predictions_path, [{**current_prediction, "is_pain": False, "prediction_status": "screened_out"}])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_eval.py",
            "--dataset",
            str(dataset_path),
            "--labels",
            str(labels_path),
            "--baseline-predictions",
            f"current={current_predictions_path}",
            "--baseline-predictions",
            f"rules_only={rules_only_predictions_path}",
            "--output-dir",
            str(output_dir),
        ],
    )

    run_eval_path = Path(__file__).resolve().parents[1] / "eval" / "run_eval.py"
    runpy.run_path(str(run_eval_path), run_name="__main__")

    current_metrics = json.loads((output_dir / "current" / "metrics.json").read_text(encoding="utf-8"))
    rules_only_metrics = json.loads((output_dir / "rules_only" / "metrics.json").read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "baseline_summary.json").read_text(encoding="utf-8"))

    assert current_metrics["pain"]["recall"] == pytest.approx(1.0)
    assert rules_only_metrics["pain"]["recall"] == pytest.approx(0.0)
    assert summary["reference_baseline"] == "current"
    assert summary["baselines"]["current"]["metrics_path"] == "current/metrics.json"
    assert summary["baselines"]["rules_only"]["predictions_path"] == "rules_only/predictions.jsonl"
    assert summary["baselines"]["current"]["metrics"]["pain_recall"] == pytest.approx(1.0)
    assert summary["comparisons"]["rules_only_vs_current"]["pain_recall_delta"] == pytest.approx(-1.0)
    assert summary["comparisons"]["rules_only_vs_current"]["screening_false_negative_delta"] == 1
    assert summary["comparisons"]["rules_only_vs_current"]["evidence_exact_match_rate_delta"] == pytest.approx(-1.0)


def test_checked_in_seed_labels_include_expanded_hard_negatives(eval_harness_module):
    labels_path = Path(__file__).resolve().parents[1] / "eval" / "labels.jsonl"
    labels = eval_harness_module.labels_from_jsonl(labels_path)
    hard_negative_count = sum(1 for label in labels if label["hard_negative_type"] != "none")

    assert len(labels) >= 60
    assert hard_negative_count >= 50
    assert {"generic_recommendation", "b2c_consumer_rant", "founder_pitch", "news_analysis"}.issubset(
        {label["hard_negative_type"] for label in labels}
    )
    assert all("pain_type" in label and "evidence_quality" in label for label in labels)


def test_labels_schema_matches_expanded_taxonomy_contract(eval_harness_module):
    schema_path = Path(__file__).resolve().parents[1] / "eval" / "labels.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert set(schema["required"]) >= {
        "post_id",
        "is_pain",
        "is_monetizable",
        "post_type",
        "pain_type",
        "expression_type",
        "first_handness",
        "buyer_authority",
        "intensity_label",
        "urgency_label",
        "wtp_label",
        "current_workaround",
        "incumbent_failure",
        "evidence_quality",
        "evidence_expected",
        "opportunity_type",
        "is_current_opportunity",
        "hard_negative_type",
        "reference_now_ts",
    }
    properties = schema["properties"]
    assert set(properties["post_type"]["enum"]) == eval_harness_module.VALID_POST_TYPES - {"unclassified"}
    assert set(properties["pain_type"]["enum"]) == eval_harness_module.VALID_PAIN_TYPES
    assert set(properties["expression_type"]["enum"]) == eval_harness_module.VALID_EXPRESSION_TYPES
    assert set(properties["first_handness"]["enum"]) == eval_harness_module.VALID_FIRST_HANDNESS
    assert set(properties["buyer_authority"]["enum"]) == eval_harness_module.VALID_BUYER_AUTHORITY
    assert set(properties["intensity_label"]["enum"]) == eval_harness_module.VALID_LABEL_STRENGTHS
    assert set(properties["evidence_quality"]["enum"]) == eval_harness_module.VALID_EVIDENCE_QUALITY
    assert set(properties["opportunity_type"]["enum"]) == eval_harness_module.VALID_OPPORTUNITY_TYPES
    assert set(properties["hard_negative_type"]["enum"]) == eval_harness_module.VALID_HARD_NEGATIVE_TYPES
    assert set(properties["evidence_relevance"]["enum"]) == eval_harness_module.VALID_EVIDENCE_RELEVANCE
    assert set(properties["source_link_validity"]["enum"]) == eval_harness_module.VALID_SOURCE_LINK_VALIDITY
    assert properties["evidence_expected"]["type"] == "boolean"


def test_labels_from_jsonl_rejects_invalid_values(eval_harness_module, tmp_path):
    labels_path = tmp_path / "labels.jsonl"
    _write_jsonl(
        labels_path,
        [
            {
                **_label(
                    "reddit:bad",
                    is_pain=True,
                    is_monetizable=True,
                    post_type="first_person_pain",
                    is_current_opportunity=True,
                    first_handness="first_hand",
                    buyer_authority="founder_owner",
                ),
                "is_pain": "tru",
                "post_type": "first_person_paiin",
            }
        ],
    )

    with pytest.raises(ValueError, match="invalid"):
        eval_harness_module.labels_from_jsonl(labels_path)


def test_labels_from_jsonl_requires_expanded_taxonomy_fields(eval_harness_module, tmp_path):
    labels_path = tmp_path / "labels.jsonl"
    missing_pain_type = _label(
        "reddit:missing",
        is_pain=True,
        is_monetizable=True,
        post_type="first_person_pain",
        is_current_opportunity=True,
        first_handness="first_hand",
        buyer_authority="founder_owner",
    )
    missing_pain_type.pop("pain_type")
    _write_jsonl(labels_path, [missing_pain_type])

    with pytest.raises(ValueError, match="pain_type"):
        eval_harness_module.labels_from_jsonl(labels_path)

    valid_path = tmp_path / "valid-labels.jsonl"
    _write_jsonl(valid_path, [_label("reddit:valid", is_pain=True, is_monetizable=True, post_type="first_person_pain", is_current_opportunity=True, first_handness="first_hand", buyer_authority="founder_owner")])
    labels = eval_harness_module.labels_from_jsonl(valid_path)
    assert labels[0]["pain_type"] == "workflow"
    assert labels[0]["intensity_label"] == "medium"
    assert labels[0]["hard_negative_type"] == "none"


def test_evaluate_predictions_rejects_mixed_reference_now_ts(eval_harness_module, sample_posts, sample_predictions):
    labels = [
        _label(
            "reddit:p1",
            is_pain=True,
            is_monetizable=True,
            post_type="first_person_pain",
            is_current_opportunity=True,
            first_handness="first_hand",
            buyer_authority="founder_owner",
        ),
        {
            **_label(
                "reddit:p2",
                is_pain=False,
                is_monetizable=False,
                post_type="advice_thread",
                is_current_opportunity=False,
                first_handness="unknown",
                buyer_authority="unknown",
                pain_type="unknown",
                expression_type="unknown",
                intensity_label="none",
                urgency_label="none",
                wtp_label="none",
                current_workaround="",
                incumbent_failure="",
                evidence_quality="no_quote",
                opportunity_type="not_opportunity",
                hard_negative_type="generic_recommendation",
                expected_cluster_key="",
                evidence_relevance="not_applicable",
            ),
            "reference_now_ts": REFERENCE_NOW_TS + 86400,
        },
    ]

    with pytest.raises(ValueError, match="reference_now_ts"):
        eval_harness_module.evaluate_predictions(
            posts=sample_posts,
            labels=labels,
            predictions=sample_predictions,
        )


@pytest.mark.parametrize(
    ("posts", "label_rows", "prediction_rows", "expected_message"),
    [
        (
            [
                Post(
                    post_id="reddit:p1",
                    subreddit="ops",
                    title="dup one",
                    body="a",
                    url="https://reddit.com/p1a",
                    score=1,
                    source_created_at="2026-04-18T00:00:00+00:00",
                    source_created_ts=1776470400,
                ),
                Post(
                    post_id="reddit:p1",
                    subreddit="ops",
                    title="dup two",
                    body="b",
                    url="https://reddit.com/p1b",
                    score=2,
                    source_created_at="2026-04-19T00:00:00+00:00",
                    source_created_ts=1776556800,
                ),
            ],
            None,
            None,
            "duplicate post_id in posts",
        ),
        (
            None,
            [
                _label(
                    "reddit:p1",
                    is_pain=True,
                    is_monetizable=True,
                    post_type="first_person_pain",
                    is_current_opportunity=True,
                    first_handness="first_hand",
                    buyer_authority="founder_owner",
                ),
                _label(
                    "reddit:p1",
                    is_pain=False,
                    is_monetizable=False,
                    post_type="advice_thread",
                    is_current_opportunity=False,
                    first_handness="unknown",
                    buyer_authority="unknown",
                    pain_type="unknown",
                    expression_type="unknown",
                    intensity_label="none",
                    urgency_label="none",
                    wtp_label="none",
                    current_workaround="",
                    incumbent_failure="",
                    evidence_quality="no_quote",
                    opportunity_type="not_opportunity",
                    hard_negative_type="generic_recommendation",
                    expected_cluster_key="",
                    evidence_relevance="not_applicable",
                ),
            ],
            None,
            "duplicate label post_id",
        ),
        (
            None,
            None,
            [
                {
                    "post_id": "reddit:p1",
                    "prediction_status": "classified",
                    "prescreen_score": 6,
                    "is_pain": True,
                    "is_monetizable": True,
                    "post_type": "first_person_pain",
                    "first_handness": "first_hand",
                    "buyer_authority": "founder_owner",
                    "opportunity_bucket": "current_opportunity",
                    "analysis_mode": "dspy_b2b",
                },
                {
                    "post_id": "reddit:p1",
                    "prediction_status": "classified",
                    "prescreen_score": 3,
                    "is_pain": False,
                    "is_monetizable": False,
                    "post_type": "advice_thread",
                    "first_handness": "unknown",
                    "buyer_authority": "unknown",
                    "opportunity_bucket": "evergreen_pain",
                    "analysis_mode": "legacy_llm",
                },
            ],
            "duplicate prediction post_id",
        ),
    ],
)
def test_evaluate_predictions_rejects_duplicate_post_ids(
    eval_harness_module,
    sample_posts,
    sample_labels,
    sample_predictions,
    posts,
    label_rows,
    prediction_rows,
    expected_message,
):
    with pytest.raises(ValueError, match=expected_message):
        eval_harness_module.evaluate_predictions(
            posts=posts or sample_posts,
            labels=label_rows or sample_labels,
            predictions=prediction_rows or sample_predictions,
            reference_now_ts=REFERENCE_NOW_TS,
        )
