"""Purge old messages and expired sessions."""

import asyncio

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, format_warning, json_output
from src.cli.utils import ConfigManager
from src.cli.utils.config import ConfigError
from src.state import DatabaseManager, MessageRepository, SessionRepository

console = Console()

_DEFAULT_RETENTION_DAYS = 30
_DEFAULT_TIMEOUT_MINUTES = 60


async def _purge(
    messages: bool,
    sessions: bool,
    retention_days: int,
    timeout_minutes: int,
) -> dict:
    """Purge old data and return counts."""
    config = ConfigManager()
    agent_config = config.load()
    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    result: dict = {}
    async with db.connection() as conn:
        if messages:
            repo = MessageRepository(conn)
            result["messages_purged"] = await repo.purge_old(retention_days)
            result["retention_days"] = retention_days
        if sessions:
            repo = SessionRepository(conn)
            result["sessions_purged"] = await repo.purge_expired(timeout_minutes)
            result["timeout_minutes"] = timeout_minutes
    return result


def purge_command(
    messages: bool,
    sessions: bool,
    retention_days: int,
    timeout_minutes: int,
    yes: bool,
    json_flag: bool,
) -> None:
    """Purge old messages and expired sessions."""
    if not messages and not sessions:
        format_error(
            console,
            "Specify --messages, --sessions, or both",
            hint="swarm purge --messages --sessions",
        )
        raise typer.Exit(code=2)

    if not yes:
        targets = []
        if messages:
            targets.append(f"messages older than {retention_days} days")
        if sessions:
            targets.append(f"sessions idle > {timeout_minutes} minutes")
        format_warning(console, f"Will purge: {', '.join(targets)}")
        if not typer.confirm("Continue?"):
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(code=0)

    try:
        result = asyncio.run(
            _purge(messages, sessions, retention_days, timeout_minutes)
        )
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' first")
        raise typer.Exit(code=1)
    except Exception as e:
        format_error(console, f"Purge failed: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(console, {"status": "purged", **result})
        return

    if "messages_purged" in result:
        format_success(console, f"Purged {result['messages_purged']} old messages")
    if "sessions_purged" in result:
        format_success(console, f"Purged {result['sessions_purged']} expired sessions")
