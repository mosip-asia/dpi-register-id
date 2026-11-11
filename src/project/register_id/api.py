"""
FastAPI REST API Router for the register_id submodule.

Exposes endpoints for citizen enrollment, ISO 30107-3 PAD liveness,
1:1 biometric matching, and registry listing.
"""

import json
import logging
from fastapi import APIRouter, HTTPException
from project.register_id.cbeff import build_cbeff_xml, extract_jpeg_bytes
from project.register_id.idrepo import get_idrepo_client
from project.register_id.keycloak import get_keycloak_client
from project.register_id.liveness import evaluate_liveness
from project.register_id.matcher import match_embeddings
from project.register_id.models import (
    AuthRequest,
    AuthResponse,
    CitizenSummary,
    EnrollRequest,
    LivenessRequest,
    LivenessResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["register_id"])


@router.get("/citizens", response_model=list[CitizenSummary])
def list_citizens():
    """
    Returns recently enrolled citizens from the IDRepo.
    """
    idrepo = get_idrepo_client()
    citizens = idrepo.list_citizens(limit=50)
    return [
        CitizenSummary(
            uin=c["uin"],
            fullName=c["full_name"],
            email=c.get("email"),
            createdAt=str(c.get("created_at")),
        )
        for c in citizens
    ]


@router.get("/citizens/{uin}")
def get_citizen(uin: str):
    """
    Retrieves full citizen demographic record by UIN.
    """
    idrepo = get_idrepo_client()
    citizen = idrepo.get_citizen(uin)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{uin}' not found.")
    return {
        "uin": citizen["uin"],
        "fullName": citizen["full_name"],
        "email": citizen.get("email"),
        "hasCbeffXml": bool(citizen.get("cbeff_xml")),
        "createdAt": str(citizen.get("created_at")),
    }


@router.post("/checkLiveness", response_model=LivenessResponse)
def check_liveness_endpoint(req: LivenessRequest):
    """
    MOSIP BioSDK SPI Contract: IBioApi.checkLiveness() (ISO/IEC 30107-3 PAD)
    Evaluates Eye Aspect Ratio (EAR) dynamics and blink events.
    """
    return evaluate_liveness(req)


@router.post("/enroll")
def enroll_citizen_endpoint(req: EnrollRequest):
    """
    Enrolls a citizen face into MOSIP IDRepo and provisions Keycloak IAM:
    1. Extracts JPEG image and serializes into ISO 19794-5 / ISO 19785-3 CBEFF XML.
    2. Stores demographics, face embedding, and CBEFF in IDRepo database.
    3. Asynchronously provisions the citizen account in Keycloak IAM for eSignet OIDC login.
    """
    idrepo = get_idrepo_client()

    # 1. Build CBEFF XML from JPEG payload
    cbeff_xml = None
    try:
        jpeg_bytes = extract_jpeg_bytes(req.faceImage)
        cbeff_xml = build_cbeff_xml(uin=req.uin, jpeg_bytes=jpeg_bytes)
    except Exception as e:
        logger.warning(f"Could not construct CBEFF XML (storing raw data): {e}")

    # 2. Persist to IDRepo
    saved = idrepo.save_citizen(
        uin=req.uin,
        full_name=req.fullName,
        email=req.email,
        face_image=req.faceImage,
        face_embedding=req.faceEmbedding,
        cbeff_xml=cbeff_xml,
    )
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save citizen record into IDRepo.")

    # 3. Synchronize with Keycloak IAM
    keycloak = get_keycloak_client()
    keycloak_ok = keycloak.provision_citizen(
        uin=req.uin,
        full_name=req.fullName,
        email=req.email,
        password=req.password,
    )

    return {
        "status": "SUCCESS",
        "message": "Citizen face enrolled successfully into MOSIP IDRepo",
        "uin": req.uin,
        "fullName": req.fullName,
        "backend": idrepo.active_backend,
        "cbeffGenerated": cbeff_xml is not None,
        "keycloakProvisioned": keycloak_ok,
    }


@router.post("/authenticate", response_model=AuthResponse)
def authenticate_citizen_endpoint(req: AuthRequest):
    """
    MOSIP BioSDK SPI Contract: IBioApi.match() (1:1 Biometric Verification)
    Compares stored gallery face descriptor with live probe and enforces ISO 30107-3 PAD.
    """
    idrepo = get_idrepo_client()
    citizen = idrepo.get_citizen(req.uin)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{req.uin}' not found in registry.")

    stored_embedding_raw = citizen["face_embedding"]
    if isinstance(stored_embedding_raw, str):
        stored_embedding = json.loads(stored_embedding_raw)
    else:
        stored_embedding = stored_embedding_raw

    # 1:1 Metric Comparison (Euclidean distance threshold = 0.50)
    is_match, distance, match_score = match_embeddings(
        stored=stored_embedding,
        probe=req.liveEmbedding,
        threshold=0.50,
    )

    # Both Biometric Match AND Liveness PAD must pass
    verified = is_match and req.livenessPassed

    jwt_token = (
        f"eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.mosip_verified_citizen_{citizen['uin']}.mock_sig"
        if verified
        else None
    )

    return AuthResponse(
        status="SUCCESS" if verified else "FAILED",
        verified=verified,
        isFaceMatch=is_match,
        livenessPassed=req.livenessPassed,
        euclideanDistance=distance,
        matchScore=match_score,
        livenessScore=req.livenessScore,
        threshold=0.50,
        citizen={
            "uin": citizen["uin"],
            "fullName": citizen["full_name"],
            "email": citizen.get("email"),
        },
        jwtToken=jwt_token,
    )
