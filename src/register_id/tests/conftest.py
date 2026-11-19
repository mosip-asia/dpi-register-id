"""Shared test fixtures for register_id."""

import pytest

from register_id.enroll_limit import reset_enroll_limits

TEST_ENROLL_TOKEN = "test-enroll-token"


def enroll_headers(token: str = TEST_ENROLL_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _enroll_caller_and_empty_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give enroll tests a fixed caller and a fresh hourly bucket."""
    monkeypatch.setenv("REGISTER_ID_ENROLL_TOKEN", TEST_ENROLL_TOKEN)
    reset_enroll_limits()


@pytest.fixture(autouse=True)
def _disable_smtp_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep enroll tests from talking to a real SMTP host.

    project/__init__.py loads `.env`, which may carry developer EMAIL_* values.
    Individual tests that need SMTP set the variables themselves.
    """
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
