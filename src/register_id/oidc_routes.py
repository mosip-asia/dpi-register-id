"""Citizen Keycloak login routes. Access tokens stay on the server."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from register_id.oidc import (
    SESSION_COOKIE_NAME,
    OidcConfigError,
    OidcError,
    OidcExchangeError,
    OidcRequestError,
    OidcStoreError,
    begin_authorization,
    cookie_secure,
    destroy_session,
    establish_session,
    load_session,
)

router = APIRouter(prefix="/api", tags=["oidc"])


def _http_error(exc: OidcError) -> HTTPException:
    if isinstance(exc, OidcStoreError):
        status_code = 503
    elif isinstance(exc, OidcExchangeError):
        status_code = 502
    elif isinstance(exc, (OidcConfigError, OidcRequestError)):
        status_code = 400
    else:
        status_code = 500
    return HTTPException(status_code=status_code, detail=str(exc))


def _set_session_cookie(response: JSONResponse, session_id: str, max_age: int) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=max_age,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: JSONResponse) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
    )


@router.get("/login/start")
def login_start():
    """Redirect the browser to the Keycloak authorization endpoint."""
    try:
        authorization_url = begin_authorization()
    except OidcError as exc:
        raise _http_error(exc) from exc
    return RedirectResponse(authorization_url, status_code=302)


@router.get("/login/callback")
def login_callback(code: str = "", state: str = ""):
    """
    Exchange the authorization code and set the session cookie.

    The JSON body has no access token and no jwtToken field.
    """
    try:
        result = establish_session(code, state)
    except OidcError as exc:
        raise _http_error(exc) from exc
    body: dict[str, str | bool] = {"authenticated": True, "subject": result.subject}
    if result.uin is not None:
        body["uin"] = result.uin
    response = JSONResponse(body)
    response.headers["Cache-Control"] = "no-store"
    _set_session_cookie(response, result.session_id, result.max_age)
    return response


@router.get("/login/session")
def login_session(request: Request):
    """Return the signed-in subject and uin claim when one was issued."""
    try:
        view = load_session(request.cookies.get(SESSION_COOKIE_NAME))
    except OidcError as exc:
        raise _http_error(exc) from exc
    if view is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    response = JSONResponse(view)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/login/logout")
def login_logout(request: Request):
    """Delete the server session and clear the session cookie."""
    try:
        destroy_session(request.cookies.get(SESSION_COOKIE_NAME))
    except OidcError as exc:
        raise _http_error(exc) from exc
    response = JSONResponse({"status": "logged_out"})
    response.headers["Cache-Control"] = "no-store"
    _clear_session_cookie(response)
    return response
