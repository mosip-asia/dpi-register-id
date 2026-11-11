"""
This module shows an example of developing a cli with `typer`
Learn more [here](https://typer.tiangolo.com/tutorial/printing/#rich-markup)
"""

import typer
from rich import print
from typing import Annotated

import os
import logging

_PROJECT_NAME = os.environ["PROJECT_NAME"]

# adding command
from project.processor import cli as processor_cli
from project.processor_celery import cli as processor_celery_cli
from project.web import cli as web_cli

cli = typer.Typer()
cli.add_typer(processor_cli, 
              name="processor",
              help="The processor module.")
cli.add_typer(processor_celery_cli, 
              name="processor_celery",
              help="The processory module that will use celery as Queue")
cli.add_typer(web_cli, name="web", help="The cli for web module")

@cli.command()
def command_1():
    """
    This is the default command. You can find this command in `src/python_project_stater/cli.py`.
    """
    logging.debug("Calling `command_1`")
    print(f"Welcome to {_PROJECT_NAME}")
