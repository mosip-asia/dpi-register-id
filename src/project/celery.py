import logging
from celery import Celery # type: ignore
from celery.result import AsyncResult # type: ignore
from typing import Annotated
import os
from time import sleep
from rich.console import Console
from rich.pretty import pprint
import typer
from typer import Typer

logger = logging.getLogger(__name__)
REDIS_URL = os.environ["REDIS_URL"]
logger.debug(f"REDIS_URL={REDIS_URL}")

queue = Celery(__name__, broker=REDIS_URL, backend=REDIS_URL, task_track_started=True)
console = Console(highlight=False)
cli = Typer()

@cli.command()
def start():
    """
    Command for starting celery worker
    """
    parameter = [
        'worker',
        '--loglevel=INFO',
        '-n worker1@%h'
    ]
    queue.worker_main(parameter) # type: ignore

@cli.command()
def status(job_id:Annotated[str, typer.Argument(help="The `job_id` of celery job. This value is returned after job is submitted")]):
    """
    Command for starting celery worker
    """
    job = AsyncResult(job_id, app=queue)
    status = {                 # type: ignore
        "id": job.id,          # type: ignore
        "status": job.status,  # type: ignore
        "state": job.state,    # type: ignore
        "result": job.result   # type: ignore
    }
    pprint(status, expand_all=True)
    
@cli.command()
def cancel(job_id:Annotated[str, typer.Argument(help="The `job_id` of celery job. This value is returned after job is submitted")]):
    queue.control.revoke(job_id, terminate=True, signal='SIGKILL') # type: ignore
    sleep(1) # sleep here and the job status has time to process
    console.print(f"[green]job_id={job_id} is cancelled.")
    status(job_id=job_id)

@cli.command()
def clear(job_id:Annotated[str, typer.Argument(help="The `job_id` of celery job. This value is returned after job is submitted")]):
    job = AsyncResult(job_id, app=queue)
    if(job.status == "STARTED"): # type: ignore
        console.print(f"[red]Job can not `clear` during processing. Please cancel it first.")
        raise RuntimeError("Job can not `clear` during processing. Please cancel it first.")
    job.forget()
    sleep(1) # sleep here and the job status has time to process
    console.print(f"[green]job_id={job_id} is cleared.")

@queue.task # type: ignore
def _sample_job() -> str:
    logger.debug("a")
    for i in range(10):
        logger.info(f"iteration {i}")
        sleep(1)
    logger.debug("a")
    return "result"

@cli.command()
def sample_job():
    """
    This will submit a job to celery
    """
    logging.debug(f"Calling `sample_job` from celery.py")
    job_id:str = _sample_job.delay() # type: ignore
    logging.info(f"celery job_id={job_id}")
    print(f"{job_id}")
