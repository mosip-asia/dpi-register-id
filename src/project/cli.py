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
from register_id import cli as register_id_cli

cli = typer.Typer()
cli.add_typer(
    register_id_cli,
    name="register_id",
    help="Citizen Registration Gateway: manage citizens, IDRepo & liveness.",
)

idrepo_cli = typer.Typer(help="MOSIP IDRepo Service utilities.")


@idrepo_cli.command("serve")
def serve_idrepo(host: str = "0.0.0.0", port: int = 8080):
    """
    Start the MOSIP IDRepo mock REST service.
    """
    from register_id.mock_idrepo import run_idrepo_server
    run_idrepo_server(host=host, port=port)


cli.add_typer(idrepo_cli, name="idrepo", help="MOSIP Identity Repository (REST API service).")
cli.add_typer(processor_cli, 
              name="processor",
              help="The processor module (demo/tutorial).")
cli.add_typer(processor_celery_cli, 
              name="processor_celery",
              help="The processory module that will use celery as Queue (demo/tutorial)")
cli.add_typer(web_cli, name="web", help="The cli for web module")

@cli.command()
def command_1():
    """
    This is the default command. You can find this command in `src/project/cli.py`.
    """
    logging.debug("Calling `command_1`")
    print(f"Welcome to {_PROJECT_NAME}")
