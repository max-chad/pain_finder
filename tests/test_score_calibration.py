import json

from eval.calibrate_score import CALIBRATION_WEIGHT_KEYS, calibrate_from_files, score_prediction
from eval_harness import write_jsonl


def _prediction(post_id, *, useful_factor, monetizable_factor, evidence_count, penalty=0.0):
    return {
        "post_id": post_id,
        "score_components": {
            "factors": {
                "intensity": useful_factor,
                "frequency": useful_factor,
                "wtp": monetizable_factor,
                "buyer_authority": monetizable_factor,
                "current_workaround": useful_factor,
                "incumbent_failure": useful_factor,
                "urgency": useful_factor,
                "evidence_quality": 1.0 if evidence_count else 0.0,
                "recency": 0.8,
            },
            "penalties": {"noise": penalty},
            "exact_evidence_count": evidence_count,
        },
    }


def test_score_prediction_uses_weights_and_penalties():
    weights = {key: 1 / len(CALIBRATION_WEIGHT_KEYS) for key in CALIBRATION_WEIGHT_KEYS}
    clean = _prediction("clean", useful_factor=1.0, monetizable_factor=1.0, evidence_count=1)
    noisy = _prediction("noisy", useful_factor=1.0, monetizable_factor=1.0, evidence_count=1, penalty=0.4)

    assert score_prediction(clean, weights) > score_prediction(noisy, weights)


def test_calibrate_score_writes_deterministic_non_auto_apply_artifact(tmp_path):
    labels_path = tmp_path / "labels.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    output_path = tmp_path / "calibration.json"
    labels = [
        {"post_id": "p1", "is_monetizable": True, "feedback_useful": True, "evidence_quality": "exact_quote"},
        {"post_id": "p2", "is_monetizable": False, "feedback_useful": False, "evidence_quality": "none"},
    ]
    predictions = [
        _prediction("p1", useful_factor=0.95, monetizable_factor=0.90, evidence_count=1),
        _prediction("p2", useful_factor=0.70, monetizable_factor=0.10, evidence_count=0, penalty=0.35),
    ]
    write_jsonl(labels_path, labels)
    write_jsonl(predictions_path, predictions)

    artifact = calibrate_from_files(labels_path=labels_path, predictions_path=predictions_path, output_path=output_path, top_n=2)

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written == artifact
    assert written["auto_apply"] is False
    assert set(written["recommended_weights"]) == set(CALIBRATION_WEIGHT_KEYS)
    assert written["metric_summary"]["monetizable_precision"] == 0.5
    assert written["metric_summary"]["evidence_exact_match_rate"] == 1.0
