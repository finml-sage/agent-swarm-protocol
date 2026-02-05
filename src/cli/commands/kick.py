"""Kick a member from a swarm (master only)."""

import asyncio
from uuid import UUID

import typer
from rich.console import Console
from rich.prompt import Confirm

from src.cli.output import format_error, format_success, format_warning, json_output
from src.cli.utils import ConfigManager, validate_agent_id, validate_swarm_id
from src.cli.utils.config import ConfigError
from src.client import NotMasterError, SwarmClient
from src.state import DatabaseManager, MembershipRepository

console = Console()


async def _kick_member(swarm_id: UUID, target_agent: str, reason: str | None) -> None:
    """Kick member from swarm and update local database."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with db.connection() as conn:
        repo = MembershipRepository(conn)
        membership = await repo.get_swarm(str(swarm_id))

        if not membership:
            raise ValueError(f"Not a member of swarm {swarm_id}")

        if membership.master != agent_config.agent_id:
            raise NotMasterError("Only the swarm master can kick members")

        target_in_swarm = any(m.agent_id == target_agent for m in membership.members)
        if not target_in_swarm:
            raise ValueError(f"Agent {target_agent} is not a member of this swarm")

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
        await client.kick_member(swarm_id, target_agent, reason)

    async with db.connection() as conn:
        repo = MembershipRepository(conn)
        await repo.remove_member(str(swarm_id), target_agent)


def kick_command(
    swarm_id: str = typer.Option(..., "--swarm", "-s", help="Swarm ID"),
    agent_id: str = typer.Option(..., "--agent", "-a", help="Agent ID to kick"),
    reason: str = typer.Option(None, "--reason", "-r", help="Reason for kicking"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Remove a member from a swarm. Only the swarm master can kick members."""
    try:
        swarm_uuid = validate_swarm_id(swarm_id)
        target_agent = validate_agent_id(agent_id)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)

    if not yes and not json_flag:
        if not Confirm.ask(f"Kick agent '{target_agent}' from swarm?"):
            format_warning(console, "Operation cancelled")
            raise typer.Exit(code=0)

    try:
        asyncio.run(_kick_member(swarm_uuid, target_agent, reason))
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)
    except NotMasterError as e:
        format_error(console, str(e))
        raise typer.Exit(code=4)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=5)
    except Exception as e:
        format_error(console, f"Failed to kick member: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(
            console,
            {"status": "kicked", "swarm_id": str(swarm_uuid), "agent_id": target_agent},
        )
    else:
        format_success(console, f"Kicked '{target_agent}' from swarm")
