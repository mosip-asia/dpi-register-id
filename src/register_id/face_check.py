"""
Capture and probe gates for register-id.

Identity matching is not implemented. The embedder that actually runs hashes
JPEG bytes. It can report a duplicate payload. It cannot decide that two
different photos are the same person, and no landmark model is loaded, so
head turn and liveness are not measured from pixels.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from register_id.embedder import ENGINE_NAME

_NOT_A_FACE_ENGINE = frozenset({"", "hash"})


@dataclass(frozen=True)
class CaptureAssessment:
    yaw_measured: bool
    yaw_degrees: list[float] | None
    presentation_passed: bool
    presentation_detail: str


@dataclass(frozen=True)
class MatchAssessment:
    is_face_match: bool
    distance: float | None
    score: float | None
    threshold: float | None
    engine: str
    duplicate_of_stored: bool


def engine_can_identify_face() -> bool:
    """Return whether the configured engine is claimed to identify a face.

    Unset, blank, and ``hash`` return False. Any other FACE_ENGINE name
    returns True. Naming an engine does not load a model.
    """
    configured = os.environ.get("FACE_ENGINE")
    if configured is None:
        return False
    name = configured.strip().lower()
    if name in _NOT_A_FACE_ENGINE or name == ENGINE_NAME:
        return False
    return True


def estimate_yaw_degrees(images: Sequence[object]) -> list[float] | None:
    """Estimate head yaw from pixels.

    No landmark model is loaded, so this always returns None.
    """
    _ = images
    return None


def assess_capture(
    images: Sequence[object],
    client_yaws: Sequence[float] | None,
) -> CaptureAssessment:
    """Assess a capture on the server.

    ``client_yaws`` is whatever the browser sent. It is not copied into
    ``yaw_degrees`` and it does not set ``yaw_measured``.
    """
    _ = client_yaws
    measured = estimate_yaw_degrees(images)
    return CaptureAssessment(
        yaw_measured=measured is not None,
        yaw_degrees=None if measured is None else list(measured),
        presentation_passed=False,
        presentation_detail=(
            "The server did not measure the head turn or liveness from the pixels."
        ),
    )


def _same_vector(left: Sequence[float], right: Sequence[float]) -> bool:
    if len(left) != len(right):
        return False
    return all(a == b for a, b in zip(left, right, strict=True))


def compare_probe(
    stored_vectors: Sequence[Sequence[float]],
    probe_vector: Sequence[float],
) -> MatchAssessment:
    """Compare a probe vector with stored vectors.

    Identity matching is not implemented. The hash embedder may set
    ``duplicate_of_stored`` when the probe vector equals a stored vector.
    That flag is a duplicate-byte check. It does not set ``is_face_match``,
    and this function does not invent a distance or a passing score.
    """
    duplicate = any(_same_vector(stored, probe_vector) for stored in stored_vectors)
    # The process that ran is the hash embedder, including when FACE_ENGINE
    # names something else. No face model is loaded, so there is no score.
    return MatchAssessment(
        is_face_match=False,
        distance=None,
        score=None,
        threshold=None,
        engine="hash",
        duplicate_of_stored=duplicate,
    )


def may_store_biometric_record(
    presentation_passed: bool,
    engine_can_identify: bool,
) -> bool:
    """Allow storage only when presentation passed and the engine can identify a face."""
    return presentation_passed is True and engine_can_identify is True
