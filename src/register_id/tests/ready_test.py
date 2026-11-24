"""Liveness stays local. Readiness checks the dependencies the process is configured to use."""

from fastapi.testclient import TestClient

from project.web import app

client = TestClient(app)


def test_health_does_not_call_dependencies():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_skips_unset_dependencies(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("IDREPO_INPROCESS_FALLBACK", "true")
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"redis": "skipped", "config": "skipped"}


def test_ready_reports_redis_down(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("IDREPO_INPROCESS_FALLBACK", "true")
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["redis"] == "down"
    assert body["checks"]["config"] == "skipped"


def test_ready_does_not_call_idrepo_when_fallback_is_off(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("IDREPO_INPROCESS_FALLBACK", "false")
    monkeypatch.setenv("MOSIP_IDREPO_BASE_URL", "http://idrepo")
    monkeypatch.setenv("MOSIP_AUTHMANAGER_URL", "http://auth")
    monkeypatch.setenv("MOSIP_CLIENT_ID", "mosip-regproc-client")
    monkeypatch.setenv("MOSIP_SECRET_KEY", "secret")
    monkeypatch.setenv("KEYCLOAK_ADMIN_CLIENT_ID", "register-id")
    monkeypatch.setenv("KEYCLOAK_ADMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_URL", "https://iam.example/auth")
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "https://iam.example/auth")
    monkeypatch.setenv("KEYCLOAK_INTERNAL_URL", "http://keycloak/auth")

    def fail_idrepo():
        raise AssertionError("ready must not call IDRepo")

    monkeypatch.setattr("register_id.idrepo_client.IDRepoClient.check_health", fail_idrepo)
    response = client.get("/ready")
    assert response.status_code == 503
    assert "idrepo" not in response.json()["checks"]
    assert response.json()["checks"]["config"] == "ok"
    assert response.json()["checks"]["redis"] == "down"


def _kit_ready_env(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("IDREPO_INPROCESS_FALLBACK", "false")
    monkeypatch.setenv("MOSIP_IDREPO_BASE_URL", "http://idrepo")
    monkeypatch.setenv("MOSIP_AUTHMANAGER_URL", "http://auth")
    monkeypatch.setenv("MOSIP_CLIENT_ID", "mosip-regproc-client")
    monkeypatch.setenv("MOSIP_SECRET_KEY", "secret")
    monkeypatch.setenv("KEYCLOAK_ADMIN_CLIENT_ID", "register-id")
    monkeypatch.setenv("KEYCLOAK_ADMIN_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_URL", "https://iam.example/auth")


def test_ready_requires_both_keycloak_urls_when_fallback_is_off(monkeypatch):
    _kit_ready_env(monkeypatch)
    monkeypatch.delenv("KEYCLOAK_PUBLIC_URL", raising=False)
    monkeypatch.delenv("KEYCLOAK_INTERNAL_URL", raising=False)

    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["config"] == "incomplete"

    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "https://iam.example/auth")
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["config"] == "incomplete"

    monkeypatch.delenv("KEYCLOAK_PUBLIC_URL", raising=False)
    monkeypatch.setenv("KEYCLOAK_INTERNAL_URL", "http://keycloak/auth")
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["config"] == "incomplete"

    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "https://iam.example/auth")
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["config"] == "ok"
    assert response.json()["checks"]["redis"] == "down"
