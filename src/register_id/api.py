"""
FastAPI REST API Router for the register_id submodule.

Exposes endpoints for citizen enrollment, ISO 30107-3 PAD liveness,
1:1 biometric matching, and registry listing.

Two enrollment and check paths exist. The image path hashes JPEG bytes and
never reports a face match. The descriptor path takes face-api-128
descriptors from the browser with a report bound to a single-use challenge.
A passed face-api challenge is the presentation check this deployment has.
That path stores the CBEFF document. The hash-only path does not.
"""

import ipaddress
import logging
import math
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request, Response
from pydantic import ValidationError
from register_id.access import (
    ADMIN,
    ADMIN_ROLES,
    CORRECT_ROLES,
    OFFICER,
    VIEW_ROLES,
    authorize,
)
from register_id.activity_grant import issue_grant, resolve_grant
from register_id.enroll_limit import (
    EnrollLimitExceeded,
    EnrollLimitUnavailable,
    ensure_enroll_allowed,
    record_enroll_success,
)
from register_id.enroll_ticket import (
    consume_for_credentials,
    get_ticket,
    issue_ticket,
    remember_allocation,
    take_credential,
    ticket_ttl,
)
from register_id.identity_schema import build_identity
from register_id.application import (
    ApplicationCreated,
    ApplicationCreate,
    create_application,
    validation_detail,
)
from register_id.application_store import ApplicationStoreError, get_application_store
from register_id.audit import list_events, project_for_citizen, record_event, search_events, tries_used
from register_id.locks import is_locked, set_locked
from register_id.reasons import CODES, TRY_CODES, citizen_message, officer_text, rough_device, uses_try
from register_id.cbeff import build_cbeff_xml, extract_jpeg_bytes
from register_id.email import EmailResult, decode_id_card_png, send_enrollment_email
from register_id.embedder import ENGINE_NAME, embed_face_image
from register_id.face_check import (
    assess_capture,
    compare_descriptor,
    compare_probe,
    may_store_biometric_record,
)
from register_id.face_descriptor import (
    DESCRIPTOR_LENGTH,
    DESCRIPTOR_MATCH_THRESHOLD,
    FACE_DESCRIPTOR_ENGINE,
    assess_client_liveness,
    create_face_challenge,
    descriptors_consistent,
    validate_descriptor,
)
from register_id.idrepo import get_idrepo_client
from register_id.idrepo_client import IDRepoClient
from register_id.keycloak import get_keycloak_client
from register_id import staff as staff_directory
from register_id.liveness import create_liveness_challenge, evaluate_liveness
from register_id.models import (
    AuthRequest,
    AuthResponse,
    CaptureAttempt,
    CitizenLock,
    CitizenSummary,
    CredentialRequest,
    CredentialResponse,
    DemographicsUpdate,
    EnrollRequest,
    FaceChallenge,
    FaceChallengeRequest,
    LivenessChallenge,
    LivenessRequest,
    LivenessResponse,
    LoginDisabledUpdate,
    NotMeReport,
    ReasonBody,
    StaffCreate,
    StaffRoleUpdate,
    SweepChallenge,
)
from register_id.sweep import assess_sweep, create_sweep_challenge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["register_id"])

# Officers and admins. A reader token is not enough for lock or report actions.
_OFFICER_ROLES = frozenset({OFFICER, ADMIN})


def _embed_or_422(image: str, uin: str, request: Request | None = None) -> list[float]:
    try:
        return embed_face_image(image)
    except ValueError as exc:
        raise _reject_enroll(uin, str(exc), request=request) from exc


def _pose_distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _templates_for_enrollment(req: EnrollRequest, uin: str, request: Request | None = None) -> list[dict]:
    """
    Build server-side templates from image bytes.

    A head sweep stores one vector per sector. The frontal template is the
    front sample. A single portrait stores sector "front" from faceImage.
    """
    if req.faceViews is not None:
        by_sector: dict[str, list[float]] = {}
        for sample in req.faceViews:
            by_sector[sample.sector] = _embed_or_422(sample.image, uin, request)

        front = by_sector["front"]
        for sector in ("far-left", "far-right"):
            if _pose_distance(front, by_sector[sector]) < 0.05:
                raise _reject_enroll(
                    uin,
                    f"{sector} sample is not a distinct pose from the frontal sample",
                    request=request,
                )
        return [
            {"sector": sample.sector, "embedding": by_sector[sample.sector]}
            for sample in req.faceViews
        ]

    return [{"sector": "front", "embedding": _embed_or_422(req.faceImage, uin, request)}]


@router.post("/enroll/ticket")
def issue_enroll_ticket():
    """Issue one short-lived enrolment ticket. The value is not written into HTML."""
    attempt = issue_ticket()
    return {"ticket": attempt.ticket, "expiresInSeconds": ticket_ttl()}


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


@router.post("/face/challenge", response_model=FaceChallenge)
def create_face_challenge_endpoint(req: FaceChallengeRequest):
    """
    Issues a single-use challenge for the browser descriptor path.

    The browser binds its head-sweep report to this id. A blink is not required.
    """
    return create_face_challenge(req.purpose)


def _require_operator(authorization: str | None, allowed: frozenset[str]) -> str:
    decision = authorize(authorization, allowed)
    if not decision.ok or decision.role is None or not decision.actor:
        raise HTTPException(status_code=decision.status_code or 401, detail=decision.reason)
    return decision.actor


_ENROLL_RATE_DETAIL = "Enrollment rate limit exceeded."
_ENROLL_LIMIT_UNAVAILABLE = "Enrollment limit store is unavailable."


def _allow_enroll(subject: str, uin: str, request: Request) -> str:
    """Check the hourly write cap for this ticket. A rejection stores nothing."""
    try:
        ensure_enroll_allowed(subject)
    except EnrollLimitExceeded:
        _audit(
            "enroll",
            "citizen",
            uin or "",
            "failure",
            "enrollment rate limit exceeded",
            retention="permanent",
            reason_code="rate_limited",
            event_name="enroll",
            request=request,
        )
        raise HTTPException(status_code=429, detail=_ENROLL_RATE_DETAIL)
    except EnrollLimitUnavailable as exc:
        raise HTTPException(status_code=503, detail=_ENROLL_LIMIT_UNAVAILABLE) from exc
    return subject


