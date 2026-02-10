"""List and manage messages via the server inbox API.

Uses the /api/inbox endpoints (issue #154-#156) which provide unread/read/
archived/deleted status lifecycle.  Auto-marks unread messages as read after
display unless --no-mark-read is specified.  Also supports --archive,
--delete, and --archive-all operations.
"""

import asyncio
from urllib.parse import urlparse, urlunparse

import httpx
import typer
from rich.console import Console

from src.cli.output import format_error, format_success, format_table, json_output
from src.cli.utils import ConfigManager, validate_swarm_id
from src.cli.utils.config import ConfigError

console = Console()

_VALID_STATUSES = ("unread", "read", "archived", "all")

_HTTP_TIMEOUT = 15.0


def _server_base_url(endpoint: str) -> str:
    """Derive the server base URL from the agent's configured endpoint.

    The agent endpoint looks like ``https://host.example.com/swarm``.
    The inbox API lives at ``/api/inbox`` on the same origin.

    Returns:
        Base URL such as ``https://host.example.com``.
    """
    parsed = urlparse(endpoint)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


async def _fetch_inbox(
    base_url: str, swarm_id: str, limit: int, status_filter: str,
) -> dict:
    """GET /api/inbox from the server."""
    params: dict[str, str | int] = {
        "swarm_id": swarm_id,
        "status": status_filter,
        "limit": limit,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{base_url}/api/inbox", params=params)
        resp.raise_for_status()
        return resp.json()


async def _fetch_count(base_url: str, swarm_id: str) -> dict:
    """GET /api/inbox/count from the server."""
    params = {"swarm_id": swarm_id}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{base_url}/api/inbox/count", params=params)
        resp.raise_for_status()
        return resp.json()


async def _batch_mark_read(base_url: str, message_ids: list[str]) -> dict:
    """POST /api/inbox/batch to mark messages as read."""
    body = {"message_ids": message_ids, "action": "read"}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(f"{base_url}/api/inbox/batch", json=body)
        resp.raise_for_status()
        return resp.json()


async def _batch_inbox_action(
    base_url: str, message_ids: list[str], action: str,
) -> dict:
    """POST /api/inbox/batch on the server."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{base_url}/api/inbox/batch",
            json={"message_ids": message_ids, "action": action},
        )
        resp.raise_for_status()
        return resp.json()



async def _archive_message(base_url: str, message_id: str) -> dict:
    """POST /api/inbox/{id}/archive."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(f"{base_url}/api/inbox/{message_id}/archive")
        if resp.status_code in (200, 400, 404):
            return resp.json()
        resp.raise_for_status()
        return resp.json()


async def _delete_message(base_url: str, message_id: str) -> dict:
    """POST /api/inbox/{id}/delete."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(f"{base_url}/api/inbox/{message_id}/delete")
        if resp.status_code in (200, 404):
            return resp.json()
        resp.raise_for_status()
        return resp.json()


def _run_async(coro, error_label: str):
    """Run async operation with standard error handling."""
    try:
        return asyncio.run(coro)
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' first")
        raise typer.Exit(code=1)
    except httpx.HTTPStatusError as e:
        format_error(
            console,
            f"Server returned {e.response.status_code} when trying to {error_label}",
            hint="Is the swarm server running?",
        )
        raise typer.Exit(code=3)
    except httpx.ConnectError:
        format_error(
            console,
            f"Could not connect to server to {error_label}",
            hint="Is the swarm server running? Check your endpoint in ~/.swarm/config.yaml",
        )
        raise typer.Exit(code=3)
    except httpx.TimeoutException:
        format_error(
            console,
            f"Server request timed out while trying to {error_label}",
            hint="The server may be overloaded. Try again or increase timeout.",
        )
        raise typer.Exit(code=3)
    except Exception as e:
        format_error(console, f"Failed to {error_label}: {e}")
        raise typer.Exit(code=1)


def _load_base_url() -> str:
    """Load config and return the server base URL."""
    config = ConfigManager()
    agent_config = config.load()
    return _server_base_url(agent_config.endpoint)


def _truncate(text: str, length: int) -> str:
    return text[:length] + "..." if len(text) > length else text


def _handle_archive(archive_id: str, json_flag: bool) -> None:
    """Archive a specific message."""
    base_url = _load_base_url()
    data = _run_async(_archive_message(base_url, archive_id), "archive message")
    if json_flag:
        json_output(console, data)
    elif "error" in data:
        format_error(console, data["error"])
        raise typer.Exit(code=5 if "not found" in data["error"] else 1)
    else:
        format_success(console, f"Message {archive_id[:12]}... archived")


def _handle_delete(delete_id: str, json_flag: bool) -> None:
    """Soft-delete a specific message."""
    base_url = _load_base_url()
    data = _run_async(_delete_message(base_url, delete_id), "delete message")
    if json_flag:
        json_output(console, data)
    elif "error" in data:
        format_error(console, data["error"])
        raise typer.Exit(code=1)
    else:
        format_success(console, f"Message {delete_id[:12]}... deleted")



def _handle_archive_all(
    swarm_id: str, json_flag: bool,
) -> None:
    """Archive all read messages in a swarm."""
    if not swarm_id:
        format_error(
            console, "Swarm ID is required for --archive-all",
            hint="Use -s/--swarm <swarm_id>",
        )
        raise typer.Exit(code=2)
    try:
        swarm_uuid = validate_swarm_id(swarm_id)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)
    sid = str(swarm_uuid)

    base_url = _load_base_url()
    inbox_data = _run_async(
        _fetch_inbox(base_url, sid, 100, "read"),
        "fetch read messages",
    )
    messages_list = inbox_data.get("messages", [])
    if not messages_list:
        if json_flag:
            json_output(console, {"action": "archive", "updated": 0, "total": 0})
        else:
            console.print("[yellow]No read messages to archive[/yellow]")
        return

    msg_ids = [m["message_id"] for m in messages_list]
    batch_data = _run_async(
        _batch_inbox_action(base_url, msg_ids, "archive"),
        "batch archive messages",
    )
    if json_flag:
        json_output(console, batch_data)
    else:
        format_success(
            console,
            f"Archived {batch_data['updated']} of {batch_data['total']} read messages",
        )


def messages_command(
    swarm_id: str | None, limit: int, status_filter: str,
    archive: str | None, delete: str | None,
    no_mark_read: bool, count: bool, json_flag: bool,
    archive_all: bool = False,
) -> None:
    """List and manage messages via the server inbox API."""
    # Archive mode
    if archive:
        try:
            _handle_archive(archive, json_flag)
        except ConfigError as e:
            format_error(console, str(e), hint="Run 'swarm init' first")
            raise typer.Exit(code=1)
        return

    # Delete mode
    if delete:
        try:
            _handle_delete(delete, json_flag)
        except ConfigError as e:
            format_error(console, str(e), hint="Run 'swarm init' first")
            raise typer.Exit(code=1)
        return

    # Archive-all mode
    if archive_all:
        try:
            _handle_archive_all(swarm_id, json_flag)
        except ConfigError as e:
            format_error(console, str(e), hint="Run 'swarm init' first")
            raise typer.Exit(code=1)
        return

    # Validate status filter
    if status_filter not in _VALID_STATUSES:
        format_error(
            console, f"Invalid status '{status_filter}'",
            hint=f"Valid values: {', '.join(_VALID_STATUSES)}",
        )
        raise typer.Exit(code=2)

    # Validate swarm_id
    if not swarm_id:
        format_error(
            console, "Swarm ID is required for listing messages",
            hint="Use -s/--swarm <swarm_id>",
        )
        raise typer.Exit(code=2)
    try:
        swarm_uuid = validate_swarm_id(swarm_id)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)
    sid = str(swarm_uuid)

    # Load server base URL
    try:
        base_url = _load_base_url()
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' first")
        raise typer.Exit(code=1)

    # Count mode
    if count:
        data = _run_async(_fetch_count(base_url, sid), "get count")
        if json_flag:
            json_output(console, {"swarm_id": sid, **data})
        else:
            console.print(f"[cyan]Unread:[/cyan] {data['unread']}  "
                          f"[dim]Read:[/dim] {data['read']}  "
                          f"[dim]Total:[/dim] {data['total']}")
        return

    # List mode
    data = _run_async(_fetch_inbox(base_url, sid, limit, status_filter), "list messages")
    msgs = data.get("messages", [])

    # Auto-mark-read: after listing unread messages, mark them as read
    unread_ids = []
    if status_filter == "unread" and not no_mark_read and msgs:
        unread_ids = [m["message_id"] for m in msgs if m.get("status") == "unread"]
        if unread_ids:
            _run_async(_batch_mark_read(base_url, unread_ids), "mark messages as read")

    if json_flag:
        payload = {"swarm_id": sid, "count": len(msgs), "messages": msgs}
        if unread_ids:
            payload["marked_read"] = len(unread_ids)
        json_output(console, payload)
        return
    if not msgs:
        console.print("[yellow]No messages found[/yellow]")
        return

    # Build header with counts
    header = f"Inbox ({len(msgs)} messages)"
    if unread_ids:
        header += f" - {len(unread_ids)} marked as read"

    rows = [
        (
            m["message_id"][:12] + "...",
            m["sender_id"],
            m["status"],
            m["received_at"][:19],
            _truncate(m.get("content_preview", ""), 60),
        )
        for m in msgs
    ]
    format_table(
        console, header,
        ["ID", "Sender", "Status", "Received", "Content"],
        rows,
    )
