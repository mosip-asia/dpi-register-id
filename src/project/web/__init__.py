from fastapi import FastAPI
from project.web.router import router as web_router
app = FastAPI()

app.include_router(web_router)

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