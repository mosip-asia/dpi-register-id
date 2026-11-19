"""
HTTP REST Client for MOSIP Identity Repository (IDRepo).

Strictly communicates with the MOSIP IDRepo REST API interface:
- POST /idrepository/v1/identity/ (Standard MOSIP JSON envelope + CBEFF XML document)
- GET /idrepository/v1/identity/uin/{uin}
- PATCH /idrepository/v1/identity/uin/{uin}
- DELETE /idrepository/v1/identity/uin/{uin}/biometrics
- GET /idrepository/v1/identity/ (List/Query)
- GET /v1/idgenerator/uin

Never touches or queries the database directly. Supports transparent in-process
fallback for offline developer workstations and automated CI testing.
"""

import base64
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

MOSIP_IDREPO_BASE_URL = os.getenv("MOSIP_IDREPO_BASE_URL", "http://localhost:8081").rstrip("/")


def _parse_embedding(value: Any) -> Any:
    """Decode a template vector when the wire format stored it as JSON text."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def _record_from_read_response(
    data: dict[str, Any],
    uin: str,
    include_biometrics: bool = False,
) -> dict[str, Any]:
    """Map a MOSIP GetIdentity envelope onto demographics. Vectors are not copied."""
    resp = data.get("response") or {}
    identity = resp.get("identity") or {}
    documents = resp.get("documents") or []

    full_name_raw = identity.get("fullName", "")
    if isinstance(full_name_raw, list) and len(full_name_raw) > 0:
        full_name = full_name_raw[0].get("value", "")
    else:
        full_name = str(full_name_raw)

    record = {
        "uin": identity.get("UIN", uin),
        "full_name": full_name,
        "email": identity.get("email"),
        "created_at": identity.get("createdAt"),
        "status": identity.get("recordStatus") or "draft",
        "login_disabled": bool(identity.get("loginDisabled", False)),
    }
    if not include_biometrics:
        return record

    cbeff_xml = None
    for doc in documents:
        if doc.get("category") == "individualBiometrics":
            b64val = doc.get("value", "")
            try:
                padded = b64val + "=" * (-len(b64val) % 4)
                cbeff_xml = base64.urlsafe_b64decode(padded).decode("utf-8")
            except Exception:
                cbeff_xml = b64val
            break

    record["face_image"] = identity.get("faceImage")
    record["cbeff_xml"] = cbeff_xml
    return record


def _summary_from_item(item: dict[str, Any]) -> dict[str, Any]:
    """List rows stay demographic. Face bytes and CBEFF are not copied."""
    return {
        "uin": item["uin"],
        "full_name": item["fullName"],
        "email": item.get("email"),
        "created_at": item.get("createdAt"),
        "status": item.get("recordStatus") or "draft",
        "login_disabled": bool(item.get("loginDisabled", False)),
    }


def _enroll_failure_summary(response) -> str:
    """HTTP status and MOSIP error codes. The body can echo face bytes and CBEFF."""
    status = getattr(response, "status_code", None)
    codes: list[str] = []
    try:
        data = response.json()
    except Exception:
        data = None
    errors = None
    if isinstance(data, dict):
        errors = data.get("errors")
        if not errors and isinstance(data.get("detail"), dict):
            errors = data["detail"].get("errors")
    if isinstance(errors, list):
        for err in errors:
            if isinstance(err, dict) and err.get("errorCode"):
                codes.append(str(err["errorCode"]))
    if codes:
        return f"MOSIP IDRepo returned HTTP {status}: {', '.join(codes)}"
    return f"MOSIP IDRepo returned HTTP {status}"


def _failure_message(response) -> str:
    try:
        data = response.json()
    except Exception:
        return f"MOSIP IDRepo returned HTTP {response.status_code}"
    errors = data.get("errors")
    if not errors and isinstance(data.get("detail"), dict):
        errors = data["detail"].get("errors")
    if errors:
        messages = []
        for err in errors:
            if isinstance(err, dict):
                messages.append(err.get("message", str(err)))
            else:
                messages.append(str(err))
        return "; ".join(messages)
    return f"MOSIP IDRepo returned HTTP {response.status_code}"


def _templates_from_body(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("templates") or []
    parsed = []
    for row in rows:
        template = {
            "sector": row.get("sector"),
            "embedding": _parse_embedding(row.get("embedding")),
        }
        if row.get("engine"):
            template["engine"] = row["engine"]
        parsed.append(template)
    return parsed


class IDRepoClient:
    """
    Client for interacting with the MOSIP IDRepo service over HTTP REST.
    """

    def __init__(self, base_url: str | None = None, enable_inprocess_fallback: bool = True):
        self.base_url = (base_url or MOSIP_IDREPO_BASE_URL).rstrip("/")
        self.enable_inprocess_fallback = enable_inprocess_fallback
        self.last_error: str | None = None
        self._test_client = None

    def _get_test_client(self):
        if self._test_client is None:
            from fastapi.testclient import TestClient
            from mock.idrepo.app import idrepo_app
            self._test_client = TestClient(idrepo_app)
        return self._test_client

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _make_rid(self) -> str:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        seq = str(random.randint(10000, 89999))
        return f"1002510009{seq}{ts}"

    def check_health(self) -> dict[str, Any]:
        """
        Pings IDRepo /health endpoint.
        """
        try:
            r = requests.get(f"{self.base_url}/health", timeout=2)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass

        if self.enable_inprocess_fallback:
            client = self._get_test_client()
            r = client.get("/health")
            if r.status_code == 200:
                data = r.json()
                data["mode"] = "in-process-mock"
                return data

        return {"status": "DOWN", "error": "Unable to connect to MOSIP IDRepo"}

    def generate_uin(self) -> str:
        """
        Requests a fresh sovereign citizen UIN via /v1/idgenerator/uin.
        """
        try:
            r = requests.get(f"{self.base_url}/v1/idgenerator/uin", timeout=3)
            if r.status_code == 200:
                data = r.json()
                if "response" in data and "uin" in data["response"]:
                    return str(data["response"]["uin"])
        except Exception as e:
            logger.debug(f"IDGenerator HTTP call failed: {e}")

        if self.enable_inprocess_fallback:
            client = self._get_test_client()
            r = client.get("/v1/idgenerator/uin")
            if r.status_code == 200:
                data = r.json()
                if "response" in data and "uin" in data["response"]:
                    return str(data["response"]["uin"])

        # Fallback random 10-digit UIN
        return str(random.randint(2000000000, 9999999999))

    def add_identity(
        self,
        uin: str,
        full_name: str,
        email: str | None = None,
        face_image: str | None = None,
        cbeff_xml: str | None = None,
        templates: list | None = None,
        status: str | None = None,
    ) -> bool:
        """
        Enrolls or updates an identity in MOSIP IDRepo via POST /idrepository/v1/identity/.

        Demographics stay in request.identity. Match vectors travel in request.templates
        and are not written onto the identity row.

        status is the registry record state: draft (default) or biometric.
        Omitting it leaves the record draft. Storing a face does not change that.
        """
        record_status = "draft" if status is None else status
        if record_status not in ("draft", "biometric"):
            self.last_error = "status must be 'draft' or 'biometric'"
            return False

        documents = []
        if cbeff_xml:
            cbeff_b64url = base64.urlsafe_b64encode(cbeff_xml.encode("utf-8")).decode("utf-8")
            documents.append({
                "category": "individualBiometrics",
                "value": cbeff_b64url,
            })

        request_body: dict[str, Any] = {
            "registrationId": self._make_rid(),
            "status": "ACTIVATED",
            "identity": {
                "UIN": uin,
                "fullName": [{"language": "eng", "value": full_name}],
                "email": email,
                "faceImage": face_image,
            },
            "documents": documents,
            "recordStatus": record_status,
        }
        if templates is not None:
            request_body["templates"] = templates

        payload = {
            "id": "mosip.id.create",
            "version": "v1",
            "requesttime": self._now_iso(),
            "metadata": {},
            "request": request_body,
        }

        self.last_error = None
        remote_error = None

        # 1. Attempt remote HTTP call
        try:
            r = requests.post(
                f"{self.base_url}/idrepository/v1/identity/",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            if r.status_code in (200, 201):
                data = r.json()
                if not data.get("errors"):
                    return True
            remote_error = _enroll_failure_summary(r)
            logger.warning("IDRepo remote enroll failed: %s", remote_error)
        except Exception as e:
            remote_error = f"Failed to connect to MOSIP IDRepo at '{self.base_url}': {e}"
            logger.debug(f"IDRepo remote connection failed: {e}")

        # 2. In-process fallback
        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                r = client.post("/idrepository/v1/identity/", json=payload)
                if r.status_code in (200, 201):
                    data = r.json()
                    if not data.get("errors"):
                        return True
                    errors = data.get("errors", [])
                    err_msgs = [e.get("message", str(e)) for e in errors]
                    self.last_error = f"In-process mock IDRepo error: {', '.join(err_msgs)}"
                    return False
            except Exception as e:
                logger.debug(f"In-process IDRepo fallback failed: {e}")

        self.last_error = remote_error or "Unknown error communicating with MOSIP IDRepo"
        return False

    def get_identity(self, uin: str, include_biometrics: bool = False) -> dict[str, Any] | None:
        """
        Retrieves a citizen identity from MOSIP IDRepo via GET /idrepository/v1/identity/uin/{uin}.

        Ordinary reads omit face_image and cbeff_xml. A custodian read passes
        include_biometrics=True. Name, email, status, and the login flag stay.
        """
        params = {"includeBiometrics": "true" if include_biometrics else "false"}

        # 1. Attempt remote HTTP call
        try:
            r = requests.get(
                f"{self.base_url}/idrepository/v1/identity/uin/{uin}",
                params=params,
                timeout=3,
            )
            if r.status_code == 200:
                return _record_from_read_response(r.json(), uin, include_biometrics)
        except Exception as e:
            logger.debug(f"IDRepo remote get failed: {e}")

        # 2. In-process fallback
        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                r = client.get(f"/idrepository/v1/identity/uin/{uin}", params=params)
                if r.status_code == 200:
                    return _record_from_read_response(r.json(), uin, include_biometrics)
            except Exception as e:
                logger.error(f"In-process IDRepo fallback get failed: {e}")

        return None

    def get_face_templates(self, uin: str) -> list[dict[str, Any]]:
        """
        Load match vectors from GET /ida/v1/face-template/uin/{uin}.

        Remote is tried first, then the in-process mock. An empty list means
        the UIN has no templates (or both calls failed).
        """
        try:
            r = requests.get(f"{self.base_url}/ida/v1/face-template/uin/{uin}", timeout=3)
            if r.status_code == 200:
                return _templates_from_body(r.json())
        except Exception as e:
            logger.debug(f"IDRepo remote face-template get failed: {e}")

        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                r = client.get(f"/ida/v1/face-template/uin/{uin}")
                if r.status_code == 200:
                    return _templates_from_body(r.json())
            except Exception as e:
                logger.error(f"In-process IDRepo fallback face-template get failed: {e}")

        return []

    def list_identities(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Retrieves list of recent identities from MOSIP IDRepo via GET /idrepository/v1/identity/.

        Rows keep uin, full_name, email, and created_at. Face bytes and CBEFF
        are never included. status and login_disabled are included when present.
        """
        # 1. Attempt remote HTTP call
        try:
            r = requests.get(f"{self.base_url}/idrepository/v1/identity/?limit={limit}", timeout=3)
            if r.status_code == 200:
                data = r.json()
                rows = data.get("response", [])
                return [_summary_from_item(item) for item in rows]
        except Exception as e:
            logger.debug(f"IDRepo remote list failed: {e}")

        # 2. In-process fallback
        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                r = client.get(f"/idrepository/v1/identity/?limit={limit}")
                if r.status_code == 200:
                    data = r.json()
                    rows = data.get("response", [])
                    return [_summary_from_item(item) for item in rows]
            except Exception as e:
                logger.error(f"In-process IDRepo fallback list failed: {e}")

        return []

    def _exchange(self, method: str, path: str, payload: dict | None = None) -> bool:
        """Send one mutating call, then the in-process mock if the remote call fails."""
        self.last_error = None
        remote_error = None
        url = f"{self.base_url}{path}"
        request_kwargs: dict[str, Any] = {"timeout": 5}
        if payload is not None:
            request_kwargs["json"] = payload
            request_kwargs["headers"] = {"Content-Type": "application/json"}

        try:
            response = requests.request(method, url, **request_kwargs)
            if response.status_code in (200, 201):
                data = response.json()
                if not data.get("errors"):
                    return True
            remote_error = _failure_message(response)
            logger.warning(f"IDRepo remote {method} {path} failed: {remote_error}")
        except Exception as exc:
            remote_error = f"Failed to connect to MOSIP IDRepo at '{self.base_url}': {exc}"
            logger.debug(f"IDRepo remote {method} failed: {exc}")

        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                call = getattr(client, method.lower())
                response = call(path, json=payload) if payload is not None else call(path)
                if response.status_code in (200, 201):
                    data = response.json()
                    if not data.get("errors"):
                        return True
                self.last_error = f"In-process mock IDRepo error: {_failure_message(response)}"
                return False
            except Exception as exc:
                logger.debug(f"In-process IDRepo fallback {method} failed: {exc}")

        self.last_error = remote_error or "Unknown error communicating with MOSIP IDRepo"
        return False

    def update_demographics(self, uin: str, full_name: str, email: str | None = None) -> bool:
        """Correct full name and email for an existing UIN. Does not touch the face."""
        if not full_name or not full_name.strip():
            self.last_error = "full name is required"
            return False
        payload = {
            "id": "mosip.id.update",
            "version": "v1",
            "requesttime": self._now_iso(),
            "metadata": {},
            "request": {
                "identity": {
                    "fullName": [{"language": "eng", "value": full_name}],
                    "email": email,
                }
            },
        }
        return self._exchange("PATCH", f"/idrepository/v1/identity/uin/{uin}", payload)

    def set_login_disabled(self, uin: str, disabled: bool) -> bool:
        """
        Remember an operator login-disabled flag on the identity record.

        This does not call Keycloak.
        """
        payload = {
            "id": "mosip.id.update",
            "version": "v1",
            "requesttime": self._now_iso(),
            "metadata": {},
            "request": {"loginDisabled": bool(disabled)},
        }
        return self._exchange("PATCH", f"/idrepository/v1/identity/uin/{uin}", payload)

    def delete_face(self, uin: str) -> bool:
        """Remove face_image, CBEFF XML, and face templates for one UIN."""
        return self._exchange("DELETE", f"/idrepository/v1/identity/uin/{uin}/biometrics")


# Global singleton client
_idrepo_client: IDRepoClient | None = None


def get_idrepo_client() -> IDRepoClient:
    global _idrepo_client
    if _idrepo_client is None:
        _idrepo_client = IDRepoClient()
    return _idrepo_client
