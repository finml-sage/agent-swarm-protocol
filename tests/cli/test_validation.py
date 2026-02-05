"""Tests for CLI validation utilities."""

import pytest
from uuid import UUID

from src.cli.utils.validation import (
    validate_agent_id,
    validate_endpoint,
    validate_message_content,
    validate_swarm_id,
    validate_swarm_name,
)


class TestValidateAgentId:
    """Tests for agent ID validation."""

    def test_valid_agent_id(self):
        """Valid agent IDs are returned unchanged."""
        assert validate_agent_id("my-agent") == "my-agent"
        assert validate_agent_id("agent_123") == "agent_123"
        assert validate_agent_id("Agent.Test") == "Agent.Test"

    def test_strips_whitespace(self):
        """Whitespace is stripped from agent ID."""
        assert validate_agent_id("  my-agent  ") == "my-agent"

    def test_empty_raises(self):
        """Empty agent ID raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_agent_id("")

    def test_whitespace_only_raises(self):
        """Whitespace-only agent ID raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_agent_id("   ")

    def test_too_long_raises(self):
        """Agent ID over 256 chars raises ValueError."""
        with pytest.raises(ValueError, match="exceed 256"):
            validate_agent_id("a" * 257)

    def test_invalid_chars_raises(self):
        """Agent ID with invalid characters raises ValueError."""
        with pytest.raises(ValueError, match="letters, numbers"):
            validate_agent_id("agent@test")
        with pytest.raises(ValueError, match="letters, numbers"):
            validate_agent_id("agent test")


class TestValidateEndpoint:
    """Tests for endpoint URL validation."""

    def test_valid_https_endpoint(self):
        """Valid HTTPS endpoints are returned unchanged."""
        assert validate_endpoint("https://example.com") == "https://example.com"
        assert (
            validate_endpoint("https://agent.example.com/swarm")
            == "https://agent.example.com/swarm"
        )

    def test_strips_whitespace(self):
        """Whitespace is stripped from endpoint."""
        assert validate_endpoint("  https://example.com  ") == "https://example.com"

    def test_empty_raises(self):
        """Empty endpoint raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_endpoint("")

    def test_http_raises(self):
        """HTTP endpoints raise ValueError (HTTPS required)."""
        with pytest.raises(ValueError, match="HTTPS"):
            validate_endpoint("http://example.com")

    def test_no_scheme_raises(self):
        """Endpoints without scheme raise ValueError."""
        with pytest.raises(ValueError, match="HTTPS"):
            validate_endpoint("example.com")


class TestValidateSwarmId:
    """Tests for swarm ID validation."""

    def test_valid_uuid(self):
        """Valid UUID strings return UUID object."""
        uuid_str = "0957dfc3-6db6-47aa-b8b5-54f4c9acbdc5"
        result = validate_swarm_id(uuid_str)
        assert isinstance(result, UUID)
        assert str(result) == uuid_str

    def test_strips_whitespace(self):
        """Whitespace is stripped before validation."""
        uuid_str = "  0957dfc3-6db6-47aa-b8b5-54f4c9acbdc5  "
        result = validate_swarm_id(uuid_str)
        assert str(result) == "0957dfc3-6db6-47aa-b8b5-54f4c9acbdc5"

    def test_empty_raises(self):
        """Empty swarm ID raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_swarm_id("")

    def test_invalid_uuid_raises(self):
        """Invalid UUID strings raise ValueError."""
        with pytest.raises(ValueError, match="valid UUID"):
            validate_swarm_id("not-a-uuid")


class TestValidateSwarmName:
    """Tests for swarm name validation."""

    def test_valid_name(self):
        """Valid names are returned unchanged."""
        assert validate_swarm_name("My Swarm") == "My Swarm"
        assert validate_swarm_name("Test-Swarm-123") == "Test-Swarm-123"

    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        assert validate_swarm_name("  My Swarm  ") == "My Swarm"

    def test_empty_raises(self):
        """Empty name raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_swarm_name("")

    def test_too_long_raises(self):
        """Name over 256 chars raises ValueError."""
        with pytest.raises(ValueError, match="exceed 256"):
            validate_swarm_name("a" * 257)


class TestValidateMessageContent:
    """Tests for message content validation."""

    def test_valid_content(self):
        """Valid content is returned unchanged."""
        assert validate_message_content("Hello, world!") == "Hello, world!"

    def test_empty_raises(self):
        """Empty content raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_message_content("")

    def test_too_long_raises(self):
        """Content over 65536 chars raises ValueError."""
        with pytest.raises(ValueError, match="exceed 65536"):
            validate_message_content("a" * 65537)