def _count_enroll_write(subject: str) -> None:
    try:
        record_enroll_success(subject)
    except EnrollLimitUnavailable as exc:
        raise HTTPException(status_code=503, detail=_ENROLL_LIMIT_UNAVAILABLE) from exc


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _ip_address(value: str) -> str | None:
    """An IP with no spaces and at most 64 characters, or None."""
    if not value or " " in value or len(value) > 64:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def _network(request: Request) -> str | None:
    """First X-Forwarded-For hop when it is an IP, else the client host when that is an IP.

    A non-IP host such as the test client's ``testclient`` is omitted. The audit
    log accepts only an IP in ``network``.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        hop = _ip_address(forwarded.split(",")[0].strip())
        if hop:
            return hop
    if request.client is not None and request.client.host:
        return _ip_address(request.client.host)
    return None


def _browser(request: Request) -> str:
    agent = request.headers.get("user-agent", "").strip()
    if not agent:
        return "unknown"
    return agent[:180]


def _source_label(request: Request) -> str:
    """IP and a short device label. The raw user agent is not included."""
    device = rough_device(request.headers.get("user-agent", ""))
    ip = _network(request)
    if ip:
        return f"{ip} · {device}"
    return device


def _new_check_id() -> str:
    return "chk_" + secrets.token_hex(8)


def _catalog_reason(reason_code: str | None, detail: str) -> str | None:
    """Map an existing failure onto a catalog code when the detail already says why."""
    if reason_code is None:
        return None
    text = detail.lower()
    if reason_code == "face_mismatch":
        return "MATCH-1"
    if reason_code == "no_face_template":
        return "MATCH-2"
    if reason_code == "unknown_uin":
        return "ID-1"
    if reason_code == "enroll_write_failed":
        return "SYS-1"
    if reason_code in {"liveness_failed", "sweep_rejected"}:
        if "expired" in text:
            return "SESSION-1"
        if "challenge" in text:
            return "SESSION-2"
        if "turn of" in text or "at least" in text:
            return "PAD-2"
        if "left to right" in text or "left-to-right" in text or "head turn" in text:
            return "PAD-1"
        if reason_code == "liveness_failed":
            return "PAD-1"
    return reason_code


def _spends_try(reason_code: str | None) -> bool:
    return isinstance(reason_code, str) and reason_code in TRY_CODES and uses_try(reason_code)


def _audit(
    kind: str,
    actor: str,
    uin: str,
    result: str,
    detail: str,
    *,
    retention: str | None = None,
    check_id: str | None = None,
    liveness_passed: bool | None = None,
    liveness_score: float | None = None,
    match_passed: bool | None = None,
    match_score: float | None = None,
    network: str | None = None,
    browser: str | None = None,
    reason: str | None = None,
    reason_code: str | None = None,
    action: str | None = None,
    event_name: str | None = None,
    app_code: str | None = None,
    session_id: str | None = None,
    request: Request | None = None,
    request_id: str | None = None,
) -> None:
    """Append one user-action row. A second application log line is not written."""
    if request is not None:
        if network is None:
            network = _network(request)
        if browser is None:
            browser = _browser(request)
    event: dict[str, Any] = {
        "kind": kind,
        "actor": actor,
        "uin": uin,
        "result": result,
        "detail": detail,
        "eventId": uuid.uuid4().hex,
        "service": "portal",
        "requestId": request_id or uuid.uuid4().hex,
    }
    if request is not None:
        event["source"] = _source_label(request)
    if retention is not None:
        event["retention"] = retention
    if check_id is not None:
        event["checkId"] = check_id
    if liveness_passed is not None:
        event["livenessPassed"] = liveness_passed
    scored_liveness = _finite(liveness_score)
    if scored_liveness is not None:
        event["livenessScore"] = scored_liveness
    if match_passed is not None:
        event["matchPassed"] = match_passed
    scored_match = _finite(match_score)
    if scored_match is not None:
        event["matchScore"] = scored_match
    if network is not None:
        event["network"] = network
    if browser is not None:
        event["browser"] = browser
    if reason is not None:
        event["reason"] = reason
    if reason_code is not None:
        event["reasonCode"] = reason_code
    if action is not None:
        event["action"] = action
    if event_name is not None:
        event["event"] = event_name
    if app_code:
        event["appCode"] = app_code
    if session_id:
        event["sessionId"] = session_id
    try:
        record_event(event)
    except ValueError as exc:
        # A success row still needs a UIN. Draft applications do not have one yet.
        if event.get("uin") == "" and result == "success" and "uin" in str(exc):
            return
        raise


def _mutation(
    actor: str,
    uin: str,
    result: str,
    detail: str,
    action: str,
    reason: str,
    *,
    event_name: str | None = None,
    request: Request | None = None,
) -> None:
    _audit(
        "operator",
        actor,
        uin,
        result,
        detail,
        retention="permanent",
        action=action,
        reason=reason,
        event_name=event_name,
        request=request,
    )


def _notification_count(records: list[dict[str, Any]], uin: str) -> int:
    return sum(
        1
        for row in records
        if row.get("uin") == uin and row.get("event") == "notification_sent"
    )


def _maybe_notify_limit(uin: str, request: Request, session_id: str | None) -> None:
    """One notification row each time failed tries for this UIN cross a multiple of 3."""
    records = list_events()
    used = tries_used(records, uin)
    if used < 3 or used % 3 != 0:
        return
    if _notification_count(records, uin) >= used // 3:
        return
    _audit(
        "operator",
        "system",
        uin,
        "failure",
        "notification sent",
        retention="permanent",
        reason_code="LIMIT-1",
        event_name="notification_sent",
        session_id=session_id,
        request=request,
    )


def _record_check(
    *,
    uin: str,
    result: str,
    detail: str,
    request: Request,
    check_id: str,
    liveness_passed: bool,
    match_passed: bool,
    match_score: float | None = None,
    liveness_score: float | None = None,
    reason_code: str | None = None,
    session_id: str | None = None,
) -> None:
    catalog = _catalog_reason(reason_code, detail)
    _audit(
        "authenticate",
        "citizen",
        uin,
        result,
        detail,
        retention="permanent",
        check_id=check_id,
        liveness_passed=liveness_passed,
        liveness_score=liveness_score,
        match_passed=match_passed,
        match_score=match_score,
        network=_network(request),
        browser=_browser(request),
        reason_code=catalog,
        event_name="authenticate",
        session_id=session_id,
        request=request,
    )
    if result == "failure" and _spends_try(catalog):
        _maybe_notify_limit(uin, request, session_id)


def _auth_session(req: AuthRequest) -> str | None:
    if req.liveness is not None and req.liveness.challengeId.strip():
        return req.liveness.challengeId.strip()
    if req.challengeId and req.challengeId.strip():
        return req.challengeId.strip()
    return None


def _enroll_session(req: EnrollRequest) -> str | None:
    if req.liveness is not None and req.liveness.challengeId.strip():
        return req.liveness.challengeId.strip()
    return None


def _with_officer_text(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    presented: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        code = item.get("reasonCode")
        if isinstance(code, str) and code in CODES:
            item["officerText"] = officer_text(code)
        presented.append(item)
    return presented


def _citizen_visible(event: dict[str, Any], uin: str) -> bool:
    if event.get("uin") != uin:
        return False
    name = event.get("event") or event.get("kind")
    kind = event.get("kind")
    if name == "authenticate" or kind == "authenticate":
        return True
    if (name == "enroll" or kind == "enroll") and event.get("result") == "success":
        return True
    if name == "activity_reported" or (kind == "dispute" and event.get("action") == "not_me"):
        return True
    return False


def _authenticate_check(check_id: str) -> dict[str, Any] | None:
    for event in list_events():
        if event.get("checkId") != check_id:
            continue
        if event.get("kind") == "authenticate" or event.get("event") == "authenticate":
            return event
    return None


def _with_activity(response: AuthResponse, uin: str, check_id: str) -> AuthResponse:
    response.checkId = check_id
    response.activityToken = issue_grant(uin)
    return response


def _citizen_summary(row: dict[str, Any]) -> CitizenSummary:
    created = row.get("created_at", row.get("createdAt"))
    if "login_disabled" in row:
        login_disabled = row.get("login_disabled")
    else:
        login_disabled = row.get("loginDisabled")
    return CitizenSummary(
        uin=str(row.get("uin") or ""),
        fullName=str(row.get("full_name") or row.get("fullName") or ""),
        email=row.get("email"),
        createdAt=None if created is None else str(created),
        loginDisabled=None if login_disabled is None else bool(login_disabled),
    )


def _matches_query(row: dict[str, Any], needle: str) -> bool:
    fields = (
        str(row.get("uin") or ""),
        str(row.get("full_name") or row.get("fullName") or ""),
        str(row.get("email") or ""),
    )
    return any(needle in field.casefold() for field in fields)


def _activity_uin(authorization: str | None) -> str:
    presented = ""
    if authorization and str(authorization).strip():
        parts = str(authorization).strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            presented = parts[1].strip()
    uin = resolve_grant(presented) if presented else None
    if not uin:
        raise HTTPException(status_code=401, detail="missing activity token")
    return uin


def _authenticate_rows(uin: str | None = None) -> list[dict[str, Any]]:
    rows = [event for event in list_events() if event.get("kind") == "authenticate"]
    if uin is None:
        return rows
    return [event for event in rows if event.get("uin") == uin]


def _notify_enrollment(req: EnrollRequest, uin: str) -> EmailResult:
    """Send the UIN confirmation. Failures do not undo the IDRepo write.

    A missing or unusable card image is omitted. The picture is not written to
    IDRepo, the audit log, or application logs.
    """
    card = decode_id_card_png(req.idCardImage) if req.emailIdCard else None
    return send_enrollment_email(
        to=req.email,
        full_name=req.fullName,
        uin=uin,
        email_id_card=req.emailIdCard,
        id_card_png=card,
    )


def _with_email(payload: dict[str, Any], mail: EmailResult) -> dict[str, Any]:
    payload["emailSent"] = mail.sent
    payload["emailStatus"] = mail.detail
    return payload


@router.get("/audit")
def read_audit(
    authorization: str | None = Header(default=None),
    limit: int = 50,
    uin: str | None = None,
    appCode: str | None = None,
    sessionId: str | None = None,
    date: str | None = None,
):
    """Operator audit trail. Records omit images and passwords.

    Officers may see ``source``, which includes the client IP. ``date`` is a
    UTC calendar day, ``YYYY-MM-DD``.
    """
    _require_operator(authorization, VIEW_ROLES)
    if date is not None and len(date) != 10:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    if date is not None:
        year, _, month_day = date.partition("-")
        month, _, day = month_day.partition("-")
        if not (year.isdigit() and month.isdigit() and day.isdigit()):
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    rows = list_events()
    if any(value is not None for value in (uin, appCode, sessionId, date)):
        rows = list(search_events(rows, uin=uin, app_code=appCode, session_id=sessionId, on_date=date))
    rows = rows[-limit:] if limit else []
    return _with_officer_text(rows)


@router.get("/citizens", response_model=list[CitizenSummary])
def list_citizens(
    authorization: str | None = Header(default=None),
    q: str | None = None,
):
    """
    Returns recently enrolled citizens from the MOSIP IDRepo REST interface.

    ``q`` keeps rows whose UIN, full name, or email contains that text.
    A query that misses the recent list is also tried as an exact UIN.
    """
    _require_operator(authorization, VIEW_ROLES)
    idrepo = get_idrepo_client()
    citizens = idrepo.list_identities(limit=50)
    needle = (q or "").strip()
    if needle:
        folded = needle.casefold()
        matched = [row for row in citizens if _matches_query(row, folded)]
        if not matched:
            exact = idrepo.get_identity(needle, include_biometrics=False)
            if exact:
                matched = [exact]
        citizens = matched
    return [_citizen_summary(row) for row in citizens]


@router.get("/citizens/{uin}")
def get_citizen(uin: str, authorization: str | None = Header(default=None)):
    """
    Retrieves a citizen demographic record by UIN. Face bytes stay off this read.
    """
    actor = _require_operator(authorization, VIEW_ROLES)
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
        "locked": is_locked(uin),
        "createdAt": str(citizen.get("created_at")),
    }


@router.get("/citizens/{uin}/checks")
def list_citizen_checks(uin: str, authorization: str | None = Header(default=None)):
    """Identity checks for one citizen. Rows are audit records and contain no images."""
    _require_operator(authorization, VIEW_ROLES)
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(uin, include_biometrics=False)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{uin}' not found in IDRepo.")
    return {"uin": uin, "checks": _authenticate_rows(uin)}


@router.post("/citizens/{uin}/demographics")
def update_citizen_demographics(
    uin: str,
    body: DemographicsUpdate,
    request: Request,
    authorization: str | None = Header(default=None),
):
    actor = _require_operator(authorization, CORRECT_ROLES)
    idrepo = get_idrepo_client()
    saved = idrepo.update_demographics(uin, body.fullName, body.email)
    if not saved:
        _mutation(
            actor,
            uin,
            "failure",
            "demographics update failed",
            "demographics",
            body.reason,
            event_name="details_corrected",
            request=request,
        )
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{uin}' was not updated.")
    _mutation(
        actor,
        uin,
        "success",
        "demographics updated",
        "demographics",
        body.reason,
        event_name="details_corrected",
        request=request,
    )
    return {"uin": uin, "fullName": body.fullName, "email": body.email}


@router.post("/citizens/{uin}/login-disabled")
def set_citizen_login_disabled(
    uin: str,
    body: LoginDisabledUpdate,
    request: Request,
    authorization: str | None = Header(default=None),
):
    actor = _require_operator(authorization, CORRECT_ROLES)
    event_name = "login_off" if body.disabled else "login_on"
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(uin, include_biometrics=False)
    if not citizen:
        _mutation(
            actor,
            uin,
            "failure",
            "login flag was not changed",
            "login",
            body.reason,
            event_name=event_name,
            request=request,
        )
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{uin}' not found in IDRepo.")
    keycloak = get_keycloak_client()
    result = keycloak.set_login_enabled(
        uin=uin,
        email=citizen.get("email") or "",
        enabled=not body.disabled,
    )
    if not result.ok:
        _mutation(
            actor,
            uin,
            "failure",
            "keycloak login flag was not changed",
            "login",
            body.reason,
            event_name=event_name,
            request=request,
        )
        raise HTTPException(status_code=502, detail="Keycloak login was not changed.")
    saved = idrepo.set_login_disabled(uin, body.disabled)
    if not saved:
        _mutation(
            actor,
            uin,
            "failure",
            "registry login flag was not changed",
            "login",
            body.reason,
            event_name=event_name,
            request=request,
        )
        raise HTTPException(status_code=502, detail="Registry login flag was not changed.")
    _mutation(
        actor,
        uin,
        "success",
        "login disabled" if body.disabled else "login enabled",
        "login",
        body.reason,
        event_name=event_name,
        request=request,
    )
    return {"uin": uin, "loginDisabled": body.disabled}


@router.post("/citizens/{uin}/delete-face")
def delete_citizen_face(
    uin: str,
    body: ReasonBody,
    request: Request,
    authorization: str | None = Header(default=None),
):
    actor = _require_operator(authorization, ADMIN_ROLES)
    idrepo = get_idrepo_client()
    saved = idrepo.delete_face(uin)
    if not saved:
        _mutation(
            actor,
            uin,
            "failure",
            "face delete failed",
            "delete_face",
            body.reason,
            event_name="face_removed",
            request=request,
        )
        raise HTTPException(status_code=404, detail=f"Face for UIN '{uin}' was not deleted.")
    _mutation(
        actor,
        uin,
        "success",
        "face deleted",
        "delete_face",
        body.reason,
        event_name="face_removed",
        request=request,
    )
    return {"uin": uin, "faceDeleted": True}


@router.post("/citizens/{uin}/lock")
def set_citizen_lock(
    uin: str,
    body: CitizenLock,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Lock or unlock a UIN. The officer's reason is stored as text, not a catalog code."""
    actor = _require_operator(authorization, _OFFICER_ROLES)
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(uin, include_biometrics=False)
    if not citizen:
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{uin}' not found in IDRepo.")
    set_locked(uin, body.locked)
    event_name = "uin_locked" if body.locked else "uin_unlocked"
    _audit(
        "operator",
        actor,
        uin,
        "success",
        "uin locked" if body.locked else "uin unlocked",
        retention="permanent",
        reason=body.reason,
        event_name=event_name,
        request=request,
    )
    return {"uin": uin, "locked": body.locked}


