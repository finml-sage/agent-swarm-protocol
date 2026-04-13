"""Render stored messages in TOON format.

New messages are stored as TOON.  Legacy messages stored as JSON
(content starting with ``{``) are converted to TOON on the fly.
"""

import json
from typing import Any

import toon


def render_message(content_str: str) -> str:
    """Render a stored message.  Content is TOON (or legacy JSON).

    Args:
        content_str: The raw ``content`` / ``content_preview`` string
            from the inbox or outbox store.

    Returns:
        A TOON-formatted string ready for display.
    """
    if not content_str:
        return ""

    if content_str.startswith("{"):
        # Legacy JSON message -- convert to TOON, strip null fields
        try:
            msg_dict = json.loads(content_str)
            msg_dict = {k: v for k, v in msg_dict.items() if v is not None}
            return toon.encode(msg_dict)
        except (json.JSONDecodeError, TypeError):
            return content_str

    # Already TOON -- return directly
    return content_str


def render_batch(messages: list[dict[str, Any]]) -> str:
    """Render multiple inbox messages separated by blank lines.

    Each message dict must contain a ``content_preview`` key whose value
    is either TOON or legacy JSON.  The rendered TOON is printed as-is.

    Args:
        messages: List of message dicts from the ``/api/inbox`` response.

    Returns:
        Multi-line string with all messages, separated by blank lines.
    """
    blocks = [render_message(m.get("content_preview", "")) for m in messages]
    return "\n\n".join(blocks)
