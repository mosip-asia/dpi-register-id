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
import time
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

def _configured(name: str, default: str) -> str:
    """Blank environment values keep the local default. Compose passes empty strings."""
    value = os.getenv(name, "").strip()
    return (value or default).rstrip("/")


MOSIP_IDREPO_BASE_URL = _configured("MOSIP_IDREPO_BASE_URL", "http://localhost:8081")
# Authmanager tokens are short-lived. Refresh before a typical one-hour expiry.
_TOKEN_TTL_SECONDS = 540


def inprocess_fallback_enabled() -> bool:
    """Local compose sets this true. The shipped image leaves it unset, which is off."""
    raw = os.getenv("IDREPO_INPROCESS_FALLBACK")
    if raw is None or not raw.strip():
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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


def _http_timeout() -> float:
    raw = os.getenv("MOSIP_HTTP_TIMEOUT", "10").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 10.0
    return min(max(value, 0.2), 60.0)


def _http_attempts(idempotent: bool) -> int:
    if not idempotent:
        return 1
    raw = os.getenv("MOSIP_HTTP_RETRIES", "2").strip()
    try:
        retries = int(raw)
    except ValueError:
        retries = 2
    return min(max(retries, 0), 5) + 1


def _http_backoff() -> float:
    raw = os.getenv("MOSIP_HTTP_BACKOFF_SECONDS", "0.2").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 0.2
    return min(max(value, 0.0), 5.0)


