"""Mute agents or swarms."""

import asyncio

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, json_output
from src.cli.utils import ConfigManager, validate_agent_id, validate_swarm_id
from src.cli.utils.config import ConfigError
from src.state import DatabaseManager, MuteRepository

console = Console()


async def _mute_agent(agent_id: str, reason: str | None) -> None:
    """Mute an agent."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = MuteRepository(conn)
        await repo.mute_agent(agent_id, reason)


async def _mute_swarm(swarm_id: str, reason: str | None) -> None:
    """Mute a swarm."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = MuteRepository(conn)
        await repo.mute_swarm(swarm_id, reason)


def mute_command(
    agent_id: str = typer.Option(None, "--agent", "-a", help="Agent ID to mute"),
    swarm_id: str = typer.Option(None, "--swarm", "-s", help="Swarm ID to mute"),
    reason: str = typer.Option(None, "--reason", "-r", help="Reason for muting"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Mute an agent or swarm. Muted sources are ignored."""
    if not agent_id and not swarm_id:
        format_error(console, "Must specify --agent or --swarm")
        raise typer.Exit(code=2)

    if agent_id and swarm_id:
        format_error(console, "Specify only one of --agent or --swarm")
        raise typer.Exit(code=2)

    try:
        if agent_id:
            validated_id = validate_agent_id(agent_id)
            asyncio.run(_mute_agent(validated_id, reason))
            target_type, target_id = "agent", validated_id
        else:
            validate_swarm_id(swarm_id)
            asyncio.run(_mute_swarm(swarm_id, reason))
            target_type, target_id = "swarm", swarm_id
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)
    except Exception as e:
        format_error(console, f"Failed to mute: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(console, {"status": "muted", "type": target_type, "id": target_id})
    else:
        format_success(console, f"Muted {target_type} '{target_id}'")
