import base64
import time

from register_id.models import FaceViewSample
from register_id.sweep import _CHALLENGES, assess_sweep, create_sweep_challenge, estimate_yaw_from_image


def _views() -> list[FaceViewSample]:
    samples = [
        ("far-left", -0.8, b"far-left"),
        ("left", -0.4, b"left"),
        ("front", 0.0, b"front"),
        ("right", 0.4, b"right"),
        ("far-right", 0.8, b"far-right"),
    ]
    return [
        FaceViewSample(
            sector=sector,
            yaw=yaw,
            image="data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii"),
        )
        for sector, yaw, payload in samples
    ]


def test_estimate_yaw_is_unavailable_without_a_face_model():
    assert estimate_yaw_from_image("data:image/jpeg;base64,aaaa") is None


def test_sweep_challenge_expires_and_does_not_claim_liveness():
    challenge = create_sweep_challenge()
    _CHALLENGES[challenge.challengeId]["expiresAt"] = time.time() - 1
    result = assess_sweep(challenge.challengeId, _views())
    assert result.accepted is False
    assert "expired" in result.message


def test_sweep_accepts_distinct_ordered_images_without_calling_it_liveness():
    challenge = create_sweep_challenge()
    result = assess_sweep(challenge.challengeId, _views())
    assert result.accepted is True
    assert result.yaw_source == "client"
    assert "does not show a live head turn" in result.message
