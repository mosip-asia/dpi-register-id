"""
FastAPI application for Mock MOSIP IDRepo REST API.

Implements the official MOSIP specifications:
- POST /idrepository/v1/identity/ (Standard MOSIP envelope + CBEFF XML document)
- GET /idrepository/v1/identity/uin/{uin}
- PATCH /idrepository/v1/identity/uin/{uin} (name, email, login-disabled flag)
- DELETE /idrepository/v1/identity/uin/{uin}/biometrics
- GET /idrepository/v1/identity/ (List/query identities)
- GET /v1/idgenerator/uin (Sovereign UIN allocation)
- POST /v1/authmanager/authenticate/clientidsecretkey
- GET /health
"""

import base64
import logging
import random
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from mock.idrepo.storage import IDRepoStorage

logger = logging.getLogger(__name__)

storage = IDRepoStorage()

idrepo_app = FastAPI(title="MOSIP Identity Repository (Mock Service)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_RECORD_STATUSES = frozenset({"draft", "biometric"})


def _full_name_value(full_name_raw) -> str:
    if isinstance(full_name_raw, list) and len(full_name_raw) > 0:
        return str(full_name_raw[0].get("value", ""))
    if isinstance(full_name_raw, str):
        return full_name_raw
    return ""


def _record_status(req: dict) -> str:
    """Draft unless the caller explicitly passes biometric. ACTIVATED is not a record status."""
    raw = req.get("recordStatus")
    if raw is None or raw == "":
        return "draft"
    if raw not in _RECORD_STATUSES:
        raise HTTPException(
            status_code=400,
            detail={
                "id": "mosip.id.create",
                "version": "v1",
                "errors": [{
                    "errorCode": "IDR-IDC-005",
                    "message": "recordStatus must be 'draft' or 'biometric'",
                }],
            },
        )
    return raw


def _not_found(uin: str, message: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "id": "mosip.id.read",
            "version": "v1",
            "response": None,
            "errors": [{
                "errorCode": "IDR-IDC-002",
                "message": message or f"Identity record not found for UIN '{uin}'",
            }],
        },
    )


def _identity_payload(record: dict, include_biometrics: bool) -> tuple[dict, list]:
    identity = {
        "UIN": record["uin"],
        "fullName": [{"language": "eng", "value": record["full_name"]}],
        "email": record.get("email"),
        "createdAt": str(record.get("created_at")),
        "recordStatus": record.get("status") or "draft",
        "loginDisabled": bool(record.get("login_disabled")),
    }
    documents: list = []
    if not include_biometrics:
        return identity, documents

    identity["faceImage"] = record.get("face_image")
    cbeff_xml = record.get("cbeff_xml")
    if cbeff_xml:
        cbeff_b64url = base64.urlsafe_b64encode(cbeff_xml.encode("utf-8")).decode("utf-8")
        documents.append({
            "category": "individualBiometrics",
            "value": cbeff_b64url,
        })
    return identity, documents


@idrepo_app.get("/health")
def health_check():
    return {
        "status": "UP",
        "service": "mosip-id-repository",
        "backend": storage.active_backend,
        "timestamp": _now_iso(),
    }


@idrepo_app.get("/v1/idgenerator/uin")
def generate_uin():
    """
    Generates a fresh 10-digit citizen UIN conforming to MOSIP specifications.
    """
    uin = str(random.randint(2000000000, 9999999999))
    return {
        "id": "mosip.idgenerator.uin",
        "version": "v1",
        "responsetime": _now_iso(),
        "metadata": None,
        "response": {
            "uin": uin,
        },
        "errors": None,
    }


@idrepo_app.post("/v1/authmanager/authenticate/clientidsecretkey")
def authenticate_service_client(payload: dict):
    """
    MOSIP Auth Manager: clientidsecretkey authentication.
    Issues mock service token for mosip-idrepo-client.
    """
    return {
        "id": "io.mosip.auth",
        "version": "1.0",
        "responsetime": _now_iso(),
        "response": {
            "status": "SUCCESS",
            "token": "mock-mosip-service-token-" + str(random.randint(100000, 999999)),
            "message": "Authenticated successfully",
        },
        "errors": None,
    }


