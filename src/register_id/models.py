"""
Pydantic data models for the register_id submodule.
"""

from typing import Any
from pydantic import BaseModel, Field


class LivenessChallenge(BaseModel):
    challengeId: str = Field(..., description="Unique nonce identifier for this liveness session")
    action: str = Field(default="BLINK_TWICE", description="Requested interactive anti-replay action")
    targetBlinks: int = Field(default=2, description="Number of blinks required")
    timeLimitSeconds: int = Field(default=10, description="Validity window for the challenge in seconds")
    prompt: str = Field(default="Please blink 2 times within 10 seconds", description="User guidance prompt")
    createdAt: float = Field(..., description="Timestamp of challenge issuance")


class LivenessRequest(BaseModel):
    challengeId: str | None = Field(default=None, description="Optional active challenge nonce")
    blinkCount: int = Field(..., ge=0, description="Observed natural blink count")
    minEar: float = Field(..., ge=0.0, le=1.0, description="Minimum Eye Aspect Ratio observed")
    maxEar: float = Field(..., ge=0.0, le=1.0, description="Maximum Eye Aspect Ratio observed")
    durationMs: float = Field(..., ge=0.0, description="Liveness tracking duration in milliseconds")


class LivenessResponse(BaseModel):
    status: str
    isoStandard: str = "ISO/IEC 30107-3 (PAD Level 1/2)"
    livenessScore: float
    padMethod: str = "Active Eye Aspect Ratio (EAR) & Blink Micro-Dynamics"
    message: str


class EnrollRequest(BaseModel):
    uin: str = Field(..., min_length=4, max_length=32, description="MOSIP Unique Identification Number")
    fullName: str = Field(..., min_length=1, max_length=128, description="Citizen full legal name")
    email: str = Field(..., max_length=128, description="Citizen email address")
    faceImage: str = Field(..., description="Base64-encoded face image (JPEG/PNG data URL)")
    faceEmbedding: list[float] = Field(..., description="128-D facial feature descriptor vector")
    password: str = Field(default="CitizenPass123!", description="Initial password for Keycloak IAM")


class AuthRequest(BaseModel):
    uin: str = Field(..., description="Target citizen UIN for 1:1 verification")
    liveEmbedding: list[float] = Field(..., description="Live probe 128-D descriptor vector")
    livenessScore: float = Field(..., ge=0.0, le=100.0, description="PAD confidence score")
    livenessPassed: bool = Field(..., description="Whether ISO 30107-3 PAD passed")


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


class CitizenSummary(BaseModel):
    uin: str
    fullName: str
    email: str | None = None
    createdAt: str | None = None
