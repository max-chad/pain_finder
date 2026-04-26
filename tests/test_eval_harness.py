import json
import runpy
import sys
from pathlib import Path

import pytest

from classifier import PainSignal
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
        {
            "post_id": "reddit:p1",
            "is_pain": True,
            "is_monetizable": True,
            "post_type": "first_person_pain",
            "is_current_opportunity": True,
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "reference_now_ts": REFERENCE_NOW_TS,
        },
        {
            "post_id": "reddit:p2",
            "is_pain": False,
            "is_monetizable": False,
            "post_type": "advice_thread",
            "is_current_opportunity": False,
            "first_handness": "unknown",
            "buyer_authority": "unknown",
            "reference_now_ts": REFERENCE_NOW_TS,
        },
        {
            "post_id": "reddit:p3",
            "is_pain": True,
            "is_monetizable": False,
            "post_type": "vendor_rant",
            "is_current_opportunity": False,
            "first_handness": "first_hand",
            "buyer_authority": "manager",
            "reference_now_ts": REFERENCE_NOW_TS,
        },
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
        },
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


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
    assert metrics["stale_leakage"]["count"] == 1
    assert metrics["stale_leakage"]["rate"] == pytest.approx(0.5)
    assert metrics["screening_false_negative_count"] == 1
    assert metrics["screening_false_negative_post_ids"] == ["reddit:p3"]
    assert metrics["post_type_confusion"]["vendor_rant"]["unclassified"] == 1
    assert metrics["first_handness_accuracy"] == pytest.approx(0.667)
    assert metrics["buyer_authority_accuracy"] == pytest.approx(0.667)


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
    )

    class FakeClassifier:
        screen_min_rule_score = 2

        def prescreen_score(self, post):
            return 5 if post.post_id == "reddit:fresh" else 1

        async def classify_batch(self, posts):
            assert [post.post_id for post in posts] == ["reddit:fresh", "reddit:stale"]
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
    assert predictions[1]["prediction_status"] == "screened_out"
    assert predictions[1]["is_pain"] is False
    assert predictions[1]["opportunity_bucket"] == "evergreen_pain"
    assert predictions[1]["prescreen_score"] == 1


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
            {
                "post_id": "reddit:p1",
                "is_pain": True,
                "is_monetizable": True,
                "post_type": "first_person_pain",
                "is_current_opportunity": True,
                "first_handness": "first_hand",
                "buyer_authority": "founder_owner",
                "reference_now_ts": REFERENCE_NOW_TS,
            }
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

    runpy.run_path("/opt/repos/pain_finder/eval/run_eval.py", run_name="__main__")

    metrics_path = output_dir / "metrics.json"
    written_predictions_path = output_dir / "predictions.jsonl"
    assert metrics_path.exists()
    assert written_predictions_path.exists()

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["dataset_size"] == 1
    assert metrics["pain"]["precision"] == pytest.approx(1.0)
    assert metrics["stale_leakage"]["count"] == 0

    stdout = capsys.readouterr().out
    assert "dataset_size=1" in stdout
    assert "pain_precision=1.000" in stdout


def test_labels_from_jsonl_rejects_invalid_values(eval_harness_module, tmp_path):
    labels_path = tmp_path / "labels.jsonl"
    _write_jsonl(
        labels_path,
        [
            {
                "post_id": "reddit:bad",
                "is_pain": "tru",
                "is_monetizable": True,
                "post_type": "first_person_paiin",
                "is_current_opportunity": True,
                "first_handness": "first_hand",
                "buyer_authority": "founder_owner",
                "reference_now_ts": REFERENCE_NOW_TS,
            }
        ],
    )

    with pytest.raises(ValueError, match="invalid"):
        eval_harness_module.labels_from_jsonl(labels_path)


def test_evaluate_predictions_rejects_mixed_reference_now_ts(eval_harness_module, sample_posts, sample_predictions):
    labels = [
        {
            "post_id": "reddit:p1",
            "is_pain": True,
            "is_monetizable": True,
            "post_type": "first_person_pain",
            "is_current_opportunity": True,
            "first_handness": "first_hand",
            "buyer_authority": "founder_owner",
            "reference_now_ts": REFERENCE_NOW_TS,
        },
        {
            "post_id": "reddit:p2",
            "is_pain": False,
            "is_monetizable": False,
            "post_type": "advice_thread",
            "is_current_opportunity": False,
            "first_handness": "unknown",
            "buyer_authority": "unknown",
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
                {
                    "post_id": "reddit:p1",
                    "is_pain": True,
                    "is_monetizable": True,
                    "post_type": "first_person_pain",
                    "is_current_opportunity": True,
                    "first_handness": "first_hand",
                    "buyer_authority": "founder_owner",
                    "reference_now_ts": REFERENCE_NOW_TS,
                },
                {
                    "post_id": "reddit:p1",
                    "is_pain": False,
                    "is_monetizable": False,
                    "post_type": "advice_thread",
                    "is_current_opportunity": False,
                    "first_handness": "unknown",
                    "buyer_authority": "unknown",
                    "reference_now_ts": REFERENCE_NOW_TS,
                },
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
