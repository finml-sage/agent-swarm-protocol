"""Import agent state from JSON."""

import asyncio
import json as json_lib
from pathlib import Path

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, format_warning, json_output
from src.cli.utils import ConfigManager
from src.cli.utils.config import ConfigError
from src.state import DatabaseManager, import_state_from_file, StateImportError

console = Console()


async def _import(input_path: Path, merge: bool) -> dict:
    """Import state from file and return summary."""
    config = ConfigManager()
    agent_config = config.load()
    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    with open(input_path, "r", encoding="utf-8") as f:
        state = json_lib.load(f)

    await import_state_from_file(db, input_path, merge=merge)

    version = state.get("schema_version", "unknown")
    inbox_key = "inbox" if version == "2.0.0" else "message_queue"
    return {
        "source": str(input_path),
        "merge": merge,
        "schema_version": version,
        "swarms": len(state.get("swarms", {})),
        "public_keys": len(state.get("public_keys", {})),
        "muted_agents": len(state.get("muted_agents", [])),
        "muted_swarms": len(state.get("muted_swarms", [])),
        "inbox": len(state.get(inbox_key, [])),
        "outbox": len(state.get("outbox", [])),
    }


def import_command(
    input_path: str,
    merge: bool,
    yes: bool,
    json_flag: bool,
) -> None:
    """Import agent state from JSON file."""
    path = Path(input_path)
    if not path.exists():
        format_error(console, f"File not found: {path}")
        raise typer.Exit(code=5)

    if not merge and not yes:
        format_warning(console, "This will REPLACE all existing state")
        if not typer.confirm("Continue?"):
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(code=0)

    try:
        summary = asyncio.run(_import(path, merge))
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' first")
        raise typer.Exit(code=1)
    except StateImportError as e:
        format_error(console, f"Import failed: {e}")
        raise typer.Exit(code=2)
    except Exception as e:
        format_error(console, f"Import failed: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(console, {"status": "imported", **summary})
        return

    mode = "merged into" if merge else "imported to"
    format_success(console, f"State {mode} local database")
    console.print(f"[cyan]Source:[/cyan]       {summary['source']}")
    console.print(f"[cyan]Schema:[/cyan]       {summary['schema_version']}")
    console.print(f"[cyan]Swarms:[/cyan]       {summary['swarms']}")
    console.print(f"[cyan]Public Keys:[/cyan]  {summary['public_keys']}")
    console.print(f"[cyan]Muted Agents:[/cyan] {summary['muted_agents']}")
    console.print(f"[cyan]Muted Swarms:[/cyan] {summary['muted_swarms']}")
    console.print(f"[cyan]Inbox:[/cyan]        {summary['inbox']}")
    console.print(f"[cyan]Outbox:[/cyan]       {summary['outbox']}")
