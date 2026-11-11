import time
import pytest
from register_id.liveness import create_liveness_challenge, evaluate_liveness
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


def test_liveness_challenge_verification_and_nonce_burning():
    challenge = create_liveness_challenge()
    assert challenge.challengeId.startswith("pad_")
    assert challenge.targetBlinks == 2

    # 1. Successful challenge satisfaction
    req = LivenessRequest(
        challengeId=challenge.challengeId,
        blinkCount=2,
        minEar=0.18,
        maxEar=0.30,
        durationMs=2500.0,
    )
    res = evaluate_liveness(req)
    assert res.status == "PASSED"
    assert res.livenessScore >= 80.0

    # 2. Replay attack attempt: reusing the burned challenge nonce must fail
    replay_res = evaluate_liveness(req)
    assert replay_res.status == "FAILED"
    assert "Challenge expired or invalid" in replay_res.message


def test_liveness_challenge_insufficient_blinks():
    challenge = create_liveness_challenge()
    req = LivenessRequest(
        challengeId=challenge.challengeId,
        blinkCount=1,  # expected 2
        minEar=0.18,
        maxEar=0.30,
        durationMs=2500.0,
    )
    res = evaluate_liveness(req)
    assert res.status == "FAILED"
    assert "Challenge incomplete" in res.message


def test_evaluate_liveness_bypass():
    challenge = create_liveness_challenge()
    req = LivenessRequest(
        challengeId=challenge.challengeId,
        blinkCount=0,
        minEar=0.30,
        maxEar=0.30,
        durationMs=1000.0,
        bypassLiveness=True,
    )
    res = evaluate_liveness(req)
    assert res.status == "PASSED"
    assert res.livenessScore == 95.0
    assert "Manual Operator/Test Override" in res.message
