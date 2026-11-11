"""
Typer CLI command group for mock services.
"""

import typer

cli = typer.Typer(help="MOSIP Substrate Mock Services.")
idrepo_cli = typer.Typer(help="MOSIP Mock IDRepo Service.")


@idrepo_cli.command("serve")
def serve_idrepo(host: str = "0.0.0.0", port: int = 8080):
    """
    Start the MOSIP Mock IDRepo REST API service.
    """
    from mock.idrepo.app import run_idrepo_server
    run_idrepo_server(host=host, port=port)


cli.add_typer(idrepo_cli, name="idrepo", help="Mock IDRepo server commands.")
