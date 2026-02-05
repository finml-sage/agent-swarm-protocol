"""Show agent and connection status."""

import asyncio

import typer
from rich.console import Console

from src.cli.output import format_error, format_table, json_output
from src.cli.utils import ConfigManager
from src.cli.utils.config import ConfigError
from src.client import public_key_to_base64
from src.state import DatabaseManager, MembershipRepository, MuteRepository

console = Console()


async def _get_status(verbose: bool) -> dict:
    """Get agent status information."""
    config = ConfigManager()
    agent_config = config.load()

    public_key_b64 = public_key_to_base64(agent_config.private_key.public_key())

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        membership_repo = MembershipRepository(conn)
        mute_repo = MuteRepository(conn)

        swarms = await membership_repo.get_all_swarms()
        muted_agents = await mute_repo.get_all_muted_agents()
        muted_swarms = await mute_repo.get_all_muted_swarms()

    status = {
        "agent_id": agent_config.agent_id,
        "endpoint": agent_config.endpoint,
        "public_key": public_key_b64,
        "config_path": str(config.config_path),
        "db_path": str(agent_config.db_path),
        "swarm_count": len(swarms),
        "muted_agents": len(muted_agents),
        "muted_swarms": len(muted_swarms),
    }

    if verbose:
        status["swarms"] = [
            {
                "swarm_id": s.swarm_id,
                "name": s.name,
                "master": s.master,
                "is_master": s.master == agent_config.agent_id,
                "member_count": len(s.members),
            }
            for s in swarms
        ]
        status["muted_agent_ids"] = [m.agent_id for m in muted_agents]
        status["muted_swarm_ids"] = [m.swarm_id for m in muted_swarms]

    return status


def status_command(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed status"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show agent configuration and connection status."""
    try:
        status = asyncio.run(_get_status(verbose))
    except ConfigError as e:
        if json_flag:
            json_output(console, {"status": "not_initialized", "error": str(e)})
        else:
            format_error(
                console, str(e), hint="Run 'swarm init' to configure your agent"
            )
        raise typer.Exit(code=1)
    except Exception as e:
        format_error(console, f"Failed to get status: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(console, {"status": "initialized", **status})
        return

    console.print("[bold]Agent Status[/bold]")
    console.print()
    console.print(f"[cyan]Agent ID:[/cyan]     {status['agent_id']}")
    console.print(f"[cyan]Endpoint:[/cyan]     {status['endpoint']}")
    console.print(f"[cyan]Public Key:[/cyan]   {status['public_key'][:32]}...")
    console.print(f"[cyan]Config:[/cyan]       {status['config_path']}")
    console.print(f"[cyan]Database:[/cyan]     {status['db_path']}")
    console.print()
    console.print(f"[cyan]Swarms:[/cyan]       {status['swarm_count']}")
    console.print(f"[cyan]Muted Agents:[/cyan] {status['muted_agents']}")
    console.print(f"[cyan]Muted Swarms:[/cyan] {status['muted_swarms']}")

    if verbose and status.get("swarms"):
        console.print()
        rows = [
            (
                s["swarm_id"][:8] + "...",
                s["name"],
                "Yes" if s["is_master"] else "No",
                str(s["member_count"]),
            )
            for s in status["swarms"]
        ]
        format_table(
            console,
            "Swarm Memberships",
            ["ID", "Name", "Master", "Members"],
            rows,
        )