@idrepo_app.post("/idrepository/v1/identity/")
@idrepo_app.post("/idrepository/v1/identity")
def add_identity(payload: dict):
    """
    MOSIP IDRepo AddIdentity endpoint.
    Expects standard MOSIP envelope:
    {
      "id": "mosip.id.create",
      "version": "v1",
      "request": {
         "registrationId": "...",
         "status": "ACTIVATED",
         "identity": { "UIN": "...", "fullName": [...], "email": "...", "faceImage": "..." },
         "templates": [ { "sector": "front", "embedding": [0.1, "..."], "engine": "face-api-128" } ],
         "documents": [ { "category": "individualBiometrics", "value": "base64url..." } ]
      }
    }
    """
    req = payload.get("request", {})
    identity = req.get("identity", {})
    documents = req.get("documents", [])

    uin = identity.get("UIN")
    if not uin:
        raise HTTPException(
            status_code=400,
            detail={
                "id": "mosip.id.create",
                "version": "v1",
                "errors": [{"errorCode": "IDR-IDC-001", "message": "Missing mandatory field 'UIN'"}],
            },
        )

    # Extract full name (string or localized array [{"language":"eng", "value":"..."}])
    full_name = _full_name_value(identity.get("fullName")) or "Unknown Citizen"
    record_status = _record_status(req)

    email = identity.get("email")
    face_image = identity.get("faceImage")
    # Client faceEmbedding / faceViews are ignored. Vectors arrive as request.templates.
    templates = req.get("templates")

    # Extract CBEFF XML from individualBiometrics document
    cbeff_xml = None
    for doc in documents:
        if doc.get("category") == "individualBiometrics":
            raw_val = doc.get("value", "")
            try:
                padded = raw_val + "=" * (-len(raw_val) % 4)
                decoded_bytes = base64.urlsafe_b64decode(padded)
                cbeff_xml = decoded_bytes.decode("utf-8", errors="replace")
            except Exception as e:
                logger.warning(f"Failed to decode CBEFF document: {e}")
                cbeff_xml = raw_val

    saved = storage.save_identity(
        uin=str(uin),
        full_name=full_name,
        email=email,
        face_image=face_image,
        cbeff_xml=cbeff_xml,
        status=record_status,
    )

    if saved and templates is not None:
        if not isinstance(templates, list):
            raise HTTPException(
                status_code=400,
                detail={
                    "id": "mosip.id.create",
                    "version": "v1",
                    "errors": [{"errorCode": "IDR-IDC-004", "message": "templates must be a list"}],
                },
            )
        saved = storage.save_face_templates(str(uin), templates)

    if not saved:
        raise HTTPException(
            status_code=500,
            detail={
                "id": "mosip.id.create",
                "version": "v1",
                "errors": [{"errorCode": "IDR-IDC-500", "message": "Failed to persist identity record"}],
            },
        )

    return {
        "id": "mosip.id.create",
        "version": "v1",
        "responsetime": _now_iso(),
        "metadata": None,
        "response": {
            "status": req.get("status", "ACTIVATED"),
            "entity": "identity",
        },
        "errors": None,
    }


@idrepo_app.get("/idrepository/v1/identity/uin/{uin}")
def get_identity_by_uin(uin: str, includeBiometrics: bool = False):
    """
    MOSIP IDRepo GetIdentity endpoint.

    Face image and CBEFF stay off the response unless includeBiometrics=true.
    A caller that can reach this port otherwise receives demographics only.
    """
    record = storage.get_identity(uin)
    if not record:
        raise _not_found(uin)

    identity, documents = _identity_payload(record, include_biometrics=includeBiometrics)
    return {
        "id": "mosip.id.read",
        "version": "v1",
        "responsetime": _now_iso(),
        "metadata": None,
        "response": {
            "status": "ACTIVATED",
            "identity": identity,
            "documents": documents,
        },
        "errors": None,
    }