@router.get("/checks")
def list_all_checks(
    authorization: str | None = Header(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Authenticate events for every citizen, oldest first, capped at ``limit``."""
    _require_operator(authorization, ADMIN_ROLES)
    return _authenticate_rows()[-limit:]


@router.get("/staff")
def list_staff(authorization: str | None = Header(default=None)):
    _require_operator(authorization, ADMIN_ROLES)
    return staff_directory.list_members()


@router.post("/staff")
def create_staff(
    body: StaffCreate,
    authorization: str | None = Header(default=None),
):
    actor = _require_operator(authorization, ADMIN_ROLES)
    try:
        member = staff_directory.add_member(body.name, body.email, body.role)
    except ValueError as exc:
        _mutation(actor, "staff", "failure", str(exc)[:240], "add_staff", body.reason)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _mutation(actor, "staff", "success", f"member {member['id']}", "add_staff", body.reason)
    return member


@router.delete("/staff/{member_id}")
def delete_staff(
    member_id: str,
    body: ReasonBody,
    authorization: str | None = Header(default=None),
):
    actor = _require_operator(authorization, ADMIN_ROLES)
    removed = staff_directory.remove_member(member_id)
    if not removed:
        _mutation(actor, "staff", "failure", f"member {member_id} was not removed", "remove_staff", body.reason)
        raise HTTPException(status_code=404, detail=f"Staff member '{member_id}' was not found.")
    _mutation(actor, "staff", "success", f"member {member_id}", "remove_staff", body.reason)
    return {"id": member_id, "removed": True}


@router.post("/staff/{member_id}/role")
def change_staff_role(
    member_id: str,
    body: StaffRoleUpdate,
    request: Request,
    authorization: str | None = Header(default=None),
):
    actor = _require_operator(authorization, ADMIN_ROLES)
    try:
        member = staff_directory.set_role(member_id, body.role)
    except ValueError as exc:
        _mutation(
            actor,
            "staff",
            "failure",
            str(exc)[:240],
            "set_role",
            body.reason,
            event_name="role_changed",
            request=request,
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if member is None:
        _mutation(
            actor,
            "staff",
            "failure",
            f"member {member_id} role was not changed",
            "set_role",
            body.reason,
            event_name="role_changed",
            request=request,
        )
        raise HTTPException(status_code=404, detail=f"Staff member '{member_id}' was not found.")
    _mutation(
        actor,
        "staff",
        "success",
        f"member {member_id} role {member['role']}",
        "set_role",
        body.reason,
        event_name="role_changed",
        request=request,
    )
    return member


@router.get("/desk/session")
def desk_session(authorization: str | None = Header(default=None)):
    decision = authorize(authorization, VIEW_ROLES)
    if not decision.ok or decision.role is None or not decision.actor:
        raise HTTPException(status_code=decision.status_code or 401, detail=decision.reason)
    return {"role": decision.role, "actor": decision.actor}


@router.post("/attempts", status_code=204)
def report_capture_attempt(body: CaptureAttempt, request: Request) -> Response:
    """A camera or enroll failure that happened before a UIN existed."""
    _audit(
        body.kind,
        "citizen",
        "",
        "failure",
        body.detail[:200],
        retention="permanent",
        reason_code=body.reasonCode,
        event_name=body.kind,
        network=_network(request),
        browser=_browser(request),
        request=request,
    )
    return Response(status_code=204)


@router.get("/me/activity")
def read_my_activity(authorization: str | None = Header(default=None)):
    uin = _activity_uin(authorization)
    events = list_events()
    checks = [project_for_citizen(event) for event in events if _citizen_visible(event, uin)]
    disputes: list[str] = []
    for event in events:
        if event.get("uin") != uin:
            continue
        if event.get("kind") != "dispute" and event.get("event") != "activity_reported":
            continue
        check_id = event.get("checkId")
        if isinstance(check_id, str) and check_id and check_id not in disputes:
            disputes.append(check_id)
    used = tries_used(events, uin)
    return {
        "uin": uin,
        "checks": checks,
        "disputes": disputes,
        "askWasThisYou": used >= 3,
        "triesUsed": used,
    }


@router.post("/me/activity/{check_id}/not-me")
def report_not_me(
    check_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    body: NotMeReport | None = None,
):
    uin = _activity_uin(authorization)
    owned = any(
        event.get("checkId") == check_id for event in _authenticate_rows(uin)
    )
    if not owned:
        raise HTTPException(status_code=404, detail="Check not found.")
    text = ""
    if body is not None and body.detail:
        text = " ".join(body.detail.split())[:200]
    reason = text or "This wasn't me"
    _audit(
        "dispute",
        "citizen",
        uin,
        "success",
        reason,
        retention="permanent",
        action="not_me",
        reason=reason,
        check_id=check_id,
        event_name="activity_reported",
        network=_network(request),
        browser=_browser(request),
        request=request,
    )
    return {"checkId": check_id, "reported": True}


@router.get("/reports")
def list_reports(authorization: str | None = Header(default=None)):
    """Activity reports for officers, oldest first. Rows contain no images."""
    _require_operator(authorization, _OFFICER_ROLES)
    return [
        event
        for event in list_events()
        if event.get("event") == "activity_reported"
        or (event.get("kind") == "dispute" and event.get("action") == "not_me")
    ]


@router.post("/reports/{check_id}/open")
def open_report(
    check_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Record that an officer opened one authenticate check."""
    actor = _require_operator(authorization, _OFFICER_ROLES)
    check = _authenticate_check(check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    _audit(
        "operator",
        actor,
        str(check.get("uin") or ""),
        "success",
        "report opened",
        retention="permanent",
        check_id=check_id,
        event_name="report_opened",
        session_id=check.get("sessionId") if isinstance(check.get("sessionId"), str) else None,
        request=request,
    )
    return {"checkId": check_id, "opened": True}


@router.post("/reports/{check_id}/checked")
def mark_report_checked(
    check_id: str,
    body: ReasonBody,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Record an officer's review note. The reason is free text."""
    actor = _require_operator(authorization, _OFFICER_ROLES)
    check = _authenticate_check(check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    _audit(
        "operator",
        actor,
        str(check.get("uin") or ""),
        "success",
        "marked checked",
        retention="permanent",
        reason=body.reason,
        check_id=check_id,
        event_name="marked_checked",
        session_id=check.get("sessionId") if isinstance(check.get("sessionId"), str) else None,
        request=request,
    )
    return {"checkId": check_id, "checked": True}


@router.post("/checkLiveness", response_model=LivenessResponse)
def check_liveness_endpoint(req: LivenessRequest):
    """
    MOSIP BioSDK SPI Contract: IBioApi.checkLiveness() (ISO/IEC 30107-3 PAD)
    Evaluates Eye Aspect Ratio (EAR) dynamics and blink events.
    """
    return evaluate_liveness(req)


def _citizen_id_failure(request_id: str) -> str:
    """Plain enrolment failure. The reference matches the log line. No service names."""
    return (
        "We couldn't create your ID right now. Please try again later. "
        f"Reference: {request_id}"
    )


def _mosip_failure(idrepo: IDRepoClient, uin: str, req: EnrollRequest, request: Request | None) -> HTTPException:
    status = idrepo.last_status if idrepo.last_status in (502, 503) else 502
    request_id = uuid.uuid4().hex
    reason = idrepo.last_error or "Failed to persist identity in MOSIP IDRepo"
    logger.error("request_id=%s %s", request_id, reason)
    _audit(
        "enroll",
        "citizen",
        uin,
        "failure",
        "idrepo write failed",
        retention="permanent",
        reason_code="SYS-1",
        event_name="enroll",
        session_id=_enroll_session(req),
        request=request,
        request_id=request_id,
    )
    headers = {"Retry-After": "30"} if status == 503 else None
    return HTTPException(
        status_code=status,
        detail=_citizen_id_failure(request_id),
        headers=headers,
    )


def _identity_for(req: EnrollRequest, uin: str) -> dict[str, Any]:
    return build_identity(
        uin=uin,
        full_name=req.fullName,
        date_of_birth=req.dateOfBirth,
        gender=req.gender,
        email=req.email,
        phone=req.phone,
        address_line1=req.addressLine1,
        address_line2=req.addressLine2,
        address_line3=req.addressLine3,
        region=req.region,
        province=req.province,
        city=req.city,
        zone=req.zone,
        postal_code=req.postalCode,
        reference_identity_number=req.referenceIdentityNumber,
    )


def _cbeff_for(req: EnrollRequest, uin: str) -> str:
    jpeg_bytes = extract_jpeg_bytes(req.faceImage)
    # The face-api descriptors travel inside the CBEFF so a real MOSIP IDRepo (which has no
    # template endpoint) still holds what verify compares against.
    return build_cbeff_xml(uin=uin, jpeg_bytes=jpeg_bytes, descriptors=req.faceDescriptors)


def _store_identity(
    idrepo: IDRepoClient,
    req: EnrollRequest,
    uin: str,
    registration_id: str,
    cbeff_xml: str | None,
    templates: list[dict],
    record_status: str,
    enroll_subject: str,
    request: Request | None = None,
) -> None:
    # Face bytes and CBEFF are written only when policy allows a biometric record.
    store_biometrics = record_status == "biometric" and cbeff_xml is not None
    saved = idrepo.add_identity(
        uin=uin,
        full_name=req.fullName,
        email=req.email,
        face_image=req.faceImage if store_biometrics else None,
        cbeff_xml=cbeff_xml if store_biometrics else None,
        templates=templates,
        status=record_status,
        identity=_identity_for(req, uin),
        registration_id=registration_id,
        date_of_birth=req.dateOfBirth,
        gender=req.gender,
        phone=req.phone,
        address_line1=req.addressLine1,
        address_line2=req.addressLine2,
        address_line3=req.addressLine3,
        region=req.region,
        province=req.province,
        city=req.city,
        zone=req.zone,
        postal_code=req.postalCode,
        reference_identity_number=req.referenceIdentityNumber,
    )
    if not saved:
        raise _mosip_failure(idrepo, uin, req, request)
    _count_enroll_write(enroll_subject)


def _consent_note(req: EnrollRequest) -> str:
    purpose = " ".join(req.consent.purpose.split())[:80]
    return f"consent {req.consent.language} at {int(req.consent.acceptedAt)}; {purpose}"


def _reject_enroll(
    uin: str,
    message: str,
    request: Request | None = None,
    session_id: str | None = None,
) -> HTTPException:
    _audit(
        "enroll",
        "citizen",
        uin,
        "failure",
        message[:240],
        retention="permanent",
        reason_code="enroll_failed",
        event_name="enroll",
        session_id=session_id,
        request=request,
    )
    return HTTPException(status_code=422, detail=message)


def _enroll_with_descriptors(
    req: EnrollRequest,
    idrepo: IDRepoClient,
    uin: str,
    registration_id: str,
    enroll_subject: str,
    request: Request | None = None,
) -> dict:
    """
    Store face-api templates after the descriptor checks pass.

    The challenge check rejects an expired, reused, or out-of-order report
    before any write. A report that passes is the presentation check, and
    face-api-128 can identify, so the CBEFF document is sent.
    """
    assert req.faceDescriptors is not None and req.liveness is not None
    try:
        descriptors = [
            validate_descriptor(values, f"Face descriptor {index}")
            for index, values in enumerate(req.faceDescriptors, start=1)
        ]
        hash_vector = embed_face_image(req.faceImage)
    except ValueError as exc:
        raise _reject_enroll(
            uin, str(exc), request=request, session_id=_enroll_session(req)
        ) from exc

    liveness = assess_client_liveness(req.liveness, "enroll")
    if not liveness.ok:
        raise _reject_enroll(
            uin, liveness.message, request=request, session_id=_enroll_session(req)
        )

    if not descriptors_consistent(descriptors):
        raise _reject_enroll(
            uin,
            "The captured frames do not look like the same face. Scan again.",
            request=request,
            session_id=_enroll_session(req),
        )

    store_biometric = may_store_biometric_record(liveness.ok, True)
    record_status = "biometric" if store_biometric else "draft"
    cbeff_xml = _cbeff_for(req, uin) if store_biometric else None
    templates = [
        {"sector": "front", "embedding": descriptor, "engine": FACE_DESCRIPTOR_ENGINE}
        for descriptor in descriptors
    ]
    templates.append({"sector": "front", "embedding": hash_vector, "engine": ENGINE_NAME})
    _store_identity(
        idrepo, req, uin, registration_id, cbeff_xml, templates, record_status, enroll_subject, request
    )
    mail = _notify_enrollment(req, uin)

    _audit(
        "enroll",
        "citizen",
        uin,
        "success",
        (
            f"{record_status} stored; {len(descriptors)} {FACE_DESCRIPTOR_ENGINE} templates; "
            f"{_consent_note(req)}; {mail.detail}"
        )[:240],
        event_name="enroll",
        session_id=_enroll_session(req),
        request=request,
    )
    return _with_email(
        {
            "status": "SUCCESS",
            "message": "Citizen identity stored via MOSIP IDRepo interface",
            "uin": uin,
            "fullName": req.fullName,
            "backend": idrepo.last_backend or "mosip-idrepo-rest",
            "cbeffGenerated": cbeff_xml is not None,
            "recordStatus": record_status,
        },
        mail,
    )


def _require_attempt(request: Request):
    presented = request.headers.get("x-enroll-ticket", "").strip()
    attempt = get_ticket(presented)
    if attempt is None:
        raise HTTPException(status_code=401, detail="Enrollment ticket is required.")
    if attempt.consumed:
        raise HTTPException(status_code=409, detail="Enrollment ticket was already used.")
    return attempt


def _allocate(idrepo: IDRepoClient, attempt, req: EnrollRequest, request: Request) -> tuple[str, str]:
    """Keep one UIN and one registration id for this ticket, including a later retry."""
    registration_id = attempt.registration_id or idrepo._make_rid()
    uin = attempt.uin
    if not uin:
        uin = idrepo.generate_uin()
        if not uin:
            raise _mosip_failure(idrepo, "", req, request)
    remember_allocation(attempt, uin, registration_id)
    return uin, registration_id


@router.post("/enroll")
def enroll_citizen_endpoint(req: EnrollRequest, request: Request):
    """
    Enrol through MOSIP IDRepo.

    The browser presents a server-issued ticket. The server allocates the UIN
    and keeps that UIN and one registration id if a later step fails. The
    write cap is per ticket and comes from ENROLL_SUCCESS_LIMIT. A client UIN
    is rejected by the request model. Password setup is a separate call and
    needs the credential ticket returned here.
    """
    attempt = _require_attempt(request)
    _allow_enroll(attempt.ticket, attempt.uin or "", request)
    idrepo = get_idrepo_client()
    uin, registration_id = _allocate(idrepo, attempt, req, request)

    if req.faceDescriptors is not None:
        payload = _enroll_with_descriptors(
            req, idrepo, uin, registration_id, attempt.ticket, request
        )
    else:
        # Hash templates cannot identify a face, so this path stays a draft
        # and does not build or send CBEFF.
        record_status = "biometric" if may_store_biometric_record(False, False) else "draft"
        templates = _templates_for_enrollment(req, uin, request)
        _store_identity(
            idrepo, req, uin, registration_id, None, templates, record_status, attempt.ticket, request
        )
        mail = _notify_enrollment(req, uin)
        _audit(
            "enroll",
            "citizen",
            uin,
            "success",
            f"draft stored; {_consent_note(req)}; {mail.detail}"[:240],
            event_name="enroll",
            session_id=_enroll_session(req),
            request=request,
        )
        payload = _with_email(
            {
                "status": "SUCCESS",
                "message": "Citizen demographics stored as a draft via MOSIP IDRepo interface",
                "uin": uin,
                "fullName": req.fullName,
                "backend": idrepo.last_backend or "mosip-idrepo-rest",
                "cbeffGenerated": False,
                "recordStatus": record_status,
            },
            mail,
        )

    payload["activityToken"] = issue_grant(uin)
    payload["credentialTicket"] = consume_for_credentials(attempt)
    return payload


@router.post("/applications", status_code=201, response_model=ApplicationCreated)
def create_application_endpoint(request: Request, payload: Any = Body(...)) -> ApplicationCreated:
    """
    Store a draft application for someone who could not finish a face capture.

    A draft is not an identity. This route does not enroll, write IDRepo,
    call Keycloak, embed a face, or send mail.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="request body must be an object")
    try:
        application = ApplicationCreate.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc
    try:
        created = create_application(get_application_store(), application)
    except ApplicationStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # A saved application has a code and no UIN yet. The code stays in appCode.
    _audit(
        "operator",
        "citizen",
        "",
        "success",
        "application saved",
        event_name="details_saved",
        app_code=created.code,
        request=request,
    )
    return created


@router.post("/credentials", response_model=CredentialResponse)
def issue_credentials_endpoint(req: CredentialRequest):
    """
    Set the Keycloak password for the UIN this enrolment ticket allocated.

    The password is sent only to Keycloak. It is never written to IDRepo.
    A ticket from a different enrolment, or a second use of the same ticket, is rejected.
    """
    if not take_credential(req.credentialTicket, req.uin):
        raise HTTPException(
            status_code=401,
            detail="Password setup requires the ticket from the enrolment that created this UIN.",
        )
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
        if result.detail == "account already exists":
            _audit("credential", "citizen", req.uin, "failure", "keycloak account already exists")
            raise HTTPException(status_code=409, detail="An account for this UIN already exists.")
        _audit("credential", "citizen", req.uin, "failure", "keycloak did not store the login")
        status = 503 if getattr(result, "retryable", False) else 502
        headers = {"Retry-After": "30"} if status == 503 else None
        raise HTTPException(
            status_code=status,
            detail="Keycloak did not store the login.",
            headers=headers,
        )
    _audit("credential", "citizen", req.uin, "success", "keycloak user ready")
    return CredentialResponse(
        status="SUCCESS",
        uin=req.uin,
        keycloakProvisioned=True,
    )


_NO_DESCRIPTOR_TEMPLATE = (
    "This ID has no face template from the browser model. Enroll again in the portal."
)


def _authenticate_with_descriptor(
    req: AuthRequest,
    idrepo: IDRepoClient,
    citizen: dict,
    request: Request,
    check_id: str,
) -> AuthResponse:
    """
    Compare a browser descriptor with stored face-api-128 templates.

    The browser reports liveness and sends the descriptor. The server checks
    the report against its challenge and decides the match from distance.
    """
    assert req.probeDescriptor is not None and req.liveness is not None
    session_id = _auth_session(req)
    try:
        probe = validate_descriptor(req.probeDescriptor, "Probe descriptor")
    except ValueError as exc:
        _record_check(
            uin=req.uin,
            result="failure",
            detail=str(exc),
            request=request,
            check_id=check_id,
            liveness_passed=False,
            match_passed=False,
            reason_code="bad_descriptor",
            session_id=session_id,
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    common: dict[str, Any] = {
        "citizen": {"uin": citizen["uin"]},
        "jwtToken": None,
        "livenessScore": None,
        "yawSource": "client",
        "livenessSource": "client",
    }

    liveness = assess_client_liveness(req.liveness, "check")
    if not liveness.ok:
        _record_check(
            uin=req.uin,
            result="failure",
            detail=liveness.message[:240],
            request=request,
            check_id=check_id,
            liveness_passed=False,
            match_passed=False,
            reason_code="liveness_failed",
            session_id=session_id,
        )
        return _with_activity(
            AuthResponse(
                status="FAILED",
                verified=False,
                isFaceMatch=False,
                livenessPassed=False,
                compared=False,
                sweepAccepted=False,
                message=liveness.message,
                **common,
            ),
            req.uin,
            check_id,
        )

    gallery = [
        row["embedding"]
        for row in idrepo.get_face_templates(req.uin)
        if row.get("engine") == FACE_DESCRIPTOR_ENGINE
        and isinstance(row.get("embedding"), list)
        and len(row["embedding"]) == DESCRIPTOR_LENGTH
    ]
    if not gallery:
        _record_check(
            uin=req.uin,
            result="failure",
            detail=f"no {FACE_DESCRIPTOR_ENGINE} template stored",
            request=request,
            check_id=check_id,
            liveness_passed=True,
            match_passed=False,
            reason_code="no_face_template",
            session_id=session_id,
        )
        return _with_activity(
            AuthResponse(
                status="FAILED",
                verified=False,
                isFaceMatch=False,
                livenessPassed=True,
                compared=False,
                sweepAccepted=True,
                threshold=DESCRIPTOR_MATCH_THRESHOLD,
                message=_NO_DESCRIPTOR_TEMPLATE,
                **common,
            ),
            req.uin,
            check_id,
        )

    match = compare_descriptor(gallery, probe, DESCRIPTOR_MATCH_THRESHOLD)
    assert match.distance is not None
    verdict = "is below" if match.is_face_match else "is not below"
    message = (
        f"Face {'matched' if match.is_face_match else 'did not match'} on the server: "
        f"distance {match.distance:.4f} {verdict} {DESCRIPTOR_MATCH_THRESHOLD}. "
        "Liveness was reported by the browser."
    )
    _record_check(
        uin=req.uin,
        result="success" if match.is_face_match else "failure",
        detail=(
            f"{FACE_DESCRIPTOR_ENGINE} {'match' if match.is_face_match else 'no match'} "
            f"at distance {match.distance:.4f}; liveness reported by browser"
        ),
        request=request,
        check_id=check_id,
        liveness_passed=True,
        match_passed=match.is_face_match,
        match_score=match.score,
        reason_code=None if match.is_face_match else "face_mismatch",
        session_id=session_id,
    )
    return _with_activity(
        AuthResponse(
            status="SUCCESS" if match.is_face_match else "FAILED",
            verified=match.is_face_match,
            isFaceMatch=match.is_face_match,
            livenessPassed=True,
            compared=True,
            sweepAccepted=True,
            euclideanDistance=match.distance,
            matchScore=match.score,
            threshold=match.threshold,
            message=message,
            **common,
        ),
        req.uin,
        check_id,
    )


@router.post("/authenticate", response_model=AuthResponse)
def authenticate_citizen_endpoint(req: AuthRequest, request: Request):
    """
    Verify a citizen against stored templates.

    With probeDescriptor: browser-reported liveness bound to a face challenge,
    then a server-side face-api-128 distance comparison.

    Without it: a five-pose head sweep bound to an expiring challenge. Blink
    flags on the request are ignored. The hash embedder is not a face model,
    so a passing sweep is a submission check, not an identity match and not
    proof of a live head turn.
    """
    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(req.uin)
    check_id = _new_check_id()
    session_id = _auth_session(req)
    if not citizen:
        _record_check(
            uin=req.uin,
            result="failure",
            detail="citizen not found",
            request=request,
            check_id=check_id,
            liveness_passed=False,
            match_passed=False,
            reason_code="unknown_uin",
            session_id=session_id,
        )
        raise HTTPException(status_code=404, detail=f"Citizen UIN '{req.uin}' not found in registry.")

    if is_locked(req.uin):
        _record_check(
            uin=req.uin,
            result="failure",
            detail="uin is locked",
            request=request,
            check_id=check_id,
            liveness_passed=False,
            match_passed=False,
            reason_code="ID-2",
            session_id=session_id,
        )
        raise HTTPException(status_code=423, detail=citizen_message("ID-2"))

    if req.probeDescriptor is not None:
        return _authenticate_with_descriptor(req, idrepo, citizen, request, check_id)

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
            stored_vectors = [
                row["embedding"]
                for row in stored_rows
                if "embedding" in row and row.get("engine", ENGINE_NAME) == ENGINE_NAME
            ]
            match = compare_probe(stored_vectors, probe_vector)
        except ValueError:
            match = compare_probe([], [])

    _record_check(
        uin=req.uin,
        result="success" if verified else "failure",
        detail="sweep submission accepted" if verified else "sweep submission rejected",
        request=request,
        check_id=check_id,
        liveness_passed=capture.presentation_passed,
        match_passed=match.is_face_match,
        match_score=match.score,
        liveness_score=req.livenessScore,
        reason_code=None if verified else _catalog_reason("sweep_rejected", assessment.message),
        session_id=session_id,
    )
    return _with_activity(
        AuthResponse(
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
        ),
        req.uin,
        check_id,
    )
