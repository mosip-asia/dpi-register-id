"""
Typer CLI command group for the register_id submodule.
"""

import typer
from rich import print
from rich.table import Table

cli = typer.Typer(help="Citizen Registration Gateway CLI commands.")


@cli.command("list")
def list_citizens(limit: int = 20):
    """
    List enrolled citizens in the IDRepo database.
    """
    from project.register_id.idrepo import get_idrepo_client

    idrepo = get_idrepo_client()
    citizens = idrepo.list_citizens(limit=limit)

    table = Table(title=f"Enrolled Citizens ({idrepo.active_backend.upper()})")
    table.add_column("UIN", style="cyan", no_wrap=True)
    table.add_column("Full Name", style="bold")
    table.add_column("Email", style="green")
    table.add_column("Enrolled At", style="magenta")

    for c in citizens:
        table.add_row(
            c["uin"],
            c["full_name"],
            c.get("email") or "-",
            str(c.get("created_at") or "-"),
        )

    print(table)


@cli.command("show")
def show_citizen(uin: str):
    """
    Display citizen demographic and biometric details.
    """
    from project.register_id.idrepo import get_idrepo_client

    idrepo = get_idrepo_client()
    citizen = idrepo.get_citizen(uin)
    if not citizen:
        print(f"[red]Citizen UIN '{uin}' not found.[/red]")
        raise typer.Exit(1)

    print(f"[bold cyan]Citizen Details ({uin})[/bold cyan]")
    print(f"  [bold]Full Name:[/bold] {citizen['full_name']}")
    print(f"  [bold]Email:[/bold]     {citizen.get('email')}")
    print(f"  [bold]Created At:[/bold]  {citizen.get('created_at')}")
    print(f"  [bold]CBEFF XML:[/bold]   {'Present' if citizen.get('cbeff_xml') else 'None'}")


@cli.command("check-backend")
def check_backend():
    """
    Verify identity repository database connectivity.
    """
    from project.register_id.idrepo import get_idrepo_client

    idrepo = get_idrepo_client()
    print(f"IDRepo active backend: [bold green]{idrepo.active_backend.upper()}[/bold green]")
