"""Create a new swarm."""

import asyncio
from datetime import datetime

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, json_output
from src.cli.utils import ConfigManager
from src.cli.utils.config import ConfigError
from src.cli.utils.validation import validate_swarm_name
from src.client import SwarmClient
from src.state import DatabaseManager
from src.state.models import SwarmMember, SwarmMembership, SwarmSettings

console = Console()


async def _create_swarm(
    name: str, allow_member_invite: bool, require_approval: bool
) -> SwarmMembership:
    """Create swarm and persist to database."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with SwarmClient(
        agent_id=agent_config.agent_id,
        endpoint=agent_config.endpoint,
        private_key=agent_config.private_key,
        db=db,
    ) as client:
        membership_dict = await client.create_swarm(
            name=name,
            allow_member_invite=allow_member_invite,
            require_approval=require_approval,
        )

        membership = SwarmMembership(
            swarm_id=membership_dict["swarm_id"],
            name=membership_dict["name"],
            master=membership_dict["master"],
            members=tuple(
                SwarmMember(
                    agent_id=m["agent_id"],
                    endpoint=m["endpoint"],
                    public_key=m["public_key"],
                    joined_at=datetime.fromisoformat(m["joined_at"]),
                )
                for m in membership_dict["members"]
            ),
            joined_at=datetime.fromisoformat(membership_dict["joined_at"]),
            settings=SwarmSettings(
                allow_member_invite=membership_dict["settings"]["allow_member_invite"],
                require_approval=membership_dict["settings"]["require_approval"],
            ),
        )

        return membership


def create_command(
    name: str = typer.Option(..., "--name", "-n", help="Name for the new swarm"),
    allow_member_invite: bool = typer.Option(
        False, "--allow-member-invite", help="Allow non-masters to generate invites"
    ),
    require_approval: bool = typer.Option(
        False, "--require-approval", help="Require master approval for new members"
    ),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Create a new swarm with this agent as master."""
    try:
        name = validate_swarm_name(name)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)

    try:
        membership = asyncio.run(
            _create_swarm(name, allow_member_invite, require_approval)
        )
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)
    except Exception as e:
        format_error(console, f"Failed to create swarm: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(
            console,
            {
                "status": "created",
                "swarm_id": membership.swarm_id,
                "name": membership.name,
                "master": membership.master,
            },
        )
    else:
        format_success(console, f"Swarm '{name}' created successfully")
        console.print(f"[cyan]Swarm ID:[/cyan] {membership.swarm_id}")
        console.print(f"[cyan]Master:[/cyan]   {membership.master}")
