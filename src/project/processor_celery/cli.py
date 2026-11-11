import logging
from typing import Annotated
from typer import Typer
import typer

from rich.console import Console
from rich.pretty import pprint

from project.processor_celery.works import addition_job, subtraction_job, multiplier_job

console = Console(highlight=False)
cli = Typer()

@cli.command()
def addition(a:Annotated[int, typer.Argument(help="First number argument")], 
        b:Annotated[int, typer.Argument(help="Second number argument")]):
    """
    It will perform an addition between `a` and `b`.
    """
    logging.debug(f"Calling `addition` from processor_celery")
    job_id:str = addition_job.delay(a,b)
    logging.info(f"celery job_id={job_id}")

@cli.command()
def subtraction(a:Annotated[int, typer.Argument(help="First number argument")], 
        b:Annotated[int, typer.Argument(help="Second number argument")]):
    """
    This is the another default command.
    It will perform a subtraction between `a` and `b`.
    """
    logging.debug(f"Calling `addition` from processor_celery")
    job_id:str = subtraction_job.delay(a,b)
    logging.info(f"celery job_id={job_id}")

@cli.command()
def multiplier(a:Annotated[int, typer.Argument(help="First number argument")], 
        b:Annotated[int, typer.Argument(help="Second number argument")]):
    """
    This multiplier is a part of celery job.
    The job will simulate long processing time with 10 seconds sleep then return with the answer
    """
    logging.debug(f"Calling `addition` from processor_celery")
    job_id:str = multiplier_job.delay(a,b)
    logging.info(f"celery job_id={job_id}")