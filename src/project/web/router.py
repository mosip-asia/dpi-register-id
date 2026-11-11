from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

_BUILD_VERSION: str = os.getenv("BUILD_VERSION", "0.1.0-dev")
_ENVIRONMENT: str = os.getenv("ENVIRONMENT", "dev")

router = APIRouter()
# router.mount("/static", StaticFiles(directory="static"), name="static")

template_path = Path(__file__).parent.joinpath("templates")
templates = Jinja2Templates(directory=template_path)


@router.get("/health")
async def get_health():
    return {
        "status": "ok",
        "environment": _ENVIRONMENT,
        "build_version": _BUILD_VERSION,
    }


@router.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    context = {
        "build_version": _BUILD_VERSION,
        "environment": _ENVIRONMENT,
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@router.get("/example/{id}", response_class=HTMLResponse)
async def get_example(request: Request, id: int):
    return templates.TemplateResponse(request=request, name="example.html", context={"id": id})
