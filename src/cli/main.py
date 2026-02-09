"""Main CLI entry point for Agent Swarm Protocol."""

import typer
from rich.console import Console

from src.cli.commands.create import create_command
from src.cli.commands.export_state import export_command
from src.cli.commands.import_state import import_command
from src.cli.commands.init import init_command
from src.cli.commands.invite import invite_command
from src.cli.commands.join import join_command
from src.cli.commands.kick import kick_command
from src.cli.commands.leave import leave_command
from src.cli.commands.list_swarms import list_command
from src.cli.commands.messages import messages_command
from src.cli.commands.mute import mute_command
from src.cli.commands.purge import purge_command
from src.cli.commands.send import send_command
from src.cli.commands.status import status_command
from src.cli.commands.unmute import unmute_command

app = typer.Typer(
    name="swarm",
    help="Agent Swarm Protocol - P2P communication for autonomous agents",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command("init")
def init(
    agent_id: str = typer.Option(..., "-a", "--agent-id", help="Agent identifier"),
    endpoint: str = typer.Option(..., "-e", "--endpoint", help="HTTPS endpoint"),
    force: bool = typer.Option(False, "-f", "--force", help="Overwrite config"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Initialize agent configuration and generate keypair."""
    init_command(agent_id, endpoint, force, json_flag)


@app.command("create")
def create(
    name: str = typer.Option(..., "-n", "--name", help="Swarm name"),
    allow_invite: bool = typer.Option(False, "--allow-member-invite"),
    require_approval: bool = typer.Option(False, "--require-approval"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Create a new swarm with this agent as master."""
    create_command(name, allow_invite, require_approval, json_flag)


@app.command("invite")
def invite(
    swarm_id: str = typer.Option(..., "-s", "--swarm", help="Swarm ID"),
    expires: int = typer.Option(None, "-e", "--expires", help="Hours until expiry"),
    max_uses: int = typer.Option(None, "-m", "--max-uses"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Generate an invite token for a swarm."""
    invite_command(swarm_id, expires, max_uses, json_flag)


@app.command("join")
def join(
    token: str = typer.Option(..., "-t", "--token", help="Invite token URL"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Join a swarm using an invite token."""
    join_command(token, json_flag)


@app.command("leave")
def leave(
    swarm_id: str = typer.Option(..., "-s", "--swarm", help="Swarm ID"),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Leave a swarm."""
    leave_command(swarm_id, yes, json_flag)


@app.command("kick")
def kick(
    swarm_id: str = typer.Option(..., "-s", "--swarm", help="Swarm ID"),
    agent_id: str = typer.Option(..., "-a", "--agent", help="Agent to kick"),
    reason: str = typer.Option(None, "-r", "--reason"),
    yes: bool = typer.Option(False, "-y", "--yes"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a member from a swarm (master only)."""
    kick_command(swarm_id, agent_id, reason, yes, json_flag)


@app.command("list")
def list_swarms(
    swarm_id: str = typer.Option(None, "-s", "--swarm", help="Filter by ID"),
    members: bool = typer.Option(False, "-m", "--members", help="Show members"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """List swarms this agent belongs to."""
    list_command(swarm_id, members, json_flag)


@app.command("purge")
def purge(
    messages: bool = typer.Option(False, "--messages", help="Purge old messages"),
    sessions: bool = typer.Option(False, "--sessions", help="Purge expired sessions"),
    retention_days: int = typer.Option(
        30, "--retention-days", help="Message retention (days)"
    ),
    timeout_minutes: int = typer.Option(
        60, "--timeout-minutes", help="Session timeout (minutes)"
    ),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Purge old messages and expired sessions."""
    purge_command(messages, sessions, retention_days, timeout_minutes, yes, json_flag)


@app.command("send")
def send(
    swarm_id: str = typer.Option(..., "-s", "--swarm", help="Swarm ID"),
    message: str = typer.Option(..., "-m", "--message", help="Content"),
    to: str = typer.Option(None, "-t", "--to", help="Recipient (default: all)"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Send a message to a swarm."""
    send_command(swarm_id, message, to, json_flag)


@app.command("messages")
def messages(
    swarm_id: str = typer.Option(None, "-s", "--swarm", help="Swarm ID"),
    limit: int = typer.Option(10, "-l", "--limit", help="Max messages to show"),
    show_all: bool = typer.Option(False, "--all", help="Show all statuses"),
    ack: str = typer.Option(None, "--ack", help="Mark message as completed"),
    count: bool = typer.Option(False, "--count", help="Show pending count only"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List and manage received messages."""
    messages_command(swarm_id, limit, show_all, ack, count, json_flag)


@app.command("mute")
def mute(
    agent_id: str = typer.Option(None, "-a", "--agent", help="Agent ID"),
    swarm_id: str = typer.Option(None, "-s", "--swarm", help="Swarm ID"),
    reason: str = typer.Option(None, "-r", "--reason"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Mute an agent or swarm."""
    mute_command(agent_id, swarm_id, reason, json_flag)


@app.command("unmute")
def unmute(
    agent_id: str = typer.Option(None, "-a", "--agent", help="Agent ID"),
    swarm_id: str = typer.Option(None, "-s", "--swarm", help="Swarm ID"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Unmute a previously muted agent or swarm."""
    unmute_command(agent_id, swarm_id, json_flag)


@app.command("status")
def status(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Details"),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Show agent configuration and status."""
    status_command(verbose, json_flag)


@app.command("export")
def export_state_cmd(
    output: str = typer.Option(None, "-o", "--output", help="Output file path"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Export agent state to JSON."""
    export_command(output, json_flag)


@app.command("import")
def import_state_cmd(
    input_path: str = typer.Option(..., "-i", "--input", help="JSON file to import"),
    merge: bool = typer.Option(False, "--merge", help="Merge with existing state"),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation"),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Import agent state from a JSON file."""
    import_command(input_path, merge, yes, json_flag)


def main() -> None:
    """Entry point."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
        raise typer.Exit(130)
