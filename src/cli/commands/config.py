"""Show resolved configuration including swarm ID fallback chain."""

import asyncio
import os

import typer
from rich.console import Console

from src.cli.output import format_error, json_output
from src.cli.utils.config import ConfigError, ConfigManager
from src.cli.utils.resolve import (
    SwarmIdError,
    _auto_detect_single_swarm,
    _read_default_swarm_from_config,
)

console = Console()


def _resolve_swarm_with_source() -> tuple[str | None, str]:
    """Resolve swarm ID and report which fallback was used.

    Returns:
        Tuple of (swarm_id_or_none, source_description).
    """
    env_value = os.environ.get("SWARM_ID")
    if env_value:
        return env_value, "SWARM_ID environment variable"

    config_value = _read_default_swarm_from_config()
    if config_value:
        return config_value, "default_swarm in ~/.swarm/config.yaml"

    auto_value = asyncio.run(_auto_detect_single_swarm())
    if auto_value:
        return auto_value, "auto-detected (single swarm in DB)"

    return None, "not resolved"


def config_command(
    json_flag: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Display resolved agent configuration."""
    config = ConfigManager()
    try:
        agent_config = config.load()
    except ConfigError as e:
        format_error(console, str(e), hint="Run 'swarm init' to configure your agent")
        raise typer.Exit(code=1)

    config_value = _read_default_swarm_from_config()
    swarm_id, source = _resolve_swarm_with_source()

    data = {
        "agent_id": agent_config.agent_id,
        "endpoint": agent_config.endpoint,
        "config_path": str(config.config_path),
        "db_path": str(agent_config.db_path),
        "default_swarm": config_value,
        "resolved_swarm_id": swarm_id,
        "resolved_via": source,
    }

    if json_flag:
        json_output(console, data)
        return

    console.print("[bold]Agent Configuration[/bold]")
    console.print()
    console.print(f"[cyan]Agent ID:[/cyan]         {data['agent_id']}")
    console.print(f"[cyan]Endpoint:[/cyan]         {data['endpoint']}")
    console.print(f"[cyan]Config:[/cyan]           {data['config_path']}")
    console.print(f"[cyan]Database:[/cyan]         {data['db_path']}")
    console.print()
    console.print("[bold]Swarm ID Resolution[/bold]")
    console.print()
    default = data["default_swarm"] or "[dim]not set[/dim]"
    console.print(f"[cyan]default_swarm:[/cyan]    {default}")
    env = os.environ.get("SWARM_ID") or "[dim]not set[/dim]"
    console.print(f"[cyan]SWARM_ID env:[/cyan]     {env}")
    if swarm_id:
        console.print(f"[cyan]Resolved ID:[/cyan]      {swarm_id}")
        console.print(f"[cyan]Resolved via:[/cyan]     {source}")
    else:
        console.print(
            "[yellow]No swarm ID resolved.[/yellow] "
            "Set default_swarm in config.yaml, SWARM_ID env var, or pass -s <id>"
        )
