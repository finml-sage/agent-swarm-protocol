"""Input validation utilities for CLI commands."""

import re
from uuid import UUID


def validate_agent_id(agent_id: str) -> str:
    """Validate and return agent ID. Raises ValueError if invalid."""
    if not agent_id or not agent_id.strip():
        raise ValueError("Agent ID cannot be empty")
    agent_id = agent_id.strip()
    if len(agent_id) > 256:
        raise ValueError("Agent ID cannot exceed 256 characters")
    if not re.match(r"^[a-zA-Z0-9_.-]+$", agent_id):
        raise ValueError(
            "Agent ID can only contain letters, numbers, underscores, dots, and hyphens"
        )
    return agent_id


def validate_endpoint(endpoint: str) -> str:
    """Validate and return endpoint URL. Raises ValueError if invalid."""
    if not endpoint or not endpoint.strip():
        raise ValueError("Endpoint cannot be empty")
    endpoint = endpoint.strip()
    if not endpoint.startswith("https://"):
        raise ValueError("Endpoint must use HTTPS (start with https://)")
    if len(endpoint) > 2048:
        raise ValueError("Endpoint URL cannot exceed 2048 characters")
    return endpoint


def validate_swarm_id(swarm_id: str) -> UUID:
    """Validate and return swarm ID as UUID. Raises ValueError if invalid."""
    if not swarm_id or not swarm_id.strip():
        raise ValueError("Swarm ID cannot be empty")
    try:
        return UUID(swarm_id.strip())
    except ValueError as e:
        raise ValueError(f"Swarm ID must be a valid UUID: {e}") from e


def validate_swarm_name(name: str) -> str:
    """Validate and return swarm name. Raises ValueError if invalid."""
    if not name or not name.strip():
        raise ValueError("Swarm name cannot be empty")
    name = name.strip()
    if len(name) > 256:
        raise ValueError("Swarm name cannot exceed 256 characters")
    return name


def validate_message_content(content: str) -> str:
    """Validate and return message content. Raises ValueError if invalid."""
    if not content:
        raise ValueError("Message content cannot be empty")
    if len(content) > 65536:
        raise ValueError("Message content cannot exceed 65536 characters")
    return content
