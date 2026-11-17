"""
FastAPI REST API Router for the register_id submodule.

Exposes endpoints for citizen enrollment, ISO 30107-3 PAD liveness,
1:1 biometric matching, and registry listing.
"""

import logging
import math

from fastapi import APIRouter, Header, HTTPException
from register_id.access import CUSTODIAN_ROLES, DEMOGRAPHIC_ROLES, require_role
from register_id.audit import list_events, record_event
from register_id.cbeff import build_cbeff_xml, extract_jpeg_bytes
from register_id.embedder import embed_face_image
from register_id.face_check import assess_capture, compare_probe, may_store_biometric_record
from register_id.idrepo import get_idrepo_client
from register_id.keycloak import get_keycloak_client
from register_id.liveness import create_liveness_challenge, evaluate_liveness
from register_id.models import (
    AuthRequest,
    AuthResponse,
    CitizenSummary,
    CredentialRequest,
    CredentialResponse,
    DemographicsUpdate,
    EnrollRequest,
    LivenessChallenge,
    LivenessRequest,
    LivenessResponse,
    LoginDisabledUpdate,
    SweepChallenge,
)
from register_id.sweep import assess_sweep, create_sweep_challenge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["register_id"])


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


def _require_operator(authorization: str | None, allowed: frozenset[str]) -> str:
    decision = require_role(authorization, allowed)
    if not decision.ok or decision.role is None:
        raise HTTPException(status_code=decision.status_code or 401, detail=decision.reason)
    return decision.role


def _audit(kind: str, actor: str, uin: str, result: str, detail: str) -> None:
    record_event(
        {
            "kind": kind,
            "actor": actor,
            "uin": uin,
            "result": result,
            "detail": detail,
        }
    )


@router.get("/audit")
def read_audit(
    authorization: str | None = Header(default=None),
    limit: int = 50,
):
    """Operator audit trail. Records omit images and passwords."""
    _require_operator(authorization, DEMOGRAPHIC_ROLES)
    return list_events(limit)


@router.get("/citizens", response_model=list[CitizenSummary])
def list_citizens(authorization: str | None = Header(default=None)):
    """
    Returns recently enrolled citizens from the MOSIP IDRepo REST interface.
    """
    _require_operator(authorization, DEMOGRAPHIC_ROLES)
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
def get_citizen(uin: str, authorization: str | None = Header(default=None)):
    """
    Retrieves a citizen demographic record by UIN. Face bytes stay off this read.
    """
    actor = _require_operator(authorization, DEMOGRAPHIC_ROLES)
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(uin, include_biometrics=False)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{uin}' not found in IDRepo.")
    _audit("operator", actor, uin, "success", "read demographics")
    return {
        "uin": citizen["uin"],
        "fullName": citizen["full_name"],
        "email": citizen.get("email"),
        "status": citizen.get("status"),
        "loginDisabled": citizen.get("login_disabled"),
        "createdAt": str(citizen.get("created_at")),
    }


@router.post("/citizens/{uin}/demographics")
def update_citizen_demographics(
    uin: str,
    body: DemographicsUpdate,
    authorization: str | None = Header(default=None),
):
    actor = _require_operator(authorization, CUSTODIAN_ROLES)
    idrepo = get_idrepo_client()
    saved = idrepo.update_demographics(uin, body.fullName, body.email)
    if not saved:
        _audit("operator", actor, uin, "failure", "demographics update failed")
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{uin}' was not updated.")
    _audit("operator", actor, uin, "success", "demographics updated")
    return {"uin": uin, "fullName": body.fullName, "email": body.email}


@router.post("/citizens/{uin}/login-disabled")
def set_citizen_login_disabled(
    uin: str,
    body: LoginDisabledUpdate,
    authorization: str | None = Header(default=None),
):
    actor = _require_operator(authorization, CUSTODIAN_ROLES)
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(uin, include_biometrics=False)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{uin}' not found in IDRepo.")
    keycloak = get_keycloak_client()
    result = keycloak.set_login_enabled(
        uin=uin,
        email=citizen.get("email") or "",
        enabled=not body.disabled,
    )
    if not result.ok:
        _audit("operator", actor, uin, "failure", "keycloak login flag was not changed")
        raise HTTPException(status_code=502, detail="Keycloak login was not changed.")
    saved = idrepo.set_login_disabled(uin, body.disabled)
    if not saved:
        _audit("operator", actor, uin, "failure", "registry login flag was not changed")
        raise HTTPException(status_code=502, detail="Registry login flag was not changed.")
    _audit("operator", actor, uin, "success", "login disabled" if body.disabled else "login enabled")
    return {"uin": uin, "loginDisabled": body.disabled}


