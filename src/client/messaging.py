"""Message sending functions for the client."""

from .exceptions import NotMemberError, TransportError
from .transport import Transport
from .types import SwarmMembership


async def broadcast_message(transport: Transport, swarm: SwarmMembership, sender_id: str, wire: dict) -> None:
    """Broadcast message to all swarm members except sender."""
    errors: list[tuple[str, Exception]] = []
    others = [m for m in swarm["members"] if m["agent_id"] != sender_id]
    for m in others:
        try:
            status, _ = await transport.post(f"{m['endpoint'].rstrip('/')}/swarm/message", wire, retry=True)
            if status not in (200, 202):
                errors.append((m["agent_id"], TransportError(f"Status {status}")))
        except Exception as e:
            errors.append((m["agent_id"], e))
    if errors and len(errors) == len(others):
        raise TransportError(f"Failed to send to any member: {errors[0][1]}")


async def send_to_recipient(transport: Transport, swarm: SwarmMembership, recipient: str, wire: dict) -> None:
    """Send message to specific recipient."""
    target = next((m for m in swarm["members"] if m["agent_id"] == recipient), None)
    if not target:
        raise NotMemberError(f"Recipient {recipient} not in swarm")
    status, resp = await transport.post(f"{target['endpoint'].rstrip('/')}/swarm/message", wire, retry=True)
    if status not in (200, 202):
        msg = resp.get("error", {}).get("message", str(resp)) if resp else "Unknown"
        raise TransportError(f"Send failed: {msg}", status)
