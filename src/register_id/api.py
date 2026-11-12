"""
FastAPI REST API Router for the register_id submodule.

Exposes endpoints for citizen enrollment, ISO 30107-3 PAD liveness,
1:1 biometric matching, and registry listing.
"""

import logging

from fastapi import APIRouter, HTTPException
from register_id.cbeff import build_cbeff_xml, extract_jpeg_bytes
from register_id.embedder import embed_face_image
from register_id.idrepo import get_idrepo_client
from register_id.keycloak import get_keycloak_client
from register_id.liveness import create_liveness_challenge, evaluate_liveness
from register_id.matcher import match_embeddings
from register_id.models import (
    AuthRequest,
    AuthResponse,
    CitizenSummary,
    CredentialRequest,
    CredentialResponse,
    EnrollRequest,
    LivenessChallenge,
    LivenessRequest,
    LivenessResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["register_id"])

MATCH_THRESHOLD = 0.50


def _embed_or_422(image: str) -> list[float]:
    try:
        return embed_face_image(image)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    Enrolls a citizen face through the MOSIP IDRepo REST interface.

    The frontal template is computed from the image bytes. A client-supplied
    embedding is not accepted. Keycloak login is a separate POST /api/credentials call.
    """
    idrepo = get_idrepo_client()

    cbeff_xml = None
    try:
        jpeg_bytes = extract_jpeg_bytes(req.faceImage)
        cbeff_xml = build_cbeff_xml(uin=req.uin, jpeg_bytes=jpeg_bytes)
    except Exception as e:
        logger.warning(f"Could not construct CBEFF XML (storing raw data): {e}")

    templates = [{"sector": "front", "embedding": _embed_or_422(req.faceImage)}]
    saved = idrepo.add_identity(
        uin=req.uin,
        full_name=req.fullName,
        email=req.email,
        face_image=req.faceImage,
        cbeff_xml=cbeff_xml,
        templates=templates,
    )
    if not saved:
        error_msg = getattr(idrepo, "last_error", None) or "Failed to persist identity in MOSIP IDRepo"
        logger.error(f"Enrollment failed in IDRepo: {error_msg}")
        raise HTTPException(
            status_code=502,
            detail=f"MOSIP IDRepo enrollment failed: {error_msg}",
        )

    return {
        "status": "SUCCESS",
        "message": "Citizen face enrolled successfully via MOSIP IDRepo interface",
        "uin": req.uin,
        "fullName": req.fullName,
        "backend": "mosip-idrepo-rest",
        "cbeffGenerated": cbeff_xml is not None,
    }


@router.post("/credentials", response_model=CredentialResponse)
def issue_credentials_endpoint(req: CredentialRequest):
    """
    Issues the Keycloak login for an already enrolled citizen.

    The password is sent only to Keycloak. It is never written to IDRepo.
    """
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(req.uin)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{req.uin}' not found in IDRepo.")

    keycloak = get_keycloak_client()
    keycloak_ok = keycloak.provision_citizen(
        uin=req.uin,
        full_name=citizen.get("full_name") or "",
        email=citizen.get("email") or "",
        password=req.password,
    )
    return CredentialResponse(
        status="SUCCESS",
        uin=req.uin,
        keycloakProvisioned=keycloak_ok,
    )


@router.post("/authenticate", response_model=AuthResponse)
def authenticate_citizen_endpoint(req: AuthRequest):
    """
    1:1 check of the live probe against the frontal template in the IDA table.
    """
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(req.uin)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{req.uin}' not found in registry.")

    templates = idrepo.get_face_templates(req.uin)
    front = next((item["embedding"] for item in templates if item["sector"] == "front"), None)
    if not isinstance(front, list):
        raise HTTPException(status_code=404, detail=f"No frontal template stored for UIN '{req.uin}'.")

    is_match, distance, match_score = match_embeddings(
        stored=front,
        probe=req.liveEmbedding,
        threshold=MATCH_THRESHOLD,
    )
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
        threshold=MATCH_THRESHOLD,
        citizen={
            "uin": citizen["uin"],
            "fullName": citizen["full_name"],
            "email": citizen.get("email"),
        },
        jwtToken=jwt_token,
    )
