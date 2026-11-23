import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

_BUILD_VERSION: str = os.getenv("BUILD_VERSION", "0.1.0-dev")
_ENVIRONMENT: str = os.getenv("ENVIRONMENT", "dev")

router = APIRouter()
# router.mount("/static", StaticFiles(directory="static"), name="static")

template_path = Path(__file__).parent.joinpath("templates")
templates = Jinja2Templates(directory=template_path)
_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
_SPA_PREFIXES = ("enroll", "prove", "id", "assets", "models")


def _spa_index() -> HTMLResponse | None:
    index = _DIST / "index.html"
    if index.is_file():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return None


@router.get("/health")
async def get_health():
    return {
        "status": "ok",
        "environment": _ENVIRONMENT,
        "build_version": _BUILD_VERSION,
    }


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
