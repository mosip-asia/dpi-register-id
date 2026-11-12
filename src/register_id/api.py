"""
FastAPI REST API Router for the register_id submodule.

Exposes endpoints for citizen enrollment, ISO 30107-3 PAD liveness,
1:1 biometric matching, and registry listing.
"""

import logging
import math

from fastapi import APIRouter, HTTPException
from register_id.cbeff import build_cbeff_xml, extract_jpeg_bytes
from register_id.embedder import embed_face_image
from register_id.idrepo import get_idrepo_client
from register_id.keycloak import get_keycloak_client
from register_id.liveness import create_liveness_challenge, evaluate_liveness
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
    SweepChallenge,
)
from register_id.sweep import assess_sweep, create_sweep_challenge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["register_id"])

MATCH_THRESHOLD = 0.50


def _embed_or_422(image: str) -> list[float]:
    try:
        return embed_face_image(image)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _pose_distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _templates_for_enrollment(req: EnrollRequest) -> list[dict]:
    """
    Build server-side templates from image bytes.

    A head sweep stores one vector per sector. The frontal template is the
    front sample. A single portrait stores sector "front" from faceImage.
    """
    if req.faceViews is not None:
        by_sector: dict[str, list[float]] = {}
        for sample in req.faceViews:
            by_sector[sample.sector] = _embed_or_422(sample.image)

        front = by_sector["front"]
        for sector in ("far-left", "far-right"):
            if _pose_distance(front, by_sector[sector]) < 0.05:
                raise HTTPException(
                    status_code=422,
                    detail=f"{sector} sample is not a distinct pose from the frontal sample",
                )
        return [
            {"sector": sample.sector, "embedding": by_sector[sample.sector]}
            for sample in req.faceViews
        ]

    return [{"sector": "front", "embedding": _embed_or_422(req.faceImage)}]


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


@router.post("/sweep/challenge", response_model=SweepChallenge)
def create_sweep_challenge_endpoint():
    """
    Issues a single-use head-sweep challenge. Blink score is not part of verification.
    """
    return create_sweep_challenge()


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
    Enrolls a citizen face through the MOSIP IDRepo REST interface:
    1. Extracts JPEG image and serializes into ISO 19794-5 / ISO 19785-3 CBEFF XML.
    2. Computes 128-D templates from the image bytes. Client vectors are rejected.
    3. Persists demographics on the identity and templates on the IDA table.

    Keycloak login is a separate POST /api/credentials call. No password is accepted here.
    """
    idrepo = get_idrepo_client()

    cbeff_xml = None
    try:
        jpeg_bytes = extract_jpeg_bytes(req.faceImage)
        cbeff_xml = build_cbeff_xml(uin=req.uin, jpeg_bytes=jpeg_bytes)
    except Exception as e:
        logger.warning(f"Could not construct CBEFF XML (storing raw data): {e}")

    templates = _templates_for_enrollment(req)
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
    Verify a five-pose head sweep bound to an expiring challenge.

    Blink flags on the request are ignored. The hash embedder is not a face
    model, so a passing sweep is a submission check, not an identity match
    and not proof of a live head turn.
    """
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(req.uin)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{req.uin}' not found in registry.")

    assessment = assess_sweep(req.challengeId, req.liveViews)
    verified = assessment.accepted

    return AuthResponse(
        status="SUCCESS" if verified else "FAILED",
        verified=verified,
        isFaceMatch=False,
        livenessPassed=False,
        euclideanDistance=1.0,
        matchScore=0.0,
        livenessScore=0.0,
        threshold=MATCH_THRESHOLD,
        citizen={
            "uin": citizen["uin"],
            "fullName": citizen["full_name"],
            "email": citizen.get("email"),
        },
        jwtToken=None,
        message=assessment.message,
        sweepAccepted=assessment.accepted,
        yawSource=assessment.yaw_source,
    )
