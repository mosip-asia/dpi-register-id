"""
FastAPI application for Mock MOSIP IDRepo REST API.

Implements the official MOSIP specifications:
- POST /idrepository/v1/identity/ (Standard MOSIP envelope + CBEFF XML document)
- GET /idrepository/v1/identity/uin/{uin}
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
         "templates": [ { "sector": "front", "embedding": [0.1, "..."] } ],
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
    full_name_raw = identity.get("fullName")
    if isinstance(full_name_raw, list) and len(full_name_raw) > 0:
        full_name = full_name_raw[0].get("value", "")
    elif isinstance(full_name_raw, str):
        full_name = full_name_raw
    else:
        full_name = "Unknown Citizen"

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
def get_identity_by_uin(uin: str):
    """
    MOSIP IDRepo GetIdentity endpoint.
    Retrieves citizen demographics and CBEFF individualBiometrics.
    """
    record = storage.get_identity(uin)
    if not record:
        raise HTTPException(
            status_code=404,
            detail={
                "id": "mosip.id.read",
                "version": "v1",
                "response": None,
                "errors": [
                    {
                        "errorCode": "IDR-IDC-002",
                        "message": f"Identity record not found for UIN '{uin}'",
                    }
                ],
            },
        )

    # Format CBEFF as URL-safe base64
    cbeff_xml = record.get("cbeff_xml")
    documents = []
    if cbeff_xml:
        cbeff_b64url = base64.urlsafe_b64encode(cbeff_xml.encode("utf-8")).decode("utf-8")
        documents.append({
            "category": "individualBiometrics",
            "value": cbeff_b64url,
        })

    return {
        "id": "mosip.id.read",
        "version": "v1",
        "responsetime": _now_iso(),
        "metadata": None,
        "response": {
            "status": "ACTIVATED",
            "identity": {
                "UIN": record["uin"],
                "fullName": [{"language": "eng", "value": record["full_name"]}],
                "email": record.get("email"),
                "faceImage": record.get("face_image"),
                "createdAt": str(record.get("created_at")),
            },
            "documents": documents,
        },
        "errors": None,
    }


@idrepo_app.get("/ida/v1/face-template/uin/{uin}")
def get_face_templates(uin: str):
    """
    IDA read path for match vectors. Identity demographics are not included.
    404 when the UIN has no identity row or no stored templates.
    """
    record = storage.get_identity(uin)
    templates = storage.get_face_templates(uin) if record else []
    if not record or not templates:
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

    return {
        "templates": [
            {"sector": item["sector"], "embedding": item["embedding"]}
            for item in templates
        ]
    }


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
            }
            for r in rows
        ],
        "errors": None,
    }


def run_idrepo_server(host: str = "0.0.0.0", port: int = 8080):
    import uvicorn
    uvicorn.run(idrepo_app, host=host, port=port, log_level="info")
