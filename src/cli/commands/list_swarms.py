"""List swarms and their members."""

import asyncio

import typer
from rich.console import Console

from src.cli.output import format_error, format_table, json_output
from src.cli.utils import ConfigManager, validate_swarm_id
from src.cli.utils.config import ConfigError
from src.state import DatabaseManager, MembershipRepository
from src.state.models import SwarmMembership

console = Console()


async def _list_swarms(swarm_id: str | None) -> list[SwarmMembership]:
    """List swarms from local database."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = MembershipRepository(conn)
        if swarm_id:
            membership = await repo.get_swarm(swarm_id)
            return [membership] if membership else []
        return await repo.get_all_swarms()


def list_command(
    swarm_id: str = typer.Option(None, "--swarm", "-s", help="Filter by swarm ID"),
    members: bool = typer.Option(False, "--members", "-m", help="Show member details"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List swarms this agent belongs to."""
    if swarm_id:
        try:
            validate_swarm_id(swarm_id)
        except ValueError as e:
            format_error(console, str(e))
            raise typer.Exit(code=2)

    try:
        swarms = asyncio.run(_list_swarms(swarm_id))
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)
    except Exception as e:
        format_error(console, f"Failed to list swarms: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        data = [
            {
                "swarm_id": s.swarm_id,
                "name": s.name,
                "master": s.master,
                "member_count": len(s.members),
                "joined_at": s.joined_at.isoformat(),
                "members": (
                    [
                        {
                            "agent_id": m.agent_id,
                            "endpoint": m.endpoint,
                            "joined_at": m.joined_at.isoformat(),
                        }
                        for m in s.members
                    ]
                    if members
                    else None
                ),
            }
            for s in swarms
        ]
        json_output(console, {"swarms": data})
        return

    if not swarms:
        console.print("[dim]No swarms found. Create one with 'swarm create'.[/dim]")
        return

    rows = [
        (
            s.swarm_id,
            s.name,
            s.master,
            str(len(s.members)),
            s.joined_at.strftime("%Y-%m-%d"),
        )
        for s in swarms
    ]
    format_table(
        console,
        "Swarms",
        ["ID", "Name", "Master", "Members", "Joined"],
        rows,
    )

    if members:
        for swarm in swarms:
            console.print()
            member_rows = [
                (m.agent_id, m.endpoint, m.joined_at.strftime("%Y-%m-%d %H:%M"))
                for m in swarm.members
            ]
            format_table(
                console,
                f"Members of {swarm.name}",
                ["Agent ID", "Endpoint", "Joined"],
                member_rows,
            )
