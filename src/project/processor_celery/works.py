from typing import Annotated
import typer
import logging
import time

import os
from project.celery import queue

@queue.task
def addition_job(a:int, b:int) -> int:
    logging.debug("Calling `addition`")
    answer:int = a + b
    print(f"The calculation is {answer}.")
    return answer

@queue.task 
def subtraction_job(a:Annotated[int, typer.Argument(help="First number argument")], 
        b:Annotated[int, typer.Argument(help="Second number argument")]) -> int:
    """
    This is the another default command.
    It will perform a subtraction between `a` and `b`.
    """
    logging.debug("Calling `subtraction`")
    answer:int = a - b
    print(f"The calculation is {answer}.")
    return answer


@queue.task 
def multiplier_job(a:Annotated[int, typer.Argument(help="First number argument")], 
        b:Annotated[int, typer.Argument(help="Second number argument")]) -> float:
    """
    This multiplier is a part of celery job.
    The job will simulate long processing time with 10 seconds sleep then return with the answer
    """
    logging.debug("Calling `multiplier`")
    for i in range(10):
        time.sleep(1)
        logging.debug(f"Calculation for {i}")

    logging.debug(f"Calculation done!!")
    answer:float = a * b
    print(f"The calculation is {answer}.")
    return answer
