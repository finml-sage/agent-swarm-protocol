"""Send a message to a swarm."""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from uuid import UUID

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, json_output
from src.cli.utils import ConfigManager, resolve_swarm_id, SwarmIdError
from src.cli.utils.config import ConfigError
from src.cli.utils.validation import validate_message_content
from src.client import Message, SwarmClient
from src.state import DatabaseManager, MembershipRepository, OutboxMessage, OutboxRepository

logger = logging.getLogger(__name__)
console = Console()


async def _send_message(swarm_id: UUID, content: str, recipient: str | None) -> Message:
    """Send message and return the sent message."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = MembershipRepository(conn)
        membership = await repo.get_swarm(str(swarm_id))

        if not membership:
            raise ValueError(f"Not a member of swarm {swarm_id}")

        membership_dict = {
            "swarm_id": membership.swarm_id,
            "name": membership.name,
            "master": membership.master,
            "members": [
                {
                    "agent_id": m.agent_id,
                    "endpoint": m.endpoint,
                    "public_key": m.public_key,
                    "joined_at": m.joined_at.isoformat(),
                }
                for m in membership.members
            ],
            "joined_at": membership.joined_at.isoformat(),
            "settings": {
                "allow_member_invite": membership.settings.allow_member_invite,
                "require_approval": membership.settings.require_approval,
            },
        }

    async with SwarmClient(
        agent_id=agent_config.agent_id,
        endpoint=agent_config.endpoint,
        private_key=agent_config.private_key,
    ) as client:
        client.add_swarm(membership_dict)
        target = recipient or "broadcast"
        msg = await client.send_message(swarm_id, content, recipient=target)

    try:
        outbox_msg = OutboxMessage(
            message_id=str(msg.message_id),
            swarm_id=str(swarm_id),
            recipient_id=target,
            message_type="message",
            content=content,
            sent_at=datetime.now(timezone.utc),
        )
        async with db.connection() as conn:
            outbox_repo = OutboxRepository(conn)
            await outbox_repo.insert(outbox_msg)
    except Exception:
        logger.warning("Failed to persist sent message to outbox", exc_info=True)

    return msg


def send_command(
    swarm_id: str | None,
    message: str | None,
    to: str | None,
    json_flag: bool,
) -> None:
    """Send a message to a swarm or specific member."""
    # Resolve swarm ID via fallback chain
    try:
        swarm_uuid = resolve_swarm_id(swarm_id)
    except SwarmIdError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)

    # Resolve message content: flag or stdin
    if not message and not sys.stdin.isatty():
        message = sys.stdin.read().strip()

    if not message:
        format_error(
            console,
            "Message content required",
            hint="Use -m/--message/--body 'text' or pipe via stdin",
        )
        raise typer.Exit(code=2)

    try:
        content = validate_message_content(message)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)

    try:
        msg = asyncio.run(_send_message(swarm_uuid, content, to))
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=5)
    except Exception as e:
        format_error(console, f"Failed to send message: {e}")
        raise typer.Exit(code=3)

    if json_flag:
        json_output(
            console,
            {
                "status": "sent",
                "message_id": str(msg.message_id),
                "swarm_id": str(msg.swarm_id),
                "recipient": msg.recipient,
            },
        )
    else:
        target = to or "all members"
        format_success(console, f"Message sent to {target}")
        console.print(f"[cyan]Message ID:[/cyan] {msg.message_id}")
