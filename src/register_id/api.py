"""
FastAPI REST API Router for the register_id submodule.

Exposes endpoints for citizen enrollment, ISO 30107-3 PAD liveness,
1:1 biometric matching, and registry listing.
"""

import json
import logging
from fastapi import APIRouter, HTTPException
from register_id.cbeff import build_cbeff_xml, extract_jpeg_bytes
from register_id.idrepo import get_idrepo_client
from register_id.keycloak import get_keycloak_client
from register_id.liveness import evaluate_liveness
from register_id.matcher import match_embeddings
from register_id.models import (
    AuthRequest,
    AuthResponse,
    CitizenSummary,
    EnrollRequest,
    LivenessChallenge,
    LivenessRequest,
    LivenessResponse,
)
from register_id.liveness import create_liveness_challenge, evaluate_liveness

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["register_id"])


@router.get("/idgenerator/uin")
def generate_uin_endpoint():
    """
    Allocates a fresh sovereign citizen UIN via the MOSIP IDRepo service interface.
    """
    idrepo = get_idrepo_client()
    uin = idrepo.generate_uin()
    return {"uin": uin}


@router.post("/liveness/challenge", response_model=LivenessChallenge)
def create_liveness_challenge_endpoint():
    """
    Issues an ephemeral challenge nonce for ISO/IEC 30107-3 Level 2 anti-replay protection.
    """
    return create_liveness_challenge()


@router.get("/citizens", response_model=list[CitizenSummary])
def list_citizens():
    """
    Returns recently enrolled citizens from the MOSIP IDRepo REST interface.
    """
    idrepo = get_idrepo_client()
    citizens = idrepo.list_identities(limit=50)
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
    Retrieves full citizen demographic record by UIN via MOSIP IDRepo REST interface.
    """
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(uin)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{uin}' not found in IDRepo.")
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
    Enrolls a citizen face through the MOSIP IDRepo REST interface and provisions Keycloak IAM:
    1. Extracts JPEG image and serializes into ISO 19794-5 / ISO 19785-3 CBEFF XML.
    2. Calls MOSIP IDRepo POST /idrepository/v1/identity/ with official JSON envelope.
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

    # 2. Persist to IDRepo via MOSIP REST Interface
    saved = idrepo.add_identity(
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
        "message": "Citizen face enrolled successfully via MOSIP IDRepo interface",
        "uin": req.uin,
        "fullName": req.fullName,
        "backend": "mosip-idrepo-rest",
        "cbeffGenerated": cbeff_xml is not None,
        "keycloakProvisioned": keycloak_ok,
    }


@router.post("/authenticate", response_model=AuthResponse)
def authenticate_citizen_endpoint(req: AuthRequest):
    """
    MOSIP BioSDK SPI Contract: IBioApi.match() (1:1 Biometric Verification)
    Fetches citizen gallery template from IDRepo REST API and compares with live probe.
    """
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(req.uin)
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
