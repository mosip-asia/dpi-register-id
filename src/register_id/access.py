"""Token checks for operator routes.

One shared operator token is configured for this stage. REGISTER_ID_OPERATOR_ROLE
says whether that token acts as a reader or a custodian. This module does not
open the identity database and does not build an HTTP response.
"""

import hmac
import os
from collections.abc import Collection
from dataclasses import dataclass

READER = "reader"
CUSTODIAN = "custodian"
OFFICER = "officer"
ADMIN = "admin"

# List identities and read demographics (name, email, status, login flag).
DEMOGRAPHIC_ROLES = frozenset({READER, CUSTODIAN})
# Also correct name/email, set the login-disabled flag, and delete a face.
CUSTODIAN_ROLES = frozenset({CUSTODIAN})
# Search and read a person and their checks.
VIEW_ROLES = frozenset({READER, CUSTODIAN, OFFICER, ADMIN})
# Name, email, login on/off. A reader cannot.
CORRECT_ROLES = frozenset({OFFICER, ADMIN, CUSTODIAN})
# Remove a face, manage officers, and list every identity check.
ADMIN_ROLES = frozenset({ADMIN, CUSTODIAN})


@dataclass(frozen=True)
class RoleDecision:
    """Result the API can map onto 401 or 403 without further interpretation."""

    ok: bool
    role: str | None = None
    reason: str | None = None
    status_code: int | None = None
    actor: str | None = None


def _presented_token(authorization_header: str | None) -> str | None:
    """Bearer token, empty when the header is unusable, None when it is absent."""
    if authorization_header is None or not str(authorization_header).strip():
        return None
    parts = str(authorization_header).strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    token = parts[1].strip()
    return token if token else ""


def require_role(authorization_header: str | None, allowed: Collection[str]) -> RoleDecision:
    """
    Check "Bearer <token>" against REGISTER_ID_OPERATOR_TOKEN.

    The role comes from REGISTER_ID_OPERATOR_ROLE, not from the token.
    A missing or wrong token fails with status_code 401.
    A matching token whose role is outside allowed fails with status_code 403.
    """
    allowed_roles = {role.strip().lower() for role in allowed}
    expected = os.environ.get("REGISTER_ID_OPERATOR_TOKEN") or ""
    configured = (os.environ.get("REGISTER_ID_OPERATOR_ROLE") or "").strip().lower()

    presented = _presented_token(authorization_header)
    if presented is None:
        return RoleDecision(ok=False, reason="missing operator token", status_code=401)
    if not expected or not presented or not hmac.compare_digest(presented, expected):
        return RoleDecision(ok=False, reason="invalid operator token", status_code=401)
    if configured not in allowed_roles:
        label = configured or "unset"
        return RoleDecision(
            ok=False,
            role=configured or None,
            reason=f"operator role '{label}' is not allowed",
            status_code=403,
        )
    return RoleDecision(ok=True, role=configured, actor=configured)


def authorize(authorization_header: str | None, allowed: Collection[str]) -> RoleDecision:
    """
    Accept the configured operator token or a staff bearer token.

    A header that matches REGISTER_ID_OPERATOR_TOKEN is decided by require_role,
    including actor set to that configured role. Any other bearer token is looked
    up in the staff directory. A staff role inside allowed succeeds with
    actor set to the member email. A known staff role outside allowed is 403.
    Anything else is 401. The token is not written to a log.
    """
    presented = _presented_token(authorization_header)
    if presented is None:
        return RoleDecision(ok=False, reason="missing operator token", status_code=401)

    expected = os.environ.get("REGISTER_ID_OPERATOR_TOKEN") or ""
    if expected and presented and hmac.compare_digest(presented, expected):
        return require_role(authorization_header, allowed)

    if not presented:
        return RoleDecision(ok=False, reason="invalid operator token", status_code=401)

    from register_id.staff import authenticate_token

    member = authenticate_token(presented)
    if member is None:
        return RoleDecision(ok=False, reason="invalid operator token", status_code=401)

    allowed_roles = {role.strip().lower() for role in allowed}
    role = str(member["role"]).strip().lower()
    if role not in allowed_roles:
        return RoleDecision(
            ok=False,
            role=role,
            reason=f"operator role '{role}' is not allowed",
            status_code=403,
        )
    email = str(member["email"])
    return RoleDecision(ok=True, role=role, actor=email)
