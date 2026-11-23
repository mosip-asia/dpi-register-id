"""
Browser face-descriptor path.

The citizen portal runs @vladmandic/face-api in the browser and sends 128-D
descriptors plus liveness evidence (five head-turn yaws).
The server binds that evidence to a single-use challenge, checks it, stores
descriptors as templates, and does the 1:1 comparison itself.

Liveness on this path is the head sweep reported by the browser. The server
checks that the reported yaw steps left to right. It does not measure yaw
from the pixels, and it does not require a blink.
"""

from __future__ import annotations

import math
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from register_id.challenge_store import get_challenge_store
from register_id.matcher import compute_euclidean_distance
from register_id.models import FACE_VIEW_SECTORS, ClientLiveness, FaceChallenge
from register_id.sweep import MIN_YAW_STEP

FACE_DESCRIPTOR_ENGINE = "face-api-128"
DESCRIPTOR_LENGTH = 128
DESCRIPTOR_MAX_ABS = 2.0
DESCRIPTOR_MATCH_THRESHOLD = 0.5
DESCRIPTOR_CONSISTENCY_LIMIT = 0.6
MIN_BLINKS = 0
MIN_YAW_SPAN = 0.5

FACE_CHALLENGE_TTL_SECONDS = {"enroll": 300, "check": 120}

Purpose = Literal["enroll", "check"]


@dataclass(frozen=True)
class ClientLivenessAssessment:
    ok: bool
    message: str
    source: str = "client"


def validate_descriptor(values: Sequence[float], label: str = "Face descriptor") -> list[float]:
    """Return the descriptor as floats, or raise ValueError with a plain message."""
    if len(values) != DESCRIPTOR_LENGTH:
        raise ValueError(f"{label} must have {DESCRIPTOR_LENGTH} values, not {len(values)}.")
    cleaned = []
    for value in values:
        number = float(value)
        if not math.isfinite(number) or abs(number) > DESCRIPTOR_MAX_ABS:
            raise ValueError(
                f"{label} has a value that is not a finite number within ±{DESCRIPTOR_MAX_ABS}."
            )
        cleaned.append(number)
    return cleaned


def descriptors_consistent(descriptors: Sequence[Sequence[float]]) -> bool:
    """True when every pair of descriptors is within DESCRIPTOR_CONSISTENCY_LIMIT."""
    for index, left in enumerate(descriptors):
        for right in descriptors[index + 1 :]:
            if compute_euclidean_distance(list(left), list(right)) > DESCRIPTOR_CONSISTENCY_LIMIT:
                return False
    return True


def create_face_challenge(purpose: Purpose, now: float | None = None) -> FaceChallenge:
    clock = time.time() if now is None else now
    ttl = FACE_CHALLENGE_TTL_SECONDS[purpose]
    challenge_id = f"face_{secrets.token_hex(8)}"
    get_challenge_store().issue(
        challenge_id,
        {"kind": "face", "purpose": purpose, "createdAt": clock},
        ttl,
        now=clock,
    )
    return FaceChallenge(
        challengeId=challenge_id,
        purpose=purpose,
        expiresInSeconds=ttl,
        requiredBlinks=MIN_BLINKS,
        sectors=list(FACE_VIEW_SECTORS),
    )


def _fail(message: str) -> ClientLivenessAssessment:
    return ClientLivenessAssessment(ok=False, message=message)


def assess_client_liveness(
    liveness: ClientLiveness,
    purpose: Purpose,
    now: float | None = None,
) -> ClientLivenessAssessment:
    """
    Consume the challenge, then check the browser-reported head sweep.

    The challenge is consumed before any other check, so a failed attempt
    cannot be retried with the same id.
    """
    clock = time.time() if now is None else now
    result = get_challenge_store().consume(liveness.challengeId, now=clock)
    if result.reason == "expired":
        return _fail("Liveness not accepted: the challenge expired. Start the camera again.")
    if not result.ok or result.record is None:
        return _fail(
            "Liveness not accepted: unknown or already used challenge. Start the camera again."
        )
    issued_for = result.record.get("purpose")
    if result.record.get("kind") != "face" or issued_for != purpose:
        return _fail(
            f"Liveness not accepted: this challenge was not issued for {purpose}. "
            "Start the camera again."
        )

    yaws = liveness.sweepYaws
    for earlier, later in zip(yaws, yaws[1:]):
        if later < earlier + MIN_YAW_STEP:
            return _fail(
                "Head turn not accepted: the browser reported yaw that does not step "
                "left to right."
            )

    span = yaws[-1] - yaws[0]
    if span < MIN_YAW_SPAN:
        return _fail(
            f"Head turn not accepted: the browser reported a turn of {span:.2f}; "
            f"at least {MIN_YAW_SPAN:.2f} is required."
        )

    return ClientLivenessAssessment(
        ok=True,
        message=(
            "Liveness accepted as a head sweep reported by the browser. "
            "The server did not measure the turn from the pixels."
        ),
    )
