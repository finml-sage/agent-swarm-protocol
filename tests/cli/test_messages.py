"""Tests for swarm messages command."""

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.cli.utils.config import ConfigManager
from src.state.models.message import MessageStatus, QueuedMessage

runner = CliRunner()

SWARM_ID = "716a4150-ab9d-4b54-a2a8-f2b7c607c21e"
MSG_ID = "abc12345-dead-beef-cafe-000000000001"


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


def _make_message(
    message_id: str = MSG_ID,
    status: MessageStatus = MessageStatus.COMPLETED,
) -> QueuedMessage:
    """Create a test QueuedMessage."""
    return QueuedMessage(
        message_id=message_id,
        swarm_id=SWARM_ID,
        sender_id="sender-agent",
        message_type="chat",
        content="Hello from test",
        received_at=datetime(2026, 2, 9, 12, 0, 0, tzinfo=timezone.utc),
        status=status,
    )


class TestMessagesWithoutInit:
    """Messages command fails without initialization."""

    def test_messages_list_without_init(self, monkeypatch):
        """Messages list fails if not initialized."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID]
            )

            assert result.exit_code == 1
            assert "swarm init" in result.stdout

    def test_messages_count_without_init(self, monkeypatch):
        """Messages --count fails if not initialized."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--count"]
            )

            assert result.exit_code == 1
            assert "swarm init" in result.stdout

    def test_messages_ack_without_init(self, monkeypatch):
        """Messages --ack fails if not initialized."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(
                app, ["messages", "--ack", MSG_ID]
            )

            assert result.exit_code == 1
            assert "swarm init" in result.stdout


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

            result = runner.invoke(
                app, ["messages", "-s", "not-a-uuid"]
            )

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


class TestMessagesList:
    """Messages list mode tests."""

    @patch("src.cli.commands.messages._list_messages")
    def test_list_empty(self, mock_list, monkeypatch):
        """Empty message list shows warning."""
        mock_list.return_value = []

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID]
            )

            assert result.exit_code == 0
            assert "No messages found" in result.stdout

    @patch("src.cli.commands.messages._list_messages")
    def test_list_default_pending(self, mock_list, monkeypatch):
        """Default list shows pending messages."""
        mock_list.return_value = [
            {
                "message_id": MSG_ID,
                "sender_id": "sender-agent",
                "message_type": "chat",
                "status": "pending",
                "received_at": "2026-02-09T12:00:00+00:00",
                "content_preview": "Hello from test",
            }
        ]

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID]
            )

            assert result.exit_code == 0
            mock_list.assert_called_once()
            call_args = mock_list.call_args[0]
            assert call_args[2] == "pending"

    @patch("src.cli.commands.messages._list_messages")
    def test_list_with_status_completed(self, mock_list, monkeypatch):
        """List with --status completed filters by completed."""
        mock_list.return_value = [
            {
                "message_id": MSG_ID,
                "sender_id": "sender-agent",
                "message_type": "chat",
                "status": "completed",
                "received_at": "2026-02-09T12:00:00+00:00",
                "content_preview": "Hello from test",
            }
        ]

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "completed"]
            )

            assert result.exit_code == 0
            assert "sender-agent" in result.stdout
            call_args = mock_list.call_args[0]
            assert call_args[2] == "completed"

    @patch("src.cli.commands.messages._list_messages")
    def test_list_with_status_all(self, mock_list, monkeypatch):
        """List with --status all shows all statuses."""
        mock_list.return_value = [
            {
                "message_id": MSG_ID,
                "sender_id": "sender-agent",
                "message_type": "chat",
                "status": "completed",
                "received_at": "2026-02-09T12:00:00+00:00",
                "content_preview": "Hello from test",
            }
        ]

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "all"]
            )

            assert result.exit_code == 0
            call_args = mock_list.call_args[0]
            assert call_args[2] == "all"

    @patch("src.cli.commands.messages._list_messages")
    def test_list_with_status_failed(self, mock_list, monkeypatch):
        """List with --status failed filters by failed."""
        mock_list.return_value = []

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "failed"]
            )

            assert result.exit_code == 0
            call_args = mock_list.call_args[0]
            assert call_args[2] == "failed"

    @patch("src.cli.commands.messages._list_messages")
    def test_list_with_messages(self, mock_list, monkeypatch):
        """Message list displays table."""
        mock_list.return_value = [
            {
                "message_id": MSG_ID,
                "sender_id": "sender-agent",
                "message_type": "chat",
                "status": "completed",
                "received_at": "2026-02-09T12:00:00+00:00",
                "content_preview": "Hello from test",
            }
        ]

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "completed"]
            )

            assert result.exit_code == 0
            assert "sender-agent" in result.stdout
            assert "Messages (1)" in result.stdout

    @patch("src.cli.commands.messages._list_messages")
    def test_list_json_output(self, mock_list, monkeypatch):
        """Message list with --json outputs valid JSON."""
        mock_list.return_value = [
            {
                "message_id": MSG_ID,
                "sender_id": "sender-agent",
                "message_type": "chat",
                "status": "completed",
                "received_at": "2026-02-09T12:00:00+00:00",
                "content_preview": "Hello from test",
            }
        ]

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "completed", "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["swarm_id"] == SWARM_ID
            assert data["count"] == 1
            assert len(data["messages"]) == 1
            assert data["messages"][0]["sender_id"] == "sender-agent"


class TestMessagesCount:
    """Messages --count mode tests."""

    @patch("src.cli.commands.messages._pending_count")
    def test_count_display(self, mock_count, monkeypatch):
        """Count mode shows pending count."""
        mock_count.return_value = 5

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--count"]
            )

            assert result.exit_code == 0
            assert "5" in result.stdout

    @patch("src.cli.commands.messages._pending_count")
    def test_count_json(self, mock_count, monkeypatch):
        """Count mode with --json outputs valid JSON."""
        mock_count.return_value = 3

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--count", "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["pending_count"] == 3
            assert data["swarm_id"] == SWARM_ID


class TestMessagesAck:
    """Messages --ack mode tests."""

    @patch("src.cli.commands.messages._ack_message")
    def test_ack_success(self, mock_ack, monkeypatch):
        """Ack marks message as completed."""
        mock_ack.return_value = True

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "--ack", MSG_ID]
            )

            assert result.exit_code == 0
            assert "completed" in result.stdout

    @patch("src.cli.commands.messages._ack_message")
    def test_ack_not_found(self, mock_ack, monkeypatch):
        """Ack with unknown message ID fails with exit 5."""
        mock_ack.return_value = False

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "--ack", MSG_ID]
            )

            assert result.exit_code == 5
            assert "not found" in result.stdout

    @patch("src.cli.commands.messages._ack_message")
    def test_ack_json_success(self, mock_ack, monkeypatch):
        """Ack with --json outputs valid JSON."""
        mock_ack.return_value = True

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "--ack", MSG_ID, "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["status"] == "acked"
            assert data["message_id"] == MSG_ID

    @patch("src.cli.commands.messages._ack_message")
    def test_ack_json_not_found(self, mock_ack, monkeypatch):
        """Ack --json with unknown ID returns not_found status."""
        mock_ack.return_value = False

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "--ack", MSG_ID, "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["status"] == "not_found"
