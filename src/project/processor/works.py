from typing import Annotated
import typer
from typer import Typer
import logging
import time

cli = Typer()

@cli.command()
def addition(a:Annotated[int, typer.Argument(help="First number argument")], 
        b:Annotated[int, typer.Argument(help="Second number argument")]):
    """
    It will perform an addition between `a` and `b`.
    """
    logging.debug("Calling `addition`")
    answer:int = a + b
    print(f"The calculation is {answer}.")
    return answer

@cli.command()
def subtraction(a:Annotated[int, typer.Argument(help="First number argument")], 
        b:Annotated[int, typer.Argument(help="Second number argument")]) -> int:
    """
    It will perform a subtraction between `a` and `b`.
    """
    logging.debug("Calling `subtraction`")
    answer:int = a - b
    print(f"The calculation is {answer}.")
    return answer

@cli.command()
def multiplier(a:Annotated[int, typer.Argument(help="First number argument")], 
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
