"""Leave a swarm."""

import asyncio
from uuid import UUID

import typer
from rich.console import Console
from rich.prompt import Confirm

from src.cli.output import format_error, format_success, format_warning, json_output
from src.cli.utils import ConfigManager, validate_swarm_id
from src.cli.utils.config import ConfigError
from src.client import SwarmClient
from src.state import DatabaseManager, MembershipRepository

console = Console()


async def _leave_swarm(swarm_id: UUID) -> str:
    """Leave swarm and remove from local database. Returns swarm name."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = MembershipRepository(conn)
        membership = await repo.get_swarm(str(swarm_id))

        if not membership:
            raise ValueError(f"Not a member of swarm {swarm_id}")

        swarm_name = membership.name

        if membership.master == agent_config.agent_id:
            raise ValueError(
                "Cannot leave swarm as master. Transfer ownership or dissolve swarm."
            )

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
        await client.leave_swarm(swarm_id)

    async with db.connection() as conn:
        repo = MembershipRepository(conn)
        await repo.delete_swarm(str(swarm_id))

    return swarm_name


def leave_command(
    swarm_id: str = typer.Option(..., "--swarm", "-s", help="Swarm ID to leave"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Leave a swarm. Notifies other members before departure."""
    try:
        swarm_uuid = validate_swarm_id(swarm_id)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)

    if not yes and not json_flag:
        if not Confirm.ask(f"Leave swarm {swarm_uuid}?"):
            format_warning(console, "Operation cancelled")
            raise typer.Exit(code=0)

    try:
        swarm_name = asyncio.run(_leave_swarm(swarm_uuid))
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=5)
    except Exception as e:
        format_error(console, f"Failed to leave swarm: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(
            console,
            {"status": "left", "swarm_id": str(swarm_uuid), "name": swarm_name},
        )
    else:
        format_success(console, f"Left swarm '{swarm_name}'")
