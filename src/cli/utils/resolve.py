"""Swarm ID resolution with fallback chain.

Resolution order:
1. Explicit CLI flag (-s / --swarm)
2. SWARM_ID environment variable
3. default_swarm in ~/.swarm/config.yaml
4. Auto-detect single swarm from local DB
5. Error with helpful message
"""

import asyncio
import os
from pathlib import Path
from uuid import UUID

import yaml

from src.cli.utils.config import ConfigManager, ConfigError
from src.cli.utils.validation import validate_swarm_id
from src.state import DatabaseManager, MembershipRepository


class SwarmIdError(Exception):
    """Raised when swarm ID cannot be resolved."""


def _read_default_swarm_from_config() -> str | None:
    """Read default_swarm from ~/.swarm/config.yaml."""
    config_path = ConfigManager.DEFAULT_DIR / ConfigManager.CONFIG_FILE
    if not config_path.exists():
        return None
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict):
            return data.get("default_swarm")
    except Exception:
        return None
    return None


async def _auto_detect_single_swarm() -> str | None:
    """Query local DB for a single active swarm membership.

    Returns the swarm_id if exactly one swarm found, None otherwise.
    """
    config = ConfigManager()
    try:
        agent_config = config.load()
    except ConfigError:
        return None

    db_path = agent_config.db_path
    if not Path(db_path).exists():
        return None

    try:
        db = DatabaseManager(db_path)
        await db.initialize()
        async with db.connection() as conn:
            repo = MembershipRepository(conn)
            swarms = await repo.get_all_swarms()
        if len(swarms) == 1:
            return swarms[0].swarm_id
    except Exception:
        return None
    return None


def resolve_swarm_id(cli_value: str | None) -> UUID:
    """Resolve swarm ID from CLI flag, env var, config, or auto-detect.

    Args:
        cli_value: The value passed via -s/--swarm, or None if not provided.

    Returns:
        Validated UUID of the resolved swarm.

    Raises:
        SwarmIdError: If no swarm ID can be resolved from any source.
        ValueError: If a found swarm ID is not a valid UUID.
    """
    # 1. CLI flag
    if cli_value:
        return validate_swarm_id(cli_value)

    # 2. Environment variable
    env_value = os.environ.get("SWARM_ID")
    if env_value:
        return validate_swarm_id(env_value)

    # 3. Config file default_swarm
    config_value = _read_default_swarm_from_config()
    if config_value:
        return validate_swarm_id(config_value)

    # 4. Auto-detect single swarm from DB
    auto_value = asyncio.run(_auto_detect_single_swarm())
    if auto_value:
        return validate_swarm_id(auto_value)

    # 5. Error with helpful message
    raise SwarmIdError(
        "No swarm ID. Set `default_swarm` in ~/.swarm/config.yaml, "
        "set SWARM_ID env var, or pass -s <id>"
    )
