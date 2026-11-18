"""Shared test fixtures for register_id."""

import pytest


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
