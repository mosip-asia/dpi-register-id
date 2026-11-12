"""
Pydantic data models for the register_id submodule.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LivenessChallenge(BaseModel):
    challengeId: str = Field(..., description="Unique nonce identifier for this liveness session")
    action: str = Field(default="BLINK_TWICE", description="Requested interactive anti-replay action")
    targetBlinks: int = Field(default=2, description="Number of blinks required")
    timeLimitSeconds: int = Field(default=10, description="Validity window for the challenge in seconds")
    prompt: str = Field(default="Please blink 2 times within 10 seconds", description="User guidance prompt")
    createdAt: float = Field(..., description="Timestamp of challenge issuance")


class SweepChallenge(BaseModel):
    challengeId: str
    action: str = "HEAD_SWEEP"
    sectors: list[str] = Field(
        default_factory=lambda: ["far-left", "left", "front", "right", "far-right"]
    )
    timeLimitSeconds: int = 90
    prompt: str
    createdAt: float


class LivenessRequest(BaseModel):
    challengeId: str | None = Field(default=None, description="Optional active challenge nonce")
    blinkCount: int = Field(..., ge=0, description="Observed natural blink count")
    minEar: float = Field(..., ge=0.0, le=1.0, description="Minimum Eye Aspect Ratio observed")
    maxEar: float = Field(..., ge=0.0, le=1.0, description="Maximum Eye Aspect Ratio observed")
    durationMs: float = Field(..., ge=0.0, description="Liveness tracking duration in milliseconds")
    bypassLiveness: bool = Field(default=False, description="Manual test override to bypass blink requirement")


class LivenessResponse(BaseModel):
    status: str
    isoStandard: str = "ISO/IEC 30107-3 (PAD Level 1/2)"
    livenessScore: float
    padMethod: str = "Active Eye Aspect Ratio (EAR) & Blink Micro-Dynamics"
    message: str


FACE_VIEW_SECTORS = ("far-left", "left", "front", "right", "far-right")


class FaceViewSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sector: Literal["far-left", "left", "front", "right", "far-right"]
    # Subject-relative yaw from the jaw/nose ratio. Negative is the subject's left.
    yaw: float
    image: str = Field(..., min_length=1, description="Face image as a data URL or base64 string")


def validate_face_views(views: list[FaceViewSample] | None) -> list[FaceViewSample] | None:
    """
    Yaw and sector sanity for a head-sweep gallery.
    None means the caller is on the legacy single-image path.
    """
    if views is None:
        return None

    sectors = [sample.sector for sample in views]
    if len(sectors) != 5 or set(sectors) != set(FACE_VIEW_SECTORS):
        raise ValueError(
            "views must contain exactly one sample for each sector: "
            "far-left, left, front, right, far-right"
        )

    by_sector = {sample.sector: sample for sample in views}
    for sample in views:
        if not sample.image or not sample.image.strip():
            raise ValueError(f"image for sector '{sample.sector}' must be non-empty")

    # Limits sit just inside the browser bins (±0.16 turn, ±0.42 profile)
    # so a sample taken on the bin edge still passes.
    if by_sector["far-left"].yaw > -0.38:
        raise ValueError("far-left yaw must be <= -0.38")
    if by_sector["left"].yaw > -0.12:
        raise ValueError("left yaw must be <= -0.12")
    if abs(by_sector["front"].yaw) > 0.22:
        raise ValueError("front yaw must satisfy abs(yaw) <= 0.22")
    if by_sector["right"].yaw < 0.12:
        raise ValueError("right yaw must be >= 0.12")
    if by_sector["far-right"].yaw < 0.38:
        raise ValueError("far-right yaw must be >= 0.38")

    return views


class EnrollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uin: str = Field(..., min_length=4, max_length=32, description="MOSIP Unique Identification Number")
    fullName: str = Field(..., min_length=1, max_length=128, description="Citizen full legal name")
    email: str = Field(..., max_length=128, description="Citizen email address")
    faceImage: str = Field(..., description="Base64-encoded face image (JPEG/PNG data URL)")
    faceViews: list[FaceViewSample] | None = None

    @model_validator(mode="after")
    def _validate_face_views(self) -> "EnrollRequest":
        validate_face_views(self.faceViews)
        return self


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uin: str = Field(..., description="Target citizen UIN for 1:1 verification")
    liveImage: str | None = Field(
        default=None,
        description="Live probe face image (data URL or base64)",
    )
    livenessScore: float = Field(..., ge=0.0, le=100.0, description="Unused blink score; ignored")
    livenessPassed: bool = Field(..., description="Unused blink flag; ignored")
    challengeId: str | None = Field(default=None, description="Single-use head-sweep challenge")
    liveViews: list[FaceViewSample] | None = None

    @model_validator(mode="after")
    def _validate_live_views(self) -> "AuthRequest":
        validate_face_views(self.liveViews)
        has_image = bool(self.liveImage and self.liveImage.strip())
        if not has_image and not self.liveViews:
            raise ValueError("liveImage or liveViews is required")
        return self


class CredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uin: str = Field(..., min_length=4, description="Enrolled citizen UIN")
    password: str = Field(..., min_length=8, description="Password chosen by the citizen")


class CredentialResponse(BaseModel):
    status: str
    uin: str
    keycloakProvisioned: bool


class AuthResponse(BaseModel):
    status: str
    verified: bool
    isFaceMatch: bool
    livenessPassed: bool
    euclideanDistance: float
    matchScore: float
    livenessScore: float
    threshold: float
    citizen: dict[str, Any]
    jwtToken: str | None = None
    message: str | None = None
    sweepAccepted: bool = False
    yawSource: str | None = None


class CitizenSummary(BaseModel):
    uin: str
    fullName: str
    email: str | None = None
    createdAt: str | None = None
