import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from register_id.idrepo_client import inprocess_fallback_enabled

_BUILD_VERSION: str = os.getenv("BUILD_VERSION", "0.1.0-dev")
_ENVIRONMENT: str = os.getenv("ENVIRONMENT", "dev")

router = APIRouter()
# router.mount("/static", StaticFiles(directory="static"), name="static")

template_path = Path(__file__).parent.joinpath("templates")
templates = Jinja2Templates(directory=template_path)
_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
_SPA_PREFIXES = ("enroll", "prove", "id", "desk", "assets", "models")


def _spa_index() -> HTMLResponse | None:
    index = _DIST / "index.html"
    if index.is_file():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return None


@router.get("/health")
async def get_health():
    """Liveness: the process is serving. Dependency checks are not done here."""
    return {
        "status": "ok",
        "environment": _ENVIRONMENT,
        "build_version": _BUILD_VERSION,
    }


def _config_ready() -> bool:
    """Kit mode needs Redis plus the MOSIP and Keycloak settings. It does not call IDRepo."""
    required = (
        "REDIS_URL",
        "MOSIP_IDREPO_BASE_URL",
        "IDREPO_CLIENT_ID",
        "IDREPO_CLIENT_SECRET",
        "KEYCLOAK_ADMIN_CLIENT_ID",
        "KEYCLOAK_ADMIN_CLIENT_SECRET",
    )
    if any(not os.getenv(name, "").strip() for name in required):
        return False
    # Kit deploys use two hosts. KEYCLOAK_URL does not stand in for either.
    public = os.getenv("KEYCLOAK_PUBLIC_URL", "").strip()
    internal = os.getenv("KEYCLOAK_INTERNAL_URL", "").strip()
    return bool(public and internal)


@router.get("/ready")
async def get_ready():
    """Readiness: Redis and loaded configuration. IDRepo is not probed."""
    checks: dict[str, str] = {}
    ready = True

    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        checks["redis"] = "skipped" if inprocess_fallback_enabled() else "missing"
        if not inprocess_fallback_enabled():
            ready = False
    else:
        try:
            import redis

            client = redis.Redis.from_url(
                redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "down"
            ready = False

    if inprocess_fallback_enabled():
        checks["config"] = "skipped"
    else:
        checks["config"] = "ok" if _config_ready() else "incomplete"
        if checks["config"] != "ok":
            ready = False

    body = {"status": "ok" if ready else "unavailable", "checks": checks}
    if not ready:
        return JSONResponse(status_code=503, content=body)
    return body


@router.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    spa = _spa_index()
    if spa is not None:
        return spa
    context = {
        "build_version": _BUILD_VERSION,
        "environment": _ENVIRONMENT,
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@router.get("/lab", response_class=HTMLResponse)
async def get_lab(request: Request):
    context = {
        "build_version": _BUILD_VERSION,
        "environment": _ENVIRONMENT,
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@router.get("/example/{id}", response_class=HTMLResponse)
async def get_example(request: Request, id: int):
    return templates.TemplateResponse(request=request, name="example.html", context={"id": id})


@router.get("/{full_path:path}", response_class=HTMLResponse)
async def get_spa(full_path: str):
    if full_path.startswith(_SPA_PREFIXES) or full_path.startswith("assets/"):
        asset = (_DIST / full_path).resolve()
        if asset.is_file() and str(asset).startswith(str(_DIST.resolve())):
            return FileResponse(asset)
        spa = _spa_index()
        if spa is not None:
            return spa
    raise HTTPException(status_code=404)
