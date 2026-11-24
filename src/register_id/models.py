"""
Pydantic data models for the register_id submodule.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from register_id.consent import ConsentRecord, validate_consent

ReasonText = Annotated[str, Field(min_length=3, max_length=200)]


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


class FaceChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["enroll", "check"]


class FaceChallenge(BaseModel):
    challengeId: str
    purpose: Literal["enroll", "check"]
    expiresInSeconds: int
    requiredBlinks: int
    sectors: list[str] = Field(default_factory=lambda: list(FACE_VIEW_SECTORS))


SweepYaw = Annotated[float, Field(ge=-1.5, le=1.5, allow_inf_nan=False)]


class ClientLiveness(BaseModel):
    """Liveness evidence as reported by the browser. The server did not measure it."""

    model_config = ConfigDict(extra="forbid")

    challengeId: str = Field(..., min_length=1, max_length=64)
    engine: Literal["face-api-128"]
    blinkCount: int = Field(..., ge=0, le=50)
    # Order: far-left, left, front, right, far-right.
    sweepYaws: list[SweepYaw] = Field(..., min_length=5, max_length=5)


class EnrollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fullName: str = Field(..., min_length=1, max_length=128, description="Citizen full legal name")
    email: str = Field(..., max_length=128, description="Citizen email address")
    gender: str = Field(default="Female", min_length=1, max_length=40)
    dateOfBirth: str = Field(default="1990-01-01", min_length=10, max_length=10)
    phone: str = Field(default="", max_length=32)
    addressLine1: str = Field(default="", max_length=128)
    addressLine2: str = Field(default="", max_length=128)
    addressLine3: str = Field(default="", max_length=128)
    region: str = Field(default="", max_length=64)
    province: str = Field(default="", max_length=64)
    city: str = Field(default="", max_length=64)
    zone: str = Field(default="", max_length=32)
    postalCode: str = Field(default="", max_length=16)
    referenceIdentityNumber: str = Field(default="", max_length=64)
    emailIdCard: bool = False
    # Browser-drawn card (name, date of birth, UIN, QR). Not stored or logged.
    idCardImage: str | None = Field(default=None, repr=False)
    faceImage: str = Field(..., description="Base64-encoded face image (JPEG/PNG data URL)")
    faceViews: list[FaceViewSample] | None = None
    faceDescriptors: list[list[float]] | None = Field(default=None, min_length=1, max_length=5)
    liveness: ClientLiveness | None = None
    consent: ConsentRecord

    @model_validator(mode="before")
    @classmethod
    def _refuse_client_uin(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("uin"):
            raise ValueError("The server allocates the UIN")
        return data

    @model_validator(mode="after")
    def _validate_face_views(self) -> "EnrollRequest":
        if len(self.dateOfBirth) != 10 or self.dateOfBirth[4] not in "-/" or self.dateOfBirth[7] not in "-/":
            raise ValueError("dateOfBirth must be yyyy-MM-dd")
        validate_face_views(self.faceViews)
        if (self.faceDescriptors is None) != (self.liveness is None):
            raise ValueError("faceDescriptors and liveness must be sent together")
        if self.faceDescriptors is not None and self.faceViews is not None:
            raise ValueError("faceViews cannot be combined with faceDescriptors")
        self.consent = validate_consent(self.consent)
        return self


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uin: str = Field(..., description="Target citizen UIN for 1:1 verification")
    liveImage: str | None = Field(
        default=None,
        description="Live probe face image (data URL or base64)",
    )
    # Required on the image path. Optional on the descriptor path. Ignored on both.
    livenessScore: float | None = Field(
        default=None, ge=0.0, le=100.0, description="Unused blink score; ignored"
    )
    livenessPassed: bool | None = Field(default=None, description="Unused blink flag; ignored")
    challengeId: str | None = Field(default=None, description="Single-use head-sweep challenge")
    liveViews: list[FaceViewSample] | None = None
    probeDescriptor: list[float] | None = None
    liveness: ClientLiveness | None = None

    @model_validator(mode="after")
    def _validate_live_views(self) -> "AuthRequest":
        validate_face_views(self.liveViews)
        if self.probeDescriptor is not None:
            if self.liveness is None:
                raise ValueError("liveness is required with probeDescriptor")
            return self
        if self.liveness is not None:
            raise ValueError("liveness is only accepted with probeDescriptor")
        if self.livenessScore is None:
            raise ValueError("livenessScore is required")
        if self.livenessPassed is None:
            raise ValueError("livenessPassed is required")
        has_image = bool(self.liveImage and self.liveImage.strip())
        if not has_image and not self.liveViews:
            raise ValueError("liveImage or liveViews is required")
        return self


class CredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uin: str = Field(..., min_length=4, description="Enrolled citizen UIN")
    password: str = Field(..., min_length=8, description="Password chosen by the citizen")
    credentialTicket: str = Field(..., min_length=8, description="Single-use ticket from the enrolment that allocated this UIN")


class CredentialResponse(BaseModel):
    status: str
    uin: str
    keycloakProvisioned: bool


class AuthResponse(BaseModel):
    status: str
    verified: bool
    isFaceMatch: bool
    livenessPassed: bool
    euclideanDistance: float | None = None
    matchScore: float | None = None
    livenessScore: float | None = None
    threshold: float | None = None
    citizen: dict[str, Any]
    jwtToken: str | None = None
    message: str | None = None
    sweepAccepted: bool = False
    yawSource: str | None = None
    compared: bool = False
    livenessSource: str | None = None
    activityToken: str | None = None
    checkId: str | None = None


class DemographicsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fullName: str = Field(..., min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=128)
    reason: ReasonText


class LoginDisabledUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disabled: bool
    reason: ReasonText


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: ReasonText


class StaffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=1, max_length=254)
    role: Literal["officer", "admin"]
    reason: ReasonText


class StaffRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["officer", "admin"]
    reason: ReasonText


class CaptureAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["enroll", "camera"]
    reasonCode: Literal[
        "enroll_failed",
        "camera_unavailable",
        "camera_quality",
        "CAM-1",
        "CAM-2",
        "CAM-3",
        "CAM-4",
        "CAM-5",
        "FACE-1",
        "FACE-2",
        "FACE-3",
        "IMG-1",
        "PAD-1",
        "PAD-2",
        "SESSION-1",
        "SESSION-2",
    ]
    detail: str = Field(default="", max_length=200)


class CitizenLock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locked: bool
    reason: ReasonText


class NotMeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str | None = Field(default=None, max_length=200)


class CitizenSummary(BaseModel):
    uin: str
    fullName: str
    email: str | None = None
    createdAt: str | None = None
    loginDisabled: bool | None = None
