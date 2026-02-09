"""List and manage messages via the server inbox API.

Prior to issue #151, this command read from the local client DB
(~/.swarm/swarm.db) which has zero inbound messages.  Now it queries
the server REST API at /api/messages, which reads from the actual
server-side message_queue where inbound A2A messages are stored.
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

_VALID_STATUSES = ("pending", "completed", "failed", "all")

_HTTP_TIMEOUT = 15.0


def _server_base_url(endpoint: str) -> str:
    """Derive the server base URL from the agent's configured endpoint.

    The agent endpoint looks like ``https://host.example.com/swarm``
    (or ``https://host.example.com/swarm/``).  The inbox API lives at
    ``/api/messages`` on the same origin, so we strip the path to get
    the scheme+host base URL.

    Returns:
        Base URL such as ``https://host.example.com``.
    """
    parsed = urlparse(endpoint)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


async def _fetch_messages(
    base_url: str, swarm_id: str, limit: int, status_filter: str,
) -> dict:
    """GET /api/messages from the server."""
    params: dict[str, str | int] = {
        "swarm_id": swarm_id,
        "status": status_filter,
        "limit": limit,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{base_url}/api/messages", params=params)
        resp.raise_for_status()
        return resp.json()


async def _fetch_count(base_url: str, swarm_id: str) -> dict:
    """GET /api/messages/count from the server."""
    params = {"swarm_id": swarm_id}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(f"{base_url}/api/messages/count", params=params)
        resp.raise_for_status()
        return resp.json()


async def _ack_message_api(base_url: str, message_id: str) -> dict:
    """POST /api/messages/{message_id}/ack on the server.

    Returns the JSON body for both 200 (acked) and 404 (not_found).
    Only raises for unexpected HTTP errors.
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(f"{base_url}/api/messages/{message_id}/ack")
        if resp.status_code in (200, 404):
            return resp.json()
        resp.raise_for_status()
        return resp.json()  # unreachable but keeps type checker happy


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


def messages_command(
    swarm_id: str | None, limit: int, status_filter: str,
    ack: str | None, count: bool, json_flag: bool,
) -> None:
    """List and manage messages via the server inbox API."""
    # Ack mode: no swarm_id required
    if ack:
        try:
            base_url = _load_base_url()
        except ConfigError as e:
            format_error(console, str(e), hint="Run 'swarm init' first")
            raise typer.Exit(code=1)

        data = _run_async(_ack_message_api(base_url, ack), "ack message")
        if json_flag:
            json_output(console, data)
        elif data["status"] == "acked":
            format_success(console, f"Message {ack[:12]}... marked as completed")
        else:
            format_error(console, f"Message {ack} not found")
            raise typer.Exit(code=5)
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
            console.print(f"[cyan]Pending messages:[/cyan] {data['pending']}")
        return

    # List mode
    data = _run_async(_fetch_messages(base_url, sid, limit, status_filter), "list messages")
    msgs = data.get("messages", [])

    if json_flag:
        json_output(console, {"swarm_id": sid, "count": len(msgs), "messages": msgs})
        return
    if not msgs:
        console.print("[yellow]No messages found[/yellow]")
        return
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
        console,
        f"Messages ({len(msgs)})",
        ["ID", "Sender", "Status", "Received", "Content"],
        rows,
    )


def _truncate(text: str, length: int) -> str:
    return text[:length] + "..." if len(text) > length else text
