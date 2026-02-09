"""List and manage messages in the queue."""

import asyncio

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, format_table, json_output
from src.cli.utils import ConfigManager, validate_swarm_id
from src.cli.utils.config import ConfigError
from src.state import DatabaseManager, MessageRepository
from src.state.models.message import MessageStatus

console = Console()

_VALID_STATUSES = ("pending", "completed", "failed", "all")


async def _db_repo():
    """Return an initialized DatabaseManager."""
    config = ConfigManager()
    agent_config = config.load()
    db = DatabaseManager(agent_config.db_path)
    await db.initialize()
    return db


async def _list_messages(swarm_id_str: str, limit: int, status_filter: str) -> list[dict]:
    """Fetch messages from queue via repository layer."""
    db = await _db_repo()
    async with db.connection() as conn:
        repo = MessageRepository(conn)
        if status_filter == "all":
            messages = await repo.list_by_status(swarm_id_str, status=None, limit=limit)
        else:
            ms = MessageStatus(status_filter)
            messages = await repo.list_by_status(swarm_id_str, status=ms, limit=limit)
        return [_msg_dict(m) for m in messages]


def _msg_dict(m) -> dict:
    return {
        "message_id": m.message_id, "sender_id": m.sender_id,
        "message_type": m.message_type, "status": m.status.value,
        "received_at": m.received_at.isoformat(), "content_preview": m.content[:200],
    }


async def _ack_message(message_id: str) -> bool:
    """Mark a message as completed."""
    db = await _db_repo()
    async with db.connection() as conn:
        return await MessageRepository(conn).complete(message_id)


async def _pending_count(swarm_id_str: str) -> int:
    """Get pending message count."""
    db = await _db_repo()
    async with db.connection() as conn:
        return await MessageRepository(conn).get_pending_count(swarm_id_str)


def _run_async(coro, error_label: str):
    """Run async operation with standard error handling."""
    try:
        return asyncio.run(coro)
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' first")
        raise typer.Exit(code=1)
    except Exception as e:
        format_error(console, f"Failed to {error_label}: {e}")
        raise typer.Exit(code=1)


def messages_command(
    swarm_id: str | None, limit: int, status_filter: str,
    ack: str | None, count: bool, json_flag: bool,
) -> None:
    """List and manage messages."""
    if ack:
        result = _run_async(_ack_message(ack), "ack message")
        if json_flag:
            status = "acked" if result else "not_found"
            json_output(console, {"status": status, "message_id": ack})
        elif result:
            format_success(console, f"Message {ack[:12]}... marked as completed")
        else:
            format_error(console, f"Message {ack} not found")
            raise typer.Exit(code=5)
        return

    if status_filter not in _VALID_STATUSES:
        format_error(
            console, f"Invalid status '{status_filter}'",
            hint=f"Valid values: {', '.join(_VALID_STATUSES)}",
        )
        raise typer.Exit(code=2)

    if not swarm_id:
        format_error(console, "Swarm ID is required for listing messages",
                     hint="Use -s/--swarm <swarm_id>")
        raise typer.Exit(code=2)
    try:
        swarm_uuid = validate_swarm_id(swarm_id)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)
    sid = str(swarm_uuid)

    if count:
        pending = _run_async(_pending_count(sid), "get count")
        if json_flag:
            json_output(console, {"swarm_id": sid, "pending_count": pending})
        else:
            console.print(f"[cyan]Pending messages:[/cyan] {pending}")
        return

    msgs = _run_async(_list_messages(sid, limit, status_filter), "list messages")
    if json_flag:
        json_output(console, {"swarm_id": sid, "count": len(msgs), "messages": msgs})
        return
    if not msgs:
        console.print("[yellow]No messages found[/yellow]")
        return
    rows = [
        (m["message_id"][:12] + "...", m["sender_id"], m["status"],
         m["received_at"][:19], _truncate(m["content_preview"], 60))
        for m in msgs
    ]
    format_table(console, f"Messages ({len(msgs)})",
                 ["ID", "Sender", "Status", "Received", "Content"], rows)


def _truncate(text: str, length: int) -> str:
    return text[:length] + "..." if len(text) > length else text
