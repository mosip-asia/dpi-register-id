from fastapi import FastAPI
from project.web.router import router as web_router
from register_id.api import router as register_id_router

app = FastAPI(title="DPI Citizen Registration Gateway (register-id)")

app.include_router(web_router)
app.include_router(register_id_router)

import uvicorn
from typer import Typer
import os
cli = Typer()
@cli.command()
def start():
    """
    Start uvicorn server.
    This will read `FASTAPI_HOST`, `FASTAPI_PORT`, and `FASTAPI_WORKERS` from `os.environ`
    """
    host = os.environ["FASTAPI_HOST"]
    port = int(os.environ["FASTAPI_PORT"])
    workers = int(os.environ["FASTAPI_WORKERS"])
    uvicorn.run("project.web:app", host=host, port=port, log_level="info", workers=workers)