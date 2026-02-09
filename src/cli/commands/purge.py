"""Purge soft-deleted inbox messages and expired sessions."""

import asyncio

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, format_warning, json_output
from src.cli.utils import ConfigManager
from src.cli.utils.config import ConfigError
from src.state import DatabaseManager, InboxRepository, SessionRepository

console = Console()

_DEFAULT_TIMEOUT_MINUTES = 60
_DEFAULT_RETENTION_HOURS = 24


async def _purge(
    messages: bool,
    sessions: bool,
    include_archived: bool,
    timeout_minutes: int,
    retention_hours: int | None,
) -> dict:
    """Purge deleted/archived inbox messages and expired sessions."""
    config = ConfigManager()
    agent_config = config.load()
    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    result: dict = {}
    async with db.connection() as conn:
        if messages:
            repo = InboxRepository(conn)
            deleted_count = await repo.purge_deleted(
                older_than_hours=retention_hours,
            )
            result["messages_purged"] = deleted_count
            if retention_hours is not None:
                result["retention_hours"] = retention_hours
            if include_archived:
                archived_count = await repo.purge_archived()
                result["archived_purged"] = archived_count
        if sessions:
            repo = SessionRepository(conn)
            result["sessions_purged"] = await repo.purge_expired(timeout_minutes)
            result["timeout_minutes"] = timeout_minutes
    return result


def purge_command(
    messages: bool,
    sessions: bool,
    include_archived: bool,
    timeout_minutes: int,
    retention_hours: int,
    force: bool,
    yes: bool,
    json_flag: bool,
) -> None:
    """Purge soft-deleted inbox messages and expired sessions."""
    if not messages and not sessions:
        format_error(
            console,
            "Specify --messages, --sessions, or both",
            hint="swarm purge --messages --sessions",
        )
        raise typer.Exit(code=2)

    # Determine effective retention: None means purge everything
    effective_retention: int | None = None if force else retention_hours

    if not yes:
        targets = []
        if messages:
            if force:
                label = "ALL soft-deleted inbox messages (no retention)"
            else:
                label = (
                    f"soft-deleted inbox messages older than {retention_hours}h"
                )
            if include_archived:
                label += " and archived messages"
            targets.append(label)
        if sessions:
            targets.append(f"sessions idle > {timeout_minutes} minutes")
        format_warning(console, f"Will purge: {', '.join(targets)}")
        if not typer.confirm("Continue?"):
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(code=0)

    try:
        result = asyncio.run(
            _purge(
                messages, sessions, include_archived,
                timeout_minutes, effective_retention,
            )
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
        format_success(console, f"Purged {result['messages_purged']} deleted messages")
    if "archived_purged" in result:
        format_success(console, f"Purged {result['archived_purged']} archived messages")
    if "sessions_purged" in result:
        format_success(console, f"Purged {result['sessions_purged']} expired sessions")
