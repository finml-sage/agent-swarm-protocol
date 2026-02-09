"""Export agent state to JSON."""

import asyncio
import json as json_lib
from pathlib import Path

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, json_output
from src.cli.utils import ConfigManager
from src.cli.utils.config import ConfigError
from src.state import DatabaseManager, export_state, export_state_to_file

console = Console()


async def _export(output_path: Path | None) -> dict:
    """Export state, optionally writing to a file."""
    config = ConfigManager()
    agent_config = config.load()
    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    if output_path:
        await export_state_to_file(db, agent_config.agent_id, output_path)

    return await export_state(db, agent_config.agent_id)


def export_command(
    output: str | None,
    json_flag: bool,
) -> None:
    """Export agent state to JSON."""
    output_path = Path(output) if output else None

    try:
        state = asyncio.run(_export(output_path))
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' first")
        raise typer.Exit(code=1)
    except Exception as e:
        format_error(console, f"Export failed: {e}")
        raise typer.Exit(code=1)

    if json_flag or not output_path:
        json_output(console, state)
        return

    swarm_count = len(state.get("swarms", {}))
    key_count = len(state.get("public_keys", {}))
    muted_agents = len(state.get("muted_agents", []))
    muted_swarms = len(state.get("muted_swarms", []))
    inbox_count = len(state.get("inbox", []))
    outbox_count = len(state.get("outbox", []))

    format_success(console, f"State exported to {output_path}")
    console.print(f"[cyan]Schema:[/cyan]       {state.get('schema_version', 'unknown')}")
    console.print(f"[cyan]Swarms:[/cyan]       {swarm_count}")
    console.print(f"[cyan]Public Keys:[/cyan]  {key_count}")
    console.print(f"[cyan]Muted Agents:[/cyan] {muted_agents}")
    console.print(f"[cyan]Muted Swarms:[/cyan] {muted_swarms}")
    console.print(f"[cyan]Inbox:[/cyan]        {inbox_count}")
    console.print(f"[cyan]Outbox:[/cyan]       {outbox_count}")
