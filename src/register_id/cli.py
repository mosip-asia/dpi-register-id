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
    List enrolled citizens via the MOSIP IDRepo REST interface.
    """
    from register_id.idrepo_client import get_idrepo_client

    idrepo = get_idrepo_client()
    citizens = idrepo.list_identities(limit=limit)

    table = Table(title=f"Enrolled Citizens via MOSIP IDRepo ({idrepo.base_url})")
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
    Display citizen demographic and biometric details from MOSIP IDRepo.
    """
    from register_id.idrepo_client import get_idrepo_client

    idrepo = get_idrepo_client()
    citizen = idrepo.get_identity(uin)
    if not citizen:
        print(f"[red]Citizen UIN '{uin}' not found in IDRepo.[/red]")
        raise typer.Exit(1)

    print(f"[bold cyan]Citizen Details ({uin})[/bold cyan]")
    print(f"  [bold]Full Name:[/bold] {citizen['full_name']}")
    print(f"  [bold]Email:[/bold]     {citizen.get('email')}")
    print(f"  [bold]Created At:[/bold]  {citizen.get('created_at')}")
    print(f"  [bold]CBEFF XML:[/bold]   {'Present' if citizen.get('cbeff_xml') else 'None'}")


@cli.command("check-backend")
def check_backend():
    """
    Verify MOSIP IDRepo REST service and Keycloak connectivity.
    """
    from register_id.idrepo_client import get_idrepo_client

    idrepo = get_idrepo_client()
    health = idrepo.check_health()
    status = health.get("status", "UNKNOWN")
    color = "green" if status in ("UP", "SUCCESS") else "red"
    print(f"MOSIP IDRepo Endpoint: [cyan]{idrepo.base_url}[/cyan]")
    print(f"MOSIP IDRepo Status:   [{color}]{status}[/{color}] (info: {health})")

