"""Tests for swarm messages command (HTTP-based, issue #151).

The messages command now queries the server REST API at /api/messages
instead of reading from the local client DB.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.cli.commands.messages import _server_base_url
from src.cli.utils.config import ConfigManager

runner = CliRunner()

SWARM_ID = "716a4150-ab9d-4b54-a2a8-f2b7c607c21e"
MSG_ID = "abc12345-dead-beef-cafe-000000000001"
BASE_URL = "https://example.com"


def _init_agent(monkeypatch, config_dir: Path) -> None:
    """Initialize an agent in the given config directory."""
    monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)
    runner.invoke(
        app,
        [
            "init",
            "--agent-id",
            "test-agent",
            "--endpoint",
            "https://example.com/swarm",
        ],
    )


# ---------------------------------------------------------------------------
# Unit tests for _server_base_url
# ---------------------------------------------------------------------------


class TestServerBaseUrl:
    """Unit tests for the URL derivation helper."""

    def test_strips_swarm_path(self):
        assert _server_base_url("https://host.example.com/swarm") == "https://host.example.com"

    def test_strips_trailing_slash(self):
        assert _server_base_url("https://host.example.com/swarm/") == "https://host.example.com"

    def test_preserves_port(self):
        assert _server_base_url("http://localhost:8081/swarm") == "http://localhost:8081"

    def test_no_path(self):
        assert _server_base_url("https://host.example.com") == "https://host.example.com"


# ---------------------------------------------------------------------------
# Validation tests (no server needed)
# ---------------------------------------------------------------------------


class TestMessagesWithoutInit:
    """Messages command fails without initialization."""

    def test_messages_list_without_init(self, monkeypatch):
        """Messages list fails if not initialized."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID])

            assert result.exit_code == 1
            assert "swarm init" in result.stdout.lower()

    def test_messages_count_without_init(self, monkeypatch):
        """Messages --count fails if not initialized."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID, "--count"])

            assert result.exit_code == 1
            assert "swarm init" in result.stdout.lower()

    def test_messages_ack_without_init(self, monkeypatch):
        """Messages --ack fails if not initialized."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["messages", "--ack", MSG_ID])

            assert result.exit_code == 1
            assert "swarm init" in result.stdout.lower()


