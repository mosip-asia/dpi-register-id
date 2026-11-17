"""
Consent captured before a face image may be stored.

The record names why the face is kept, when the person agreed, and which
language version of the notice they saw. It never carries an image.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_CONSENT_LANGUAGES = ("eng", "tha")
_CONSENT_FIELDS = {"accepted", "purpose", "acceptedAt", "language"}


class ConsentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    purpose: str = Field(..., min_length=8)
    acceptedAt: float = Field(..., description="Unix time in seconds when the person accepted")
    language: Literal["eng", "tha"]


def _consent_mapping(consent: Any) -> dict[str, Any]:
    if isinstance(consent, ConsentRecord):
        return consent.model_dump()
    if isinstance(consent, dict):
        return consent
    raise ValueError("consent is required")


def validate_consent(consent: Any) -> ConsentRecord:
    """
    Return a consent record the enrollment path may keep.

    Raises ValueError when purpose is empty, the person did not accept,
    acceptedAt is missing, or language is not eng or tha.
    """
    if consent is None:
        raise ValueError("consent is required")

    data = _consent_mapping(consent)
    unknown = set(data) - _CONSENT_FIELDS
    if unknown:
        raise ValueError("consent must not include extra fields")

    if data.get("accepted") is not True:
        raise ValueError("consent was not accepted")

    purpose = data.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("purpose is empty")

    if "acceptedAt" not in data or data.get("acceptedAt") is None:
        raise ValueError("acceptedAt is missing")

    language = data.get("language")
    if language not in ALLOWED_CONSENT_LANGUAGES:
        raise ValueError("language must be eng or tha")

    return ConsentRecord.model_validate(
        {
            "accepted": True,
            "purpose": purpose,
            "acceptedAt": data["acceptedAt"],
            "language": language,
        }
    )
