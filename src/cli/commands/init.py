"""Initialize agent for swarm participation."""

import typer
from rich.console import Console

from src.cli.output import format_error, format_success, json_output
from src.cli.utils import ConfigManager, validate_agent_id, validate_endpoint
from src.client import generate_keypair, public_key_to_base64

console = Console()


def init_command(
    agent_id: str = typer.Option(
        ..., "--agent-id", "-a", help="Unique identifier for this agent"
    ),
    endpoint: str = typer.Option(
        ..., "--endpoint", "-e", help="HTTPS endpoint for receiving messages"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing configuration"
    ),
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Initialize agent configuration and generate Ed25519 keypair.

    Creates ~/.swarm/config.yaml with agent settings and ~/.swarm/agent.key
    with the private key. The private key file is chmod 600.
    """
    try:
        agent_id = validate_agent_id(agent_id)
        endpoint = validate_endpoint(endpoint)
    except ValueError as e:
        format_error(console, str(e))
        raise typer.Exit(code=2)

    config = ConfigManager()

    if config.exists() and not force:
        format_error(
            console,
            f"Configuration already exists at {config.config_path}",
            hint="Use --force to overwrite existing configuration",
        )
        raise typer.Exit(code=1)

    private_key, public_key = generate_keypair()
    config.save(agent_id, endpoint, private_key)

    public_key_b64 = public_key_to_base64(public_key)

    if json_flag:
        json_output(
            console,
            {
                "status": "initialized",
                "agent_id": agent_id,
                "endpoint": endpoint,
                "public_key": public_key_b64,
                "config_path": str(config.config_path),
            },
        )
    else:
        format_success(console, "Agent initialized successfully")
        console.print(f"[cyan]Agent ID:[/cyan]    {agent_id}")
        console.print(f"[cyan]Endpoint:[/cyan]    {endpoint}")
        console.print(f"[cyan]Public Key:[/cyan]  {public_key_b64}")
        console.print(f"[cyan]Config:[/cyan]      {config.config_path}")
