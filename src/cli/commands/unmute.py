"""Unmute previously muted agents or swarms."""

import asyncio

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, json_output
from src.cli.utils import (
    ConfigManager,
    SwarmIdError,
    resolve_swarm_id,
    validate_agent_id,
)
from src.cli.utils.config import ConfigError
from src.state import DatabaseManager, MuteRepository

console = Console()


async def _unmute_agent(agent_id: str) -> bool:
    """Unmute an agent. Returns True if was muted."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = MuteRepository(conn)
        return await repo.unmute_agent(agent_id)


async def _unmute_swarm(swarm_id: str) -> bool:
    """Unmute a swarm. Returns True if was muted."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = MuteRepository(conn)
        return await repo.unmute_swarm(swarm_id)


def unmute_command(
    agent_id: str | None,
    swarm_id: str | None,
    json_flag: bool,
) -> None:
    """Unmute a previously muted agent or swarm."""
    if not agent_id and not swarm_id:
        format_error(console, "Must specify --agent or --swarm")
        raise typer.Exit(code=2)

    if agent_id and swarm_id:
        format_error(console, "Specify only one of --agent or --swarm")
        raise typer.Exit(code=2)

    try:
        if agent_id:
            validated_id = validate_agent_id(agent_id)
            was_muted = asyncio.run(_unmute_agent(validated_id))
            target_type, target_id = "agent", validated_id
        else:
            swarm_uuid = resolve_swarm_id(swarm_id)
            was_muted = asyncio.run(_unmute_swarm(str(swarm_uuid)))
            target_type, target_id = "swarm", str(swarm_uuid)
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)
    except (SwarmIdError, ValueError) as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)
    except Exception as e:
        format_error(console, f"Failed to unmute: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(
            console,
            {
                "status": "unmuted",
                "type": target_type,
                "id": target_id,
                "was_muted": was_muted,
            },
        )
    elif was_muted:
        format_success(console, f"Unmuted {target_type} '{target_id}'")
    else:
        console.print(f"[dim]{target_type.title()} '{target_id}' was not muted[/dim]")