class TestMessagesValidation:
    """Messages command validates input."""

    def test_messages_requires_swarm_id(self, monkeypatch):
        """Messages without --swarm or --ack fails with exit 2."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["messages"])

            assert result.exit_code == 2
            assert "Swarm ID is required" in result.stdout

    def test_messages_invalid_swarm_id(self, monkeypatch):
        """Messages with invalid UUID fails with exit 2."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["messages", "-s", "not-a-uuid"])

            assert result.exit_code == 2
            assert "UUID" in result.stdout

    def test_messages_invalid_status(self, monkeypatch):
        """Messages with invalid --status value fails with exit 2."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "bogus"]
            )

            assert result.exit_code == 2
            assert "Invalid status" in result.stdout
            assert "pending" in result.stdout


# ---------------------------------------------------------------------------
# List mode tests (mocking HTTP calls)
# ---------------------------------------------------------------------------


class TestMessagesList:
    """Messages list mode tests via mocked HTTP."""

    @patch("src.cli.commands.messages._fetch_messages", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_empty(self, mock_url, mock_fetch, monkeypatch):
        """Empty message list shows warning."""
        mock_fetch.return_value = {"count": 0, "messages": []}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID])

        assert result.exit_code == 0
        assert "No messages found" in result.stdout

    @patch("src.cli.commands.messages._fetch_messages", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_default_pending(self, mock_url, mock_fetch, monkeypatch):
        """Default list queries pending status."""
        mock_fetch.return_value = {
            "count": 1,
            "messages": [
                {
                    "message_id": MSG_ID,
                    "sender_id": "sender-agent",
                    "message_type": "chat",
                    "status": "pending",
                    "received_at": "2026-02-09T12:00:00+00:00",
                    "content_preview": "Hello from test",
                }
            ],
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID])

        assert result.exit_code == 0
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        assert call_args[0][2] == 10  # default limit
        assert call_args[0][3] == "pending"  # default status

    @patch("src.cli.commands.messages._fetch_messages", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_with_status_completed(self, mock_url, mock_fetch, monkeypatch):
        """List with --status completed passes correct filter."""
        mock_fetch.return_value = {
            "count": 1,
            "messages": [
                {
                    "message_id": MSG_ID,
                    "sender_id": "sender-agent",
                    "message_type": "chat",
                    "status": "completed",
                    "received_at": "2026-02-09T12:00:00+00:00",
                    "content_preview": "Hello from test",
                }
            ],
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "completed"]
            )

        assert result.exit_code == 0
        assert "sender-agent" in result.stdout
        call_args = mock_fetch.call_args
        assert call_args[0][3] == "completed"

    @patch("src.cli.commands.messages._fetch_messages", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_with_status_all(self, mock_url, mock_fetch, monkeypatch):
        """List with --status all passes 'all' filter."""
        mock_fetch.return_value = {
            "count": 1,
            "messages": [
                {
                    "message_id": MSG_ID,
                    "sender_id": "sender-agent",
                    "message_type": "chat",
                    "status": "completed",
                    "received_at": "2026-02-09T12:00:00+00:00",
                    "content_preview": "Hello from test",
                }
            ],
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "all"]
            )

        assert result.exit_code == 0
        call_args = mock_fetch.call_args
        assert call_args[0][3] == "all"

    @patch("src.cli.commands.messages._fetch_messages", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_with_messages(self, mock_url, mock_fetch, monkeypatch):
        """Message list displays table."""
        mock_fetch.return_value = {
            "count": 1,
            "messages": [
                {
                    "message_id": MSG_ID,
                    "sender_id": "sender-agent",
                    "message_type": "chat",
                    "status": "completed",
                    "received_at": "2026-02-09T12:00:00+00:00",
                    "content_preview": "Hello from test",
                }
            ],
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "completed"]
            )

        assert result.exit_code == 0
        assert "sender-agent" in result.stdout
        assert "Messages (1)" in result.stdout

    @patch("src.cli.commands.messages._fetch_messages", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_json_output(self, mock_url, mock_fetch, monkeypatch):
        """Message list with --json outputs valid JSON."""
        mock_fetch.return_value = {
            "count": 1,
            "messages": [
                {
                    "message_id": MSG_ID,
                    "sender_id": "sender-agent",
                    "message_type": "chat",
                    "status": "completed",
                    "received_at": "2026-02-09T12:00:00+00:00",
                    "content_preview": "Hello from test",
                }
            ],
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app,
                ["messages", "-s", SWARM_ID, "--status", "completed", "--json"],
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["swarm_id"] == SWARM_ID
        assert data["count"] == 1
        assert len(data["messages"]) == 1
        assert data["messages"][0]["sender_id"] == "sender-agent"


# ---------------------------------------------------------------------------
# Count mode tests
# ---------------------------------------------------------------------------


class TestMessagesCount:
    """Messages --count mode tests."""

    @patch("src.cli.commands.messages._fetch_count", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_count_display(self, mock_url, mock_count, monkeypatch):
        """Count mode shows pending count."""
        mock_count.return_value = {
            "pending": 5, "completed": 2, "failed": 0, "total": 7,
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID, "--count"])

        assert result.exit_code == 0
        assert "5" in result.stdout

    @patch("src.cli.commands.messages._fetch_count", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_count_json(self, mock_url, mock_count, monkeypatch):
        """Count mode with --json outputs valid JSON."""
        mock_count.return_value = {
            "pending": 3, "completed": 1, "failed": 0, "total": 4,
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--count", "--json"]
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["pending"] == 3
        assert data["swarm_id"] == SWARM_ID


# ---------------------------------------------------------------------------
# Ack mode tests
# ---------------------------------------------------------------------------


class TestMessagesAck:
    """Messages --ack mode tests."""

    @patch("src.cli.commands.messages._ack_message_api", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_ack_success(self, mock_url, mock_ack, monkeypatch):
        """Ack marks message as completed."""
        mock_ack.return_value = {"status": "acked", "message_id": MSG_ID}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--ack", MSG_ID])

        assert result.exit_code == 0
        assert "completed" in result.stdout

    @patch("src.cli.commands.messages._ack_message_api", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_ack_not_found(self, mock_url, mock_ack, monkeypatch):
        """Ack with unknown message ID fails with exit 5."""
        mock_ack.return_value = {"status": "not_found", "message_id": MSG_ID}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--ack", MSG_ID])

        assert result.exit_code == 5
        assert "not found" in result.stdout

    @patch("src.cli.commands.messages._ack_message_api", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_ack_json_success(self, mock_url, mock_ack, monkeypatch):
        """Ack with --json outputs valid JSON."""
        mock_ack.return_value = {"status": "acked", "message_id": MSG_ID}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--ack", MSG_ID, "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "acked"
        assert data["message_id"] == MSG_ID

    @patch("src.cli.commands.messages._ack_message_api", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_ack_json_not_found(self, mock_url, mock_ack, monkeypatch):
        """Ack --json with unknown ID returns not_found status."""
        mock_ack.return_value = {"status": "not_found", "message_id": MSG_ID}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--ack", MSG_ID, "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "not_found"
