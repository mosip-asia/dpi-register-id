"""
HTTP REST Client for MOSIP Identity Repository (IDRepo).

Strictly communicates with the MOSIP IDRepo REST API interface:
- POST /idrepository/v1/identity/ (Standard MOSIP JSON envelope + CBEFF XML document)
- GET /idrepository/v1/identity/uin/{uin}
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
        face_embedding: list[float] | None = None,
        cbeff_xml: str | None = None,
    ) -> bool:
        """
        Enrolls or updates an identity in MOSIP IDRepo via POST /idrepository/v1/identity/.
        Packages payload into the official MOSIP envelope.
        """
        documents = []
        if cbeff_xml:
            cbeff_b64url = base64.urlsafe_b64encode(cbeff_xml.encode("utf-8")).decode("utf-8")
            documents.append({
                "category": "individualBiometrics",
                "value": cbeff_b64url,
            })

        payload = {
            "id": "mosip.id.create",
            "version": "v1",
            "requesttime": self._now_iso(),
            "metadata": {},
            "request": {
                "registrationId": self._make_rid(),
                "status": "ACTIVATED",
                "identity": {
                    "UIN": uin,
                    "fullName": [{"language": "eng", "value": full_name}],
                    "email": email,
                    "faceImage": face_image,
                    "faceEmbedding": face_embedding,
                },
                "documents": documents,
            },
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
                errors = data.get("errors", [])
                err_msgs = [e.get("message", str(e)) for e in errors]
                remote_error = f"MOSIP IDRepo error: {', '.join(err_msgs)}"
            else:
                remote_error = f"MOSIP IDRepo returned HTTP {r.status_code}: {r.text[:200]}"
            logger.warning(f"IDRepo remote enroll failed: {remote_error}")
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

    def get_identity(self, uin: str) -> dict[str, Any] | None:
        """
        Retrieves a citizen identity from MOSIP IDRepo via GET /idrepository/v1/identity/uin/{uin}.
        """
        # 1. Attempt remote HTTP call
        try:
            r = requests.get(f"{self.base_url}/idrepository/v1/identity/uin/{uin}", timeout=3)
            if r.status_code == 200:
                data = r.json()
                resp = data.get("response", {})
                identity = resp.get("identity", {})
                documents = resp.get("documents", [])

                full_name_raw = identity.get("fullName", "")
                if isinstance(full_name_raw, list) and len(full_name_raw) > 0:
                    full_name = full_name_raw[0].get("value", "")
                else:
                    full_name = str(full_name_raw)

                # Extract CBEFF
                cbeff_xml = None
                for doc in documents:
                    if doc.get("category") == "individualBiometrics":
                        b64val = doc.get("value", "")
                        try:
                            padded = b64val + "=" * (-len(b64val) % 4)
                            cbeff_xml = base64.urlsafe_b64decode(padded).decode("utf-8")
                        except Exception:
                            cbeff_xml = b64val

                return {
                    "uin": identity.get("UIN", uin),
                    "full_name": full_name,
                    "email": identity.get("email"),
                    "face_image": identity.get("faceImage"),
                    "face_embedding": identity.get("faceEmbedding"),
                    "cbeff_xml": cbeff_xml,
                    "created_at": identity.get("createdAt"),
                }
        except Exception as e:
            logger.debug(f"IDRepo remote get failed: {e}")

        # 2. In-process fallback
        if self.enable_inprocess_fallback:
            try:
                client = self._get_test_client()
                r = client.get(f"/idrepository/v1/identity/uin/{uin}")
                if r.status_code == 200:
                    data = r.json()
                    resp = data.get("response", {})
                    identity = resp.get("identity", {})
                    documents = resp.get("documents", [])

                    full_name_raw = identity.get("fullName", "")
                    if isinstance(full_name_raw, list) and len(full_name_raw) > 0:
                        full_name = full_name_raw[0].get("value", "")
                    else:
                        full_name = str(full_name_raw)

                    cbeff_xml = None
                    for doc in documents:
                        if doc.get("category") == "individualBiometrics":
                            b64val = doc.get("value", "")
                            try:
                                padded = b64val + "=" * (-len(b64val) % 4)
                                cbeff_xml = base64.urlsafe_b64decode(padded).decode("utf-8")
                            except Exception:
                                cbeff_xml = b64val

                    return {
                        "uin": identity.get("UIN", uin),
                        "full_name": full_name,
                        "email": identity.get("email"),
                        "face_image": identity.get("faceImage"),
                        "face_embedding": identity.get("faceEmbedding"),
                        "cbeff_xml": cbeff_xml,
                        "created_at": identity.get("createdAt"),
                    }
            except Exception as e:
                logger.error(f"In-process IDRepo fallback get failed: {e}")

        return None

    def list_identities(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Retrieves list of recent identities from MOSIP IDRepo via GET /idrepository/v1/identity/.
        """
        # 1. Attempt remote HTTP call
        try:
            r = requests.get(f"{self.base_url}/idrepository/v1/identity/?limit={limit}", timeout=3)
            if r.status_code == 200:
                data = r.json()
                rows = data.get("response", [])
                return [
                    {
                        "uin": item["uin"],
                        "full_name": item["fullName"],
                        "email": item.get("email"),
                        "created_at": item.get("createdAt"),
                    }
                    for item in rows
                ]
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
                    return [
                        {
                            "uin": item["uin"],
                            "full_name": item["fullName"],
                            "email": item.get("email"),
                            "created_at": item.get("createdAt"),
                        }
                        for item in rows
                    ]
            except Exception as e:
                logger.error(f"In-process IDRepo fallback list failed: {e}")

        return []


# Global singleton client
_idrepo_client: IDRepoClient | None = None


def get_idrepo_client() -> IDRepoClient:
    global _idrepo_client
    if _idrepo_client is None:
        _idrepo_client = IDRepoClient()
    return _idrepo_client
