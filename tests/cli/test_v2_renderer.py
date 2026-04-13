"""Tests for TOON-based message renderer.

Covers:
- TOON messages render as pass-through (already TOON)
- Legacy JSON messages convert to TOON on display
- Special characters in content (quotes, newlines, unicode)
- Empty content
- Messages with nested body sections
- Batch rendering
"""

import json

import toon

from src.cli.output.v2_renderer import render_batch, render_message


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SWARM_ID = "716a4150-ab9d-4b54-a2a8-f2b7c607c21e"
MSG_ID = "abc12345-dead-beef-cafe-000000000001"


def _toon_message(**overrides: object) -> str:
    """Return a TOON-encoded message string."""
    msg: dict[str, object] = {
        "protocol_version": "0.1.0",
        "message_id": MSG_ID,
        "timestamp": "2026-04-13T14:30:00.000Z",
        "sender": {
            "agent_id": "finml-sage",
            "endpoint": "https://sage.marbell.com/swarm",
        },
        "recipient": "nexus-marbell",
        "swarm_id": SWARM_ID,
        "type": "message",
        "content": "Hello from test",
        "signature": "Rk9PQkFSbase64sig==",
    }
    msg.update(overrides)
    return toon.encode(msg)


def _json_message(**overrides: object) -> str:
    """Return a JSON-encoded wire envelope (legacy format)."""
    envelope: dict[str, object] = {
        "protocol_version": "0.1.0",
        "message_id": MSG_ID,
        "timestamp": "2026-04-13T14:30:00.000Z",
        "sender": {
            "agent_id": "finml-sage",
            "endpoint": "https://sage.marbell.com/swarm",
        },
        "recipient": "nexus-marbell",
        "swarm_id": SWARM_ID,
        "type": "message",
        "content": "Hello from test",
        "signature": "Rk9PQkFSbase64sig==",
    }
    envelope.update(overrides)
    return json.dumps(envelope)


# ---------------------------------------------------------------------------
# render_message — TOON pass-through
# ---------------------------------------------------------------------------


class TestRenderMessageToon:
    """TOON content passes through without transformation."""

    def test_toon_passes_through(self):
        toon_str = _toon_message()
        result = render_message(toon_str)
        assert result == toon_str

    def test_toon_preserves_all_fields(self):
        toon_str = _toon_message()
        result = render_message(toon_str)
        assert "finml-sage" in result
        assert "nexus-marbell" in result
        assert SWARM_ID in result
        assert "Hello from test" in result

    def test_simple_toon_object(self):
        content = toon.encode({"name": "Alice", "status": "active"})
        result = render_message(content)
        assert result == content
        assert "name: Alice" in result
        assert "status: active" in result


# ---------------------------------------------------------------------------
# render_message — legacy JSON conversion
# ---------------------------------------------------------------------------


class TestRenderMessageLegacyJson:
    """Legacy JSON messages (starting with '{') convert to TOON."""

    def test_json_converts_to_toon(self):
        json_str = _json_message()
        result = render_message(json_str)
        # Result should NOT start with { (it's TOON now)
        assert not result.startswith("{")
        # Should contain the fields in TOON format
        assert "finml-sage" in result
        assert "nexus-marbell" in result
        assert "Hello from test" in result

    def test_json_round_trips_correctly(self):
        original = {"from": "sage", "to": "nexus", "content": "test"}
        json_str = json.dumps(original)
        result = render_message(json_str)
        decoded = toon.decode(result)
        assert decoded == original

    def test_malformed_json_returns_raw(self):
        raw = "{broken json content"
        result = render_message(raw)
        assert result == raw

    def test_json_array_returns_raw(self):
        """A JSON array starting with '[' is not legacy JSON envelope."""
        raw = "[1, 2, 3]"
        result = render_message(raw)
        # Not starting with '{', so treated as already-TOON
        assert result == raw


# ---------------------------------------------------------------------------
# render_message — empty and edge cases
# ---------------------------------------------------------------------------


class TestRenderMessageEdgeCases:
    """Edge cases for render_message."""

    def test_empty_string(self):
        assert render_message("") == ""

    def test_none_like_empty(self):
        """Empty string produces empty output."""
        result = render_message("")
        assert result == ""

    def test_plain_text(self):
        """Plain text that is not JSON passes through."""
        result = render_message("just some plain text")
        assert result == "just some plain text"


# ---------------------------------------------------------------------------
# render_message — special characters
# ---------------------------------------------------------------------------


class TestRenderMessageSpecialChars:
    """Special characters survive TOON encoding."""

    def test_quotes_in_content(self):
        toon_str = _toon_message(content='He said "hello"')
        result = render_message(toon_str)
        decoded = toon.decode(result)
        assert decoded["content"] == 'He said "hello"'

    def test_newlines_in_json_content(self):
        json_str = _json_message(content="line1\nline2\nline3")
        result = render_message(json_str)
        assert not result.startswith("{")
        decoded = toon.decode(result)
        assert decoded["content"] == "line1\nline2\nline3"

    def test_unicode_in_content(self):
        toon_str = _toon_message(content="Unicode: \u00e9\u00e8\u00ea \u2603")
        result = render_message(toon_str)
        assert "\u00e9\u00e8\u00ea" in result
        assert "\u2603" in result

    def test_backslashes_in_json_content(self):
        json_str = _json_message(content="path\\to\\file")
        result = render_message(json_str)
        decoded = toon.decode(result)
        assert decoded["content"] == "path\\to\\file"


# ---------------------------------------------------------------------------
# render_message — nested body sections
# ---------------------------------------------------------------------------


class TestRenderMessageNestedSections:
    """Messages with nested structures render correctly in TOON."""

    def test_nested_sender_object(self):
        toon_str = _toon_message()
        result = render_message(toon_str)
        decoded = toon.decode(result)
        assert decoded["sender"]["agent_id"] == "finml-sage"
        assert decoded["sender"]["endpoint"] == "https://sage.marbell.com/swarm"

    def test_json_with_nested_converts(self):
        json_str = _json_message()
        result = render_message(json_str)
        decoded = toon.decode(result)
        assert isinstance(decoded["sender"], dict)
        assert decoded["sender"]["agent_id"] == "finml-sage"


# ---------------------------------------------------------------------------
# render_batch
# ---------------------------------------------------------------------------


class TestRenderBatch:
    """Tests for batch rendering of multiple messages."""

    def test_batch_separates_with_blank_line(self):
        msgs = [
            {"content_preview": _toon_message()},
            {"content_preview": _toon_message(message_id="msg-2")},
        ]
        result = render_batch(msgs)
        blocks = result.split("\n\n")
        assert len(blocks) == 2

    def test_batch_single_message(self):
        msgs = [{"content_preview": _toon_message()}]
        result = render_batch(msgs)
        assert "finml-sage" in result

    def test_batch_empty_list(self):
        result = render_batch([])
        assert result == ""

    def test_batch_mixed_toon_and_json(self):
        """Batch handles mix of TOON and legacy JSON messages."""
        msgs = [
            {"content_preview": _toon_message()},
            {"content_preview": _json_message(content="legacy message")},
        ]
        result = render_batch(msgs)
        blocks = result.split("\n\n")
        assert len(blocks) == 2
        # First block is TOON pass-through
        assert not blocks[0].startswith("{")
        # Second block was JSON, now converted to TOON
        assert not blocks[1].startswith("{")
        assert "legacy message" in blocks[1]

    def test_batch_missing_content_preview(self):
        """Message without content_preview renders as empty."""
        msgs = [{"message_id": "no-preview"}]
        result = render_batch(msgs)
        assert result == ""
