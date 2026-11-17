"""
Head-sweep submission check.

A passing sweep means five different images arrived with client yaw labels in
left-to-right order, inside an unexpired single-use challenge. It does not
estimate yaw from pixels and it does not compare identity.
"""

import secrets
import time
from dataclasses import dataclass

from register_id.challenge_store import get_challenge_store, in_memory_records
from register_id.embedder import embed_face_image
from register_id.matcher import compute_euclidean_distance
from register_id.models import FACE_VIEW_SECTORS, FaceViewSample, SweepChallenge

SWEEP_TTL_SECONDS = 90
MIN_YAW_STEP = 0.08
MIN_IMAGE_DISTANCE = 0.05

# Same dict the memory store uses. Tests force expiry by writing expiresAt
# here when REDIS_URL is unset. A configured Redis store does not read it.
_CHALLENGES = in_memory_records()


@dataclass(frozen=True)
class SweepAssessment:
    accepted: bool
    message: str
    yaw_source: str


def estimate_yaw_from_image(image: str) -> float | None:
    """
    Yaw from the image itself.

    No landmark model is wired in, so this always returns None. Callers must
    not treat client-supplied yaw as a measurement from the pixels.
    """
    del image
    return None


def create_sweep_challenge() -> SweepChallenge:
    now = time.time()
    challenge_id = f"sweep_{secrets.token_hex(8)}"
    get_challenge_store().issue(
        challenge_id,
        {"createdAt": now},
        SWEEP_TTL_SECONDS,
        now=now,
    )
    return SweepChallenge(
        challengeId=challenge_id,
        timeLimitSeconds=SWEEP_TTL_SECONDS,
        prompt=(
            "Turn your head from your left shoulder to your right. "
            f"Finish within {SWEEP_TTL_SECONDS} seconds."
        ),
        createdAt=now,
    )


def _consume(challenge_id: str | None, now: float) -> str | None:
    if not challenge_id:
        return "Sweep rejected: missing challenge."
    result = get_challenge_store().consume(challenge_id, now=now)
    if result.reason == "expired":
        return "Sweep rejected: challenge expired. Start the camera again."
    if not result.ok:
        return "Sweep rejected: unknown or already used challenge."
    return None


def _yaw_order(views: list[FaceViewSample]) -> str | None:
    by_sector = {sample.sector: sample.yaw for sample in views}
    yaws = [by_sector[sector] for sector in FACE_VIEW_SECTORS]
    for earlier, later in zip(yaws, yaws[1:]):
        if later < earlier + MIN_YAW_STEP:
            return (
                "Sweep rejected: client yaw is not a left-to-right sequence. "
                "Yaw was not estimated from the image pixels."
            )
    return None


def _distinct_images(views: list[FaceViewSample]) -> str | None:
    by_sector = {sample.sector: embed_face_image(sample.image) for sample in views}
    sectors = list(FACE_VIEW_SECTORS)
    for index, left in enumerate(sectors):
        for right in sectors[index + 1 :]:
            distance = compute_euclidean_distance(by_sector[left], by_sector[right])
            if distance < MIN_IMAGE_DISTANCE:
                return (
                    "Sweep rejected: the five images are not distinct. "
                    "The same picture was submitted for more than one pose."
                )
    return None


def assess_sweep(
    challenge_id: str | None,
    views: list[FaceViewSample] | None,
    now: float | None = None,
) -> SweepAssessment:
    """
    Accept a sweep submission or explain why it was rejected.

    Server-side yaw is attempted and, while it is unavailable, client yaw is
    used only as a label-order check. Acceptance is not a liveness result.
    """
    if not views:
        return SweepAssessment(
            accepted=False,
            message=(
                "Head sweep required: submit liveViews covering far-left, left, "
                "front, right, and far-right."
            ),
            yaw_source="none",
        )

    clock = time.time() if now is None else now
    challenge_error = _consume(challenge_id, clock)
    if challenge_error:
        return SweepAssessment(accepted=False, message=challenge_error, yaw_source="none")

    server_yaws = [estimate_yaw_from_image(sample.image) for sample in views]
    yaw_source = "server" if all(yaw is not None for yaw in server_yaws) else "client"
    if yaw_source == "server":
        measured = [
            FaceViewSample(sector=sample.sector, yaw=yaw, image=sample.image)
            for sample, yaw in zip(views, server_yaws)
        ]
        order_error = _yaw_order(measured)
    else:
        order_error = _yaw_order(views)
    if order_error:
        return SweepAssessment(accepted=False, message=order_error, yaw_source=yaw_source)

    try:
        distinct_error = _distinct_images(views)
    except ValueError as exc:
        return SweepAssessment(accepted=False, message=str(exc), yaw_source=yaw_source)
    if distinct_error:
        return SweepAssessment(accepted=False, message=distinct_error, yaw_source=yaw_source)

    if yaw_source == "client":
        message = (
            "Sweep submission accepted: five distinct images with client yaw in "
            "left-to-right order. Yaw was not estimated from the image pixels, "
            "so this does not show a live head turn. Identity was not compared; "
            "no face model is configured."
        )
    else:
        message = (
            "Sweep submission accepted from server-estimated yaw. "
            "Identity was not compared; no face model is configured."
        )
    return SweepAssessment(accepted=True, message=message, yaw_source=yaw_source)