@router.post("/citizens/{uin}/delete-face")
def delete_citizen_face(uin: str, authorization: str | None = Header(default=None)):
    actor = _require_operator(authorization, CUSTODIAN_ROLES)
    idrepo = get_idrepo_client()
    saved = idrepo.delete_face(uin)
    if not saved:
        _audit("operator", actor, uin, "failure", "face delete failed")
        raise HTTPException(status_code=404, detail=f"Face for UIN '{uin}' was not deleted.")
    _audit("operator", actor, uin, "success", "face deleted")
    return {"uin": uin, "faceDeleted": True}


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

    try:
        jpeg_bytes = extract_jpeg_bytes(req.faceImage)
        cbeff_xml = build_cbeff_xml(uin=req.uin, jpeg_bytes=jpeg_bytes)
    except Exception:
        _audit("enroll", "citizen", req.uin, "failure", "image packaging failed")
        raise HTTPException(
            status_code=422,
            detail="Image could not be packaged. Nothing was stored.",
        )

    # The hash templates are a duplicate-byte check on a draft. They are not a
    # biometric of record: presentation has not passed and the engine cannot
    # identify a face, so status stays draft.
    record_status = "biometric" if may_store_biometric_record(False, False) else "draft"
    templates = _templates_for_enrollment(req)
    saved = idrepo.add_identity(
        uin=req.uin,
        full_name=req.fullName,
        email=req.email,
        face_image=req.faceImage,
        cbeff_xml=cbeff_xml,
        templates=templates,
        status=record_status,
    )
    if not saved:
        error_msg = getattr(idrepo, "last_error", None) or "Failed to persist identity in MOSIP IDRepo"
        logger.error("Enrollment failed in IDRepo")
        _audit("enroll", "citizen", req.uin, "failure", "idrepo write failed")
        raise HTTPException(
            status_code=502,
            detail=f"MOSIP IDRepo enrollment failed: {error_msg}",
        )

    purpose = " ".join(req.consent.purpose.split())[:80]
    _audit(
        "enroll",
        "citizen",
        req.uin,
        "success",
        f"draft stored; consent {req.consent.language} at {int(req.consent.acceptedAt)}; {purpose}",
    )
    return {
        "status": "SUCCESS",
        "message": "Citizen face stored as a draft via MOSIP IDRepo interface",
        "uin": req.uin,
        "fullName": req.fullName,
        "backend": "mosip-idrepo-rest",
        "cbeffGenerated": True,
        "recordStatus": record_status,
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
    result = keycloak.provision_citizen(
        uin=req.uin,
        full_name=citizen.get("full_name") or "",
        email=citizen.get("email") or "",
        password=req.password,
    )
    if not result.ok:
        _audit("credential", "citizen", req.uin, "failure", "keycloak did not store the login")
        raise HTTPException(status_code=502, detail="Keycloak did not store the login.")
    _audit("credential", "citizen", req.uin, "success", "keycloak user ready")
    return CredentialResponse(
        status="SUCCESS",
        uin=req.uin,
        keycloakProvisioned=True,
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

    probe_image = req.liveImage
    client_yaws = None
    if req.liveViews:
        front = next(sample for sample in req.liveViews if sample.sector == "front")
        probe_image = front.image
        client_yaws = [sample.yaw for sample in req.liveViews]
    capture = assess_capture([probe_image] if probe_image else [], client_yaws)
    match = compare_probe([], [])
    if probe_image:
        try:
            probe_vector = embed_face_image(probe_image)
            stored_rows = idrepo.get_face_templates(req.uin)
            stored_vectors = [row["embedding"] for row in stored_rows if "embedding" in row]
            match = compare_probe(stored_vectors, probe_vector)
        except ValueError:
            match = compare_probe([], [])

    _audit(
        "authenticate",
        "citizen",
        req.uin,
        "success" if verified else "failure",
        "sweep submission accepted" if verified else "sweep submission rejected",
    )
    return AuthResponse(
        status="SUCCESS" if verified else "FAILED",
        verified=verified,
        isFaceMatch=match.is_face_match,
        livenessPassed=capture.presentation_passed,
        euclideanDistance=match.distance,
        matchScore=match.score,
        livenessScore=None,
        threshold=match.threshold,
        citizen={"uin": citizen["uin"]},
        jwtToken=None,
        message=assessment.message,
        sweepAccepted=assessment.accepted,
        yawSource=assessment.yaw_source if not capture.yaw_measured else "server",
    )