def _uin_from_generator(response) -> str:
    if response is None or getattr(response, "status_code", None) != 200:
        return ""
    try:
        data = response.json()
    except Exception:
        return ""
    body = data.get("response") if isinstance(data, dict) else None
    if isinstance(body, dict) and body.get("uin"):
        return str(body["uin"])
    return ""


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

    def __init__(self, base_url: str | None = None, enable_inprocess_fallback: bool | None = None):
        self.base_url = (base_url or MOSIP_IDREPO_BASE_URL).rstrip("/")
        if enable_inprocess_fallback is None:
            enable_inprocess_fallback = inprocess_fallback_enabled()
        self.enable_inprocess_fallback = enable_inprocess_fallback
        self.last_error: str | None = None
        # 503 when the backend cannot be reached, 502 when it rejects the call.
        self.last_status: int | None = None
        # Set only after a write succeeds. The mock name is never mosip-idrepo-rest.
        self.last_backend: str | None = None
        self._test_client = None
        self._token: str | None = None
        self._token_at: float = 0.0

    def _auth_configured(self) -> bool:
        return bool(
            os.getenv("MOSIP_AUTHMANAGER_URL", "").strip()
            and os.getenv("MOSIP_CLIENT_ID", "").strip()
            and os.getenv("MOSIP_SECRET_KEY", "").strip()
        )

    def _mosip_token(self) -> str | None:
        """Client-id secret from MOSIP authmanager. The secret and token are not logged."""
        if not self._auth_configured():
            return None
        if self._token and (time.monotonic() - self._token_at) < _TOKEN_TTL_SECONDS:
            return self._token

        auth_base = os.environ["MOSIP_AUTHMANAGER_URL"].rstrip("/")
        url = f"{auth_base}/v1/authmanager/authenticate/clientidsecretkey"
        payload = {
            "id": "mosip.auth.clientidsecretkey",
            "version": "1.0",
            "requesttime": self._now_iso(),
            "metadata": {},
            "request": {
                "clientId": os.environ["MOSIP_CLIENT_ID"],
                "secretKey": os.environ["MOSIP_SECRET_KEY"],
                "appId": os.getenv("MOSIP_APP_ID", "").strip() or "regproc",
            },
        }
        # This cookie is an authmanager clientidsecretkey token for appId regproc, not a Keycloak access token.
        # A token POST is not retried on an HTTP error. One extra attempt covers a lost connection.
        response = None
        for attempt in range(2):
            try:
                response = requests.post(url, json=payload, timeout=_http_timeout())
            except requests.RequestException:
                if attempt == 0:
                    delay = _http_backoff()
                    if delay:
                        time.sleep(delay)
                    continue
                logger.warning("MOSIP authmanager unreachable")
                return None
            else:
                break
        if response.status_code != 200:
            logger.warning("MOSIP authmanager returned status %s", response.status_code)
            return None
        try:
            data = response.json()
        except ValueError:
            logger.warning("MOSIP authmanager response was not JSON")
            return None
        body = data.get("response") if isinstance(data, dict) else None
        token = None
        cookies = getattr(response, "cookies", None)
        cookie = cookies.get("Authorization") if cookies is not None else None
        if cookie:
            token = str(cookie)
        elif isinstance(body, dict):
            message = body.get("message") or body.get("token")
            # Authmanager often puts a success sentence in message and the JWT in Set-Cookie.
            if isinstance(message, str) and "validated successfully" not in message.lower():
                token = message
        if not token:
            logger.warning("MOSIP authmanager response did not include a token")
            return None
        self._token = str(token)
        self._token_at = time.monotonic()
        return self._token

    def _headers(self) -> dict[str, str]:
        """MOSIP kernel sends the authmanager token as a cookie, not a Bearer header."""
        headers = {"Content-Type": "application/json"}
        token = self._mosip_token()
        if token:
            headers["Cookie"] = f"Authorization={token}"
        return headers

    def _send(
        self,
        method: str,
        url: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
        idempotent: bool = True,
        retries: int | None = None,
    ):
        """Call MOSIP. Idempotent calls retry with backoff. Connection loss is status 503."""
        if retries is None:
            attempts = _http_attempts(idempotent)
        else:
            attempts = min(max(int(retries), 0), 5) + 1
        delay = _http_backoff()
        last_response = None
        for attempt in range(attempts):
            try:
                call = {
                    "GET": requests.get,
                    "POST": requests.post,
                    "PATCH": requests.patch,
                    "DELETE": requests.delete,
                }[method]
                kwargs: dict[str, Any] = {"headers": self._headers(), "timeout": _http_timeout()}
                if method == "GET":
                    kwargs["params"] = params
                elif json_body is not None:
                    kwargs["json"] = json_body
                last_response = call(url, **kwargs)
            except Exception:
                self.last_status = 503
                last_response = None
            else:
                if last_response.status_code in (502, 503, 504):
                    self.last_status = 503
                elif last_response.status_code >= 400:
                    self.last_status = 502
                    return last_response
                else:
                    self.last_status = None
                    return last_response
            if attempt + 1 < attempts and delay:
                time.sleep(delay)
                delay = min(delay * 2, 5.0)
        self.last_status = 503
        return last_response

    def _idgenerator_base(self) -> str:
        """Kernel idgenerator. An empty URL uses that host only when fallback is off."""
        configured = os.getenv("MOSIP_IDGENERATOR_BASE_URL", "").strip().rstrip("/")
        if configured:
            return configured
        if self.enable_inprocess_fallback:
            return ""
        return "http://idgenerator.kernel"

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
        for path in ("/health", "/actuator/health"):
            try:
                r = requests.get(f"{self.base_url}{path}", timeout=_http_timeout())
                if r.status_code != 200:
                    continue
                data = r.json()
                status = str(data.get("status", "")).upper()
                if status in ("UP", "OK"):
                    return data
            except Exception:
                continue

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
        Allocate a UIN from the kernel idgenerator. A failed call does not invent a number.
        """
        self.last_status = None
        # Production must present the authmanager cookie. No cookie, no invented UIN.
        if not self.enable_inprocess_fallback and not self._mosip_token():
            self.last_status = 503
            self.last_error = "MOSIP idgenerator did not return a UIN"
            return ""

        base = self._idgenerator_base()
        if base:
            response = self._send(
                "GET",
                f"{base}/v1/idgenerator/uin",
                retries=0,
            )
            uin = _uin_from_generator(response)
            if uin:
                self.last_status = None
                return uin
            if not self.enable_inprocess_fallback:
                self.last_status = 503
                self.last_error = "MOSIP idgenerator did not return a UIN"
                return ""

        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                mock = client.get("/v1/idgenerator/uin")
                uin = _uin_from_generator(mock)
                if uin:
                    self.last_status = None
                    return uin
            except Exception as exc:
                logger.debug("In-process idgenerator failed: %s", exc)

        self.last_status = 503
        self.last_error = "MOSIP idgenerator did not return a UIN"
        return ""

    def add_identity(
        self,
        uin: str,
        full_name: str,
        email: str | None = None,
        face_image: str | None = None,
        cbeff_xml: str | None = None,
        templates: list | None = None,
        status: str | None = None,
        identity: dict[str, Any] | None = None,
        registration_id: str | None = None,
        date_of_birth: str = "",
        gender: str = "",
        phone: str = "",
        address_line1: str = "",
        address_line2: str = "",
        address_line3: str = "",
        region: str = "",
        province: str = "",
        city: str = "",
        zone: str = "",
        postal_code: str = "",
        reference_identity_number: str = "",
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

        if identity is None:
            from register_id.identity_schema import build_identity

            identity = build_identity(
                uin=uin,
                full_name=full_name,
                date_of_birth=date_of_birth,
                gender=gender,
                email=email,
                phone=phone,
                address_line1=address_line1,
                address_line2=address_line2,
                address_line3=address_line3,
                region=region,
                province=province,
                city=city,
                zone=zone,
                postal_code=postal_code,
                reference_identity_number=reference_identity_number,
            )
        request_body: dict[str, Any] = {
            "registrationId": registration_id or self._make_rid(),
            "status": "ACTIVATED",
            "identity": identity,
            "documents": documents,
            "recordStatus": record_status,
        }
        if face_image:
            request_body["faceImage"] = face_image
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
        self.last_backend = None
        remote_error = None

        # The registration id is stable for this attempt, so a lost response can be retried.
        r = self._send(
            "POST",
            f"{self.base_url}/idrepository/v1/identity/",
            json_body=payload,
            idempotent=True,
        )
        if r is not None and r.status_code in (200, 201):
            try:
                data = r.json()
            except Exception:
                data = {}
            if not data.get("errors"):
                self.last_status = None
                self.last_backend = "mosip-idrepo-rest"
                return True
            remote_error = _enroll_failure_summary(r)
            self.last_status = 502
            logger.warning("IDRepo remote enroll failed: %s", remote_error)
        elif r is None:
            remote_error = f"Failed to connect to MOSIP IDRepo at '{self.base_url}'"
            self.last_status = 503
            logger.warning("IDRepo remote connection failed")
        else:
            remote_error = _enroll_failure_summary(r)
            if self.last_status != 503:
                self.last_status = 502
            logger.warning("IDRepo remote enroll failed: %s", remote_error)

        # 2. In-process fallback
        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                r = client.post("/idrepository/v1/identity/", json=payload)
                if r.status_code in (200, 201):
                    data = r.json()
                    if not data.get("errors"):
                        self.last_status = None
                        self.last_backend = "inprocess-idrepo"
                        return True
                    errors = data.get("errors", [])
                    err_msgs = [e.get("message", str(e)) for e in errors]
                    self.last_error = f"In-process mock IDRepo error: {', '.join(err_msgs)}"
                    self.last_status = 502
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
            r = self._send(
                "GET",
                f"{self.base_url}/idrepository/v1/identity/uin/{uin}",
                params=params,
            )
            if r is not None and r.status_code == 200:
                return _record_from_read_response(r.json(), uin, include_biometrics)
        except Exception as e:
            logger.debug(f"IDRepo remote get failed: {e}")

        # 2. In-process fallback
        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                r = client.get(f"/idrepository/v1/identity/uin/{uin}", params=params)
                if r.status_code == 200:
                    self.last_status = None
                    return _record_from_read_response(r.json(), uin, include_biometrics)
            except Exception as e:
                logger.error(f"In-process IDRepo fallback get failed: {e}")

        return None

    def get_face_templates(self, uin: str) -> list[dict[str, Any]]:
        """
        Load match vectors from GET /ida/v1/face-template/uin/{uin}.

        The mock omits embeddings unless this call asks for them. Remote is
        tried first, then the in-process mock. An empty list means the UIN has
        no templates (or both calls failed).
        """
        params = {"includeBiometrics": "true"}
        try:
            r = self._send(
                "GET",
                f"{self.base_url}/ida/v1/face-template/uin/{uin}",
                params=params,
            )
            if r is not None and r.status_code == 200:
                return _templates_from_body(r.json())
        except Exception as e:
            logger.debug(f"IDRepo remote face-template get failed: {e}")

        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                r = client.get(f"/ida/v1/face-template/uin/{uin}", params=params)
                if r.status_code == 200:
                    self.last_status = None
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
            r = self._send(
                "GET",
                f"{self.base_url}/idrepository/v1/identity/",
                params={"limit": limit},
            )
            if r is not None and r.status_code == 200:
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
                    self.last_status = None
                    data = r.json()
                    rows = data.get("response", [])
                    return [_summary_from_item(item) for item in rows]
            except Exception as e:
                logger.error(f"In-process IDRepo fallback list failed: {e}")

        return []

    def _exchange(self, method: str, path: str, payload: dict | None = None) -> bool:
        """Send one mutating call, then the in-process mock if the remote call fails."""
        self.last_error = None
        self.last_backend = None
        remote_error = None
        url = f"{self.base_url}{path}"
        request_kwargs: dict[str, Any] = {"timeout": _http_timeout(), "headers": self._headers()}
        if payload is not None:
            request_kwargs["json"] = payload

        try:
            response = requests.request(method, url, **request_kwargs)
            if response.status_code in (200, 201):
                data = response.json()
                if not data.get("errors"):
                    self.last_backend = "mosip-idrepo-rest"
                    return True
            remote_error = _failure_message(response)
            logger.warning(f"IDRepo remote {method} {path} failed: {remote_error}")
        except Exception as exc:
            self.last_status = 503
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
                        self.last_status = None
                        self.last_backend = "inprocess-idrepo"
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
        _idrepo_client = IDRepoClient(enable_inprocess_fallback=inprocess_fallback_enabled())
    return _idrepo_client
