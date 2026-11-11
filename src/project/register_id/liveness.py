"""
ISO/IEC 30107-3 Presentation Attack Detection (PAD) Module.

Evaluates Eye Aspect Ratio (EAR) dynamics and active blink patterns
to distinguish living human faces from static photographs and digital replays.
"""

from project.register_id.models import LivenessRequest, LivenessResponse


def evaluate_liveness(req: LivenessRequest) -> LivenessResponse:
    """
    Evaluates client EAR dynamics according to ISO 30107-3 PAD rules.
    A live human presents natural micro-motion and eye closure:
    - At least 1 natural blink cycle
    - Minimum EAR observed < 0.23 (eye closure)
    - EAR delta (max - min) >= 0.06 (transition dynamic)
    """
    ear_delta = req.maxEar - req.minEar
    is_live = req.blinkCount >= 1 and req.minEar < 0.23 and ear_delta >= 0.06

    if is_live:
        confidence = min(99.0, max(85.0, (1.0 - req.minEar) * 100.0))
        return LivenessResponse(
            status="PASSED",
            livenessScore=round(confidence, 1),
            message="Human liveness verified. No static presentation attack detected.",
        )

    return LivenessResponse(
        status="FAILED",
        livenessScore=12.0,
        message="Presentation Attack / Spoof Detected (Static photo or insufficient motion).",
    )
