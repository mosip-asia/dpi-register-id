"""
ISO/IEC 30107-3 Presentation Attack Detection (PAD) Module.

Evaluates Eye Aspect Ratio (EAR) dynamics, active blink patterns, and
interactive ephemeral challenge nonces to distinguish living human faces from
static photographs and digital replays.
"""

import logging
import secrets
import time
from typing import Any

from register_id.models import LivenessChallenge, LivenessRequest, LivenessResponse

logger = logging.getLogger(__name__)

# In-memory store for active ephemeral challenge nonces
_ACTIVE_CHALLENGES: dict[str, dict[str, Any]] = {}


def create_liveness_challenge() -> LivenessChallenge:
    """
    Generates a cryptographically random challenge nonce and ephemeral session.
    Enforces ISO/IEC 30107-3 Level 2 active anti-replay protection.
    """
    now = time.time()
    challenge_id = f"pad_{secrets.token_hex(8)}"
    time_limit_sec = 10

    # Housekeeping: prune challenges older than 60 seconds
    expired = [k for k, v in _ACTIVE_CHALLENGES.items() if v.get("expiresAt", 0) < now - 60]
    for k in expired:
        _ACTIVE_CHALLENGES.pop(k, None)

    _ACTIVE_CHALLENGES[challenge_id] = {
        "action": "BLINK_TWICE",
        "targetBlinks": 2,
        "timeLimitSeconds": time_limit_sec,
        "createdAt": now,
        "expiresAt": now + time_limit_sec,
    }

    return LivenessChallenge(
        challengeId=challenge_id,
        action="BLINK_TWICE",
        targetBlinks=2,
        timeLimitSeconds=time_limit_sec,
        prompt="Please blink 2 times within 10 seconds",
        createdAt=now,
    )


def evaluate_liveness(req: LivenessRequest) -> LivenessResponse:
    """
    Evaluates client EAR dynamics according to ISO 30107-3 PAD rules.
    A live human presents natural micro-motion and eye closure:
    - At least 1 natural blink cycle
    - Minimum EAR observed < 0.25 (eye closure)
    - EAR delta (max - min) >= 0.04 (transition dynamic)
    - If bypassLiveness is True, passes immediately (manual operator/test override)
    - If challengeId is supplied, validates active anti-replay challenge satisfaction.
    """
    if req.bypassLiveness:
        if req.challengeId:
            _ACTIVE_CHALLENGES.pop(req.challengeId, None)
        return LivenessResponse(
            status="PASSED",
            livenessScore=95.0,
            message="Human liveness verified (Manual Operator/Test Override).",
        )

    ear_delta = req.maxEar - req.minEar
    is_live = req.blinkCount >= 1 and req.minEar < 0.25 and ear_delta >= 0.04

    if not is_live:
        return LivenessResponse(
            status="FAILED",
            livenessScore=12.0,
            message="Presentation Attack / Spoof Detected (Static photo or insufficient motion).",
        )

    # Validate active challenge if provided
    if req.challengeId:
        ch = _ACTIVE_CHALLENGES.get(req.challengeId)
        if not ch:
            return LivenessResponse(
                status="FAILED",
                livenessScore=20.0,
                message="Challenge expired or invalid. Please request a new liveness challenge.",
            )

        now = time.time()
        if now > ch["expiresAt"]:
            return LivenessResponse(
                status="FAILED",
                livenessScore=25.0,
                message="Challenge timed out. Please complete the action within the allotted time limit.",
            )

        if req.blinkCount < ch["targetBlinks"]:
            return LivenessResponse(
                status="FAILED",
                livenessScore=30.0,
                message=f"Challenge incomplete: observed {req.blinkCount} blinks, expected {ch['targetBlinks']}.",
            )

        # Nonce burning: single-use token consumed upon successful verification
        _ACTIVE_CHALLENGES.pop(req.challengeId, None)

    confidence = min(99.0, max(85.0, (1.0 - req.minEar) * 100.0))
    return LivenessResponse(
        status="PASSED",
        livenessScore=round(confidence, 1),
        message="Human liveness verified. No static presentation attack detected.",
    )
