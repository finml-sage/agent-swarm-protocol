"""Join a swarm using an invite token."""

import asyncio
from datetime import datetime

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, json_output
from src.cli.utils import ConfigManager
from src.cli.utils.config import ConfigError
from src.client import SwarmClient, TokenError
from src.state import DatabaseManager, MembershipRepository
from src.state.models import SwarmMember, SwarmMembership, SwarmSettings

console = Console()


async def _join_swarm(invite_token: str) -> SwarmMembership:
    """Join swarm using invite token and persist membership."""
    config = ConfigManager()
    agent_config = config.load()

    db = DatabaseManager(agent_config.db_path)
    await db.initialize()

    async with SwarmClient(
        agent_id=agent_config.agent_id,
        endpoint=agent_config.endpoint,
        private_key=agent_config.private_key,
    ) as client:
        membership_dict = await client.join_swarm(invite_token)

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

        async with db.connection() as conn:
            repo = MembershipRepository(conn)
            await repo.create_swarm(membership)

        return membership


def join_command(
    token: str = typer.Option(..., "--token", "-t", help="Invite token URL"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Join a swarm using an invite token provided by the swarm master."""
    if not token or not token.strip():
        format_error(console, "Invite token cannot be empty")
        raise typer.Exit(code=2)

    try:
        membership = asyncio.run(_join_swarm(token.strip()))
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)
    except TokenError as e:
        format_error(
            console, f"Invalid invite token: {e}", hint="Check token is not expired"
        )
        raise typer.Exit(code=4)
    except Exception as e:
        format_error(console, f"Failed to join swarm: {e}")
        raise typer.Exit(code=1)

    if json_flag:
        json_output(
            console,
            {
                "status": "joined",
                "swarm_id": membership.swarm_id,
                "name": membership.name,
                "master": membership.master,
                "member_count": len(membership.members),
            },
        )
    else:
        format_success(console, f"Joined swarm '{membership.name}'")
        console.print(f"[cyan]Swarm ID:[/cyan] {membership.swarm_id}")
        console.print(f"[cyan]Master:[/cyan]   {membership.master}")
        console.print(f"[cyan]Members:[/cyan]  {len(membership.members)}")