@idrepo_app.patch("/idrepository/v1/identity/uin/{uin}")
@idrepo_app.post("/idrepository/v1/identity/uin/{uin}")
def update_identity(uin: str, payload: dict):
    """
    Correct demographics and/or the operator login-disabled flag.
    Face bytes and templates are left in place.
    """
    if storage.get_identity(uin) is None:
        raise _not_found(uin)

    req = payload.get("request") or {}
    if "identity" not in req and "loginDisabled" not in req:
        raise HTTPException(
            status_code=400,
            detail={
                "id": "mosip.id.update",
                "version": "v1",
                "errors": [{
                    "errorCode": "IDR-IDC-006",
                    "message": "request.identity or request.loginDisabled is required",
                }],
            },
        )

    if "identity" in req:
        identity = req.get("identity") or {}
        full_name = _full_name_value(identity.get("fullName"))
        if not full_name.strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "id": "mosip.id.update",
                    "version": "v1",
                    "errors": [{
                        "errorCode": "IDR-IDC-007",
                        "message": "fullName is required",
                    }],
                },
            )
        saved = storage.update_demographics(
            uin=str(uin),
            full_name=full_name,
            email=identity.get("email"),
        )
        if not saved:
            raise HTTPException(
                status_code=500,
                detail={
                    "id": "mosip.id.update",
                    "version": "v1",
                    "errors": [{
                        "errorCode": "IDR-IDC-500",
                        "message": "Failed to update demographics",
                    }],
                },
            )

    if "loginDisabled" in req:
        saved = storage.set_login_disabled(str(uin), bool(req.get("loginDisabled")))
        if not saved:
            raise HTTPException(
                status_code=500,
                detail={
                    "id": "mosip.id.update",
                    "version": "v1",
                    "errors": [{
                        "errorCode": "IDR-IDC-500",
                        "message": "Failed to update login-disabled flag",
                    }],
                },
            )

    return {
        "id": "mosip.id.update",
        "version": "v1",
        "responsetime": _now_iso(),
        "metadata": None,
        "response": {"status": "SUCCESS", "entity": "identity"},
        "errors": None,
    }


@idrepo_app.delete("/idrepository/v1/identity/uin/{uin}/biometrics")
def delete_face(uin: str):
    """Drop the face image, CBEFF XML, and face templates. Demographics remain."""
    if not storage.delete_face(str(uin)):
        raise _not_found(uin)
    return {
        "id": "mosip.id.update",
        "version": "v1",
        "responsetime": _now_iso(),
        "metadata": None,
        "response": {"status": "SUCCESS", "entity": "biometrics"},
        "errors": None,
    }


@idrepo_app.get("/ida/v1/face-template/uin/{uin}")
def get_face_templates(uin: str, includeBiometrics: bool = False):
    """
    IDA read path for match vectors. Identity demographics are not included.

    Embeddings stay off the response unless includeBiometrics=true. A UIN with
    an identity row and no such request returns an empty template list. 404
    when the UIN has no identity row, or when templates were requested and none
    are stored.
    """
    record = storage.get_identity(uin)
    if not record:
        raise HTTPException(
            status_code=404,
            detail={
                "id": "mosip.ida.face.read",
                "version": "v1",
                "errors": [
                    {
                        "errorCode": "IDA-FTA-002",
                        "message": f"Face templates not found for UIN '{uin}'",
                    }
                ],
            },
        )
    if not includeBiometrics:
        return {"templates": []}

    templates = storage.get_face_templates(uin)
    if not templates:
        raise HTTPException(
            status_code=404,
            detail={
                "id": "mosip.ida.face.read",
                "version": "v1",
                "errors": [
                    {
                        "errorCode": "IDA-FTA-002",
                        "message": f"Face templates not found for UIN '{uin}'",
                    }
                ],
            },
        )

    return {"templates": [_template_payload(item) for item in templates]}


def _template_payload(item: dict) -> dict:
    payload = {"sector": item["sector"], "embedding": item["embedding"]}
    if item.get("engine"):
        payload["engine"] = item["engine"]
    return payload


@idrepo_app.get("/idrepository/v1/identity/")
@idrepo_app.get("/idrepository/v1/identity")
def list_identities(limit: int = 50):
    """
    Returns list of recently registered identities.
    """
    rows = storage.list_identities(limit=limit)
    return {
        "id": "mosip.id.list",
        "version": "v1",
        "responsetime": _now_iso(),
        "response": [
            {
                "uin": r["uin"],
                "fullName": r["full_name"],
                "email": r.get("email"),
                "createdAt": str(r.get("created_at")),
                "recordStatus": r.get("status") or "draft",
                "loginDisabled": bool(r.get("login_disabled")),
            }
            for r in rows
        ],
        "errors": None,
    }


def run_idrepo_server(host: str = "0.0.0.0", port: int = 8080):
    import uvicorn
    uvicorn.run(idrepo_app, host=host, port=port, log_level="info")
