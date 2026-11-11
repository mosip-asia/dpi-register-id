import pytest
from register_id.liveness import evaluate_liveness
from register_id.models import LivenessRequest


def test_evaluate_liveness_success():
    req = LivenessRequest(
        blinkCount=2,
        minEar=0.18,
        maxEar=0.32,
        durationMs=3500.0,
    )
    res = evaluate_liveness(req)
    assert res.status == "PASSED"
    assert res.livenessScore >= 80.0
    assert "Human liveness verified" in res.message


def test_evaluate_liveness_static_spoof():
    req = LivenessRequest(
        blinkCount=0,
        minEar=0.29,
        maxEar=0.30,
        durationMs=4000.0,
    )
    res = evaluate_liveness(req)
    assert res.status == "FAILED"
    assert res.livenessScore == 12.0
    assert "Spoof Detected" in res.message
