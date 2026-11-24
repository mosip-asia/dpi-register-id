"""Shared test fixtures for register_id."""

import pytest

from register_id.enroll_limit import reset_enroll_limits

TEST_ENROLL_TOKEN = "test-enroll-token"


def enroll_headers(token: str | None = None) -> dict[str, str]:
    """A fresh single-use ticket, unless the test passes one it wants to reuse."""
    from register_id.enroll_ticket import issue_ticket

    ticket = token or issue_ticket().ticket
    return {"X-Enroll-Ticket": ticket}


@pytest.fixture(autouse=True)
def _empty_enroll_bucket() -> None:
    """Give each test a fresh hourly enrollment window and ticket store."""
    from register_id.enroll_ticket import reset_tickets

    reset_enroll_limits()
    reset_tickets()


@pytest.fixture(autouse=True)
def _local_idrepo_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests use the in-process mock. The shipped default is off, with no retry delay."""
    monkeypatch.setenv("IDREPO_INPROCESS_FALLBACK", "true")
    monkeypatch.setenv("MOSIP_HTTP_RETRIES", "0")
    monkeypatch.setenv("MOSIP_HTTP_BACKOFF_SECONDS", "0")


@pytest.fixture(autouse=True)
def _isolated_log_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep audit, staff, lock, and grant files out of the repo logs directory."""
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))


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
