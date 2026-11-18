"""
Draft applications for people who could not finish a face capture.

A draft is demographics, a reason, and consent. It is not a citizen identity:
creating one does not enroll, write IDRepo, or send mail. The public handle is
a short code. The record id stays in the store.
"""

from __future__ import annotations

import secrets
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from register_id.application_store import ApplicationStore, ApplicationStoreError
from register_id.consent import ConsentRecord, validate_consent

APPLICATION_TTL_SECONDS = 30 * 24 * 60 * 60
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_CODE_LENGTH = 6
_CODE_ATTEMPTS = 8


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fullName: str = Field(..., min_length=1, max_length=128)
    gender: str = Field(..., min_length=1, max_length=32)
    dateOfBirth: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    email: str = Field(..., min_length=1, max_length=128)
    researchOptIn: bool
    reason: Literal["no-camera", "camera-quality"]
    consent: ConsentRecord

    @field_validator("fullName", "gender", "email", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("email")
    @classmethod
    def _email_has_at_and_dot(cls, value: str) -> str:
        at = value.find("@")
        if at < 0 or "." not in value[at + 1 :]:
            raise ValueError("email must contain @ and a dot after the @")
        return value

    @model_validator(mode="after")
    def _accepted_consent(self) -> "ApplicationCreate":
        self.consent = validate_consent(self.consent)
        return self


class ApplicationCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    expiresAt: float
    expiresInSeconds: int


class ApplicationCodeExhausted(ApplicationStoreError):
    """Eight generated codes were already stored."""

    def __init__(self) -> None:
        super().__init__("Could not allocate an application code.")


def validation_detail(exc: ValidationError) -> str:
    """One string for a 422 body. The payload is not included."""
    messages: list[str] = []
    for err in exc.errors():
        cause = (err.get("ctx") or {}).get("error")
        if isinstance(cause, Exception) and str(cause):
            messages.append(str(cause))
            continue
        msg = str(err.get("msg") or "invalid request")
        prefix = "Value error, "
        if msg.startswith(prefix):
            msg = msg[len(prefix) :]
        messages.append(msg)
    return "; ".join(messages) if messages else "invalid request"


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def create_application(
    store: ApplicationStore,
    application: ApplicationCreate,
    now: float | None = None,
) -> ApplicationCreated:
    """
    Build a guid, a public code, and the stored record.

    The guid is written to the store and is not part of the response.
    A code collision tries another code, up to eight times.
    """
    clock = time.time() if now is None else now
    application_id = str(uuid.uuid4())
    consent = application.consent.model_dump()
    for _ in range(_CODE_ATTEMPTS):
        code = _new_code()
        record = {
            "id": application_id,
            "code": code,
            "fullName": application.fullName,
            "gender": application.gender,
            "dateOfBirth": application.dateOfBirth,
            "email": application.email,
            "researchOptIn": application.researchOptIn,
            "reason": application.reason,
            "consent": consent,
            "createdAt": clock,
            "expiresAt": clock + APPLICATION_TTL_SECONDS,
        }
        if store.save(record, APPLICATION_TTL_SECONDS, now=clock):
            return ApplicationCreated(
                code=code,
                expiresAt=record["expiresAt"],
                expiresInSeconds=APPLICATION_TTL_SECONDS,
            )
    raise ApplicationCodeExhausted()
