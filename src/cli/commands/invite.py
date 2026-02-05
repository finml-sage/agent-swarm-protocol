"""Generate an invite token for a swarm."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, json_output
from src.cli.utils import ConfigManager, validate_swarm_id
from src.cli.utils.config import ConfigError
from src.client import SwarmClient
from src.state import DatabaseManager, MembershipRepository

console = Console()


async def _generate_invite(
    swarm_id: UUID, expires_hours: int | None, max_uses: int | None
) -> str:
    """Generate invite token from stored swarm membership."""
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
        expires_at = None
        if expires_hours:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
        return client.generate_invite(
            swarm_id, expires_at=expires_at, max_uses=max_uses
        )


def invite_command(
    swarm_id: str = typer.Option(..., "--swarm", "-s", help="Swarm ID to invite to"),
    expires_hours: int = typer.Option(
        None, "--expires", "-e", help="Hours until invite expires (default: never)"
    ),
    max_uses: int = typer.Option(
        None, "--max-uses", "-m", help="Maximum number of times invite can be used"
    ),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Generate an invite token for others to join the swarm."""
    try:
        swarm_uuid = validate_swarm_id(swarm_id)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)

    try:
        token = asyncio.run(_generate_invite(swarm_uuid, expires_hours, max_uses))
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=5)
    except Exception as e:
        format_error(console, f"Failed to generate invite: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(console, {"status": "success", "invite_token": token})
    else:
        format_success(console, "Invite token generated")
        console.print(f"\n[cyan]Token:[/cyan] {token}")
        console.print("\n[dim]Share this token with agents who want to join.[/dim]")
