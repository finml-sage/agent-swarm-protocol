"""List sent messages from the local outbox."""

import asyncio

import typer
from rich.console import Console

from src.cli.output import format_error, format_table, json_output
from src.cli.utils import ConfigManager, validate_swarm_id
from src.cli.utils.config import ConfigError
from src.state import DatabaseManager, OutboxRepository

console = Console()


async def _list_sent(swarm_id: str, limit: int) -> list[dict]:
    """Fetch sent messages from the local outbox."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = OutboxRepository(conn)
        messages = await repo.list_by_swarm(swarm_id, limit=limit)

    return [
        {
            "message_id": m.message_id,
            "swarm_id": m.swarm_id,
            "recipient_id": m.recipient_id,
            "message_type": m.message_type,
            "content": m.content,
            "sent_at": m.sent_at.isoformat(),
            "status": m.status.value,
            "error": m.error,
        }
        for m in messages
    ]


async def _count_sent(swarm_id: str) -> dict[str, int]:
    """Count sent messages grouped by status."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = OutboxRepository(conn)
        return await repo.count_by_swarm(swarm_id)


def _truncate(text: str, length: int) -> str:
    return text[:length] + "..." if len(text) > length else text


def sent_command(
    swarm_id: str, limit: int, count: bool, json_flag: bool,
) -> None:
    """List sent messages from the local outbox."""
    try:
        swarm_uuid = validate_swarm_id(swarm_id)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)

    sid = str(swarm_uuid)

    if count:
        try:
            data = asyncio.run(_count_sent(sid))
        except ConfigError as e:
            format_error(console, str(e), hint="Run 'swarm init' first")
            raise typer.Exit(code=1)
        except Exception as e:
            format_error(console, f"Failed to count sent messages: {e}")
            raise typer.Exit(code=1)

        if json_flag:
            json_output(console, {"swarm_id": sid, **data})
        else:
            console.print(f"[cyan]Sent messages:[/cyan] {data['total']}")
        return

    try:
        msgs = asyncio.run(_list_sent(sid, limit))
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' first")
        raise typer.Exit(code=1)
    except Exception as e:
        format_error(console, f"Failed to list sent messages: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(console, {"swarm_id": sid, "count": len(msgs), "messages": msgs})
        return

    if not msgs:
        console.print("[yellow]No sent messages found[/yellow]")
        return

    rows = [
        (
            m["message_id"][:12] + "...",
            m["recipient_id"],
            m["status"],
            m["sent_at"][:19],
            _truncate(m["content"], 60),
        )
        for m in msgs
    ]
    format_table(
        console,
        f"Sent Messages ({len(msgs)})",
        ["ID", "Recipient", "Status", "Sent At", "Content"],
        rows,
    )
