"""Tests for swarm messages command (inbox API, issue #156).

The messages command queries /api/inbox with unread/read/archived/all
status lifecycle and auto-marks unread messages as read.
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


def _sample_message(status: str = "unread") -> dict:
    """Return a sample inbox message dict."""
    return {
        "message_id": MSG_ID,
        "swarm_id": SWARM_ID,
        "sender_id": "sender-agent",
        "message_type": "chat",
        "status": status,
        "received_at": "2026-02-09T12:00:00+00:00",
        "content_preview": "Hello from test",
    }


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


class TestMessagesValidation:
    """Messages command validates input."""

    def test_messages_requires_swarm_id(self, monkeypatch):
        """Messages without --swarm fails with exit 2."""
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
        assert "unread" in result.stdout

    def test_old_status_values_rejected(self, monkeypatch):
        """Old status values (pending, completed, failed) are rejected."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            for old_status in ("pending", "completed", "failed"):
                result = runner.invoke(
                    app, ["messages", "-s", SWARM_ID, "--status", old_status]
                )
                assert result.exit_code == 2, f"Status '{old_status}' should be rejected"


# ---------------------------------------------------------------------------
# Without-init tests
# ---------------------------------------------------------------------------


class TestMessagesWithoutInit:
    """Messages command fails without initialization."""

    def test_messages_list_without_init(self, monkeypatch):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID])

        assert result.exit_code == 1
        assert "swarm init" in result.stdout.lower()

    def test_messages_count_without_init(self, monkeypatch):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID, "--count"])

        assert result.exit_code == 1
        assert "swarm init" in result.stdout.lower()

    def test_messages_archive_without_init(self, monkeypatch):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["messages", "--archive", MSG_ID])

        assert result.exit_code == 1
        assert "swarm init" in result.stdout.lower()

    def test_messages_delete_without_init(self, monkeypatch):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["messages", "--delete", MSG_ID])

        assert result.exit_code == 1
        assert "swarm init" in result.stdout.lower()


# ---------------------------------------------------------------------------
# List mode tests (mocking HTTP calls)
# ---------------------------------------------------------------------------


class TestMessagesList:
    """Messages list mode tests via mocked HTTP."""

    @patch("src.cli.commands.messages._batch_mark_read", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_empty(self, mock_url, mock_fetch, mock_batch, monkeypatch):
        """Empty message list shows warning."""
        mock_fetch.return_value = {"count": 0, "messages": []}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID])

        assert result.exit_code == 0
        assert "No messages found" in result.stdout
        mock_batch.assert_not_called()

    @patch("src.cli.commands.messages._batch_mark_read", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_default_unread(self, mock_url, mock_fetch, mock_batch, monkeypatch):
        """Default list queries unread status and auto-marks as read."""
        mock_fetch.return_value = {"count": 1, "messages": [_sample_message()]}
        mock_batch.return_value = {"action": "read", "updated": 1, "total": 1}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID])

        assert result.exit_code == 0
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        assert call_args[0][2] == 10  # default limit
        assert call_args[0][3] == "unread"  # default status
        # Auto-mark-read should have been called
        mock_batch.assert_called_once_with(BASE_URL, [MSG_ID])

    @patch("src.cli.commands.messages._batch_mark_read", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_no_mark_read_flag(self, mock_url, mock_fetch, mock_batch, monkeypatch):
        """--no-mark-read prevents auto-marking."""
        mock_fetch.return_value = {"count": 1, "messages": [_sample_message()]}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--no-mark-read"]
            )

        assert result.exit_code == 0
        mock_batch.assert_not_called()

    @patch("src.cli.commands.messages._batch_mark_read", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_read_status_no_automark(self, mock_url, mock_fetch, mock_batch, monkeypatch):
        """Listing read messages does not trigger auto-mark."""
        mock_fetch.return_value = {"count": 1, "messages": [_sample_message("read")]}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "read"]
            )

        assert result.exit_code == 0
        mock_batch.assert_not_called()

    @patch("src.cli.commands.messages._batch_mark_read", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_all_status_no_automark(self, mock_url, mock_fetch, mock_batch, monkeypatch):
        """Listing with --status all does not trigger auto-mark."""
        mock_fetch.return_value = {"count": 1, "messages": [_sample_message()]}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--status", "all"]
            )

        assert result.exit_code == 0
        mock_batch.assert_not_called()

    @patch("src.cli.commands.messages._batch_mark_read", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_displays_table(self, mock_url, mock_fetch, mock_batch, monkeypatch):
        """Message list displays table with inbox header."""
        mock_fetch.return_value = {"count": 1, "messages": [_sample_message()]}
        mock_batch.return_value = {"action": "read", "updated": 1, "total": 1}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID])

        assert result.exit_code == 0
        assert "sender-agent" in result.stdout
        assert "Inbox" in result.stdout

    @patch("src.cli.commands.messages._batch_mark_read", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_json_output(self, mock_url, mock_fetch, mock_batch, monkeypatch):
        """Message list with --json includes marked_read count."""
        mock_fetch.return_value = {"count": 1, "messages": [_sample_message()]}
        mock_batch.return_value = {"action": "read", "updated": 1, "total": 1}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--json"],
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["swarm_id"] == SWARM_ID
        assert data["count"] == 1
        assert data["marked_read"] == 1
        assert len(data["messages"]) == 1

    @patch("src.cli.commands.messages._batch_mark_read", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_list_json_no_mark_read(self, mock_url, mock_fetch, mock_batch, monkeypatch):
        """JSON output with --no-mark-read omits marked_read field."""
        mock_fetch.return_value = {"count": 1, "messages": [_sample_message()]}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--json", "--no-mark-read"],
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "marked_read" not in data


# ---------------------------------------------------------------------------
# Count mode tests
# ---------------------------------------------------------------------------


class TestMessagesCount:
    """Messages --count mode tests."""

    @patch("src.cli.commands.messages._fetch_count", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_count_display(self, mock_url, mock_count, monkeypatch):
        """Count mode shows unread, read, and total."""
        mock_count.return_value = {
            "unread": 5, "read": 2, "archived": 0, "deleted": 0, "total": 7,
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "-s", SWARM_ID, "--count"])

        assert result.exit_code == 0
        assert "5" in result.stdout
        assert "7" in result.stdout

    @patch("src.cli.commands.messages._fetch_count", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_count_json(self, mock_url, mock_count, monkeypatch):
        """Count mode with --json outputs valid JSON."""
        mock_count.return_value = {
            "unread": 3, "read": 1, "archived": 0, "deleted": 0, "total": 4,
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "-s", SWARM_ID, "--count", "--json"]
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["unread"] == 3
        assert data["swarm_id"] == SWARM_ID


# ---------------------------------------------------------------------------
# Archive mode tests
# ---------------------------------------------------------------------------


class TestMessagesArchive:
    """Messages --archive mode tests."""

    @patch("src.cli.commands.messages._archive_message", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_archive_success(self, mock_url, mock_archive, monkeypatch):
        """Archive marks message as archived."""
        mock_archive.return_value = {"status": "archived", "message_id": MSG_ID}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--archive", MSG_ID])

        assert result.exit_code == 0
        assert "archived" in result.stdout

    @patch("src.cli.commands.messages._archive_message", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_archive_not_found(self, mock_url, mock_archive, monkeypatch):
        """Archive with unknown message ID fails with exit 5."""
        mock_archive.return_value = {"error": f"Message {MSG_ID} not found"}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--archive", MSG_ID])

        assert result.exit_code == 5
        assert "not found" in result.stdout

    @patch("src.cli.commands.messages._archive_message", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_archive_json(self, mock_url, mock_archive, monkeypatch):
        """Archive with --json outputs valid JSON."""
        mock_archive.return_value = {"status": "archived", "message_id": MSG_ID}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--archive", MSG_ID, "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "archived"


# ---------------------------------------------------------------------------
# Delete mode tests
# ---------------------------------------------------------------------------


class TestMessagesDelete:
    """Messages --delete mode tests."""

    @patch("src.cli.commands.messages._delete_message", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_delete_success(self, mock_url, mock_delete, monkeypatch):
        """Delete soft-deletes a message."""
        mock_delete.return_value = {"status": "deleted", "message_id": MSG_ID}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--delete", MSG_ID])

        assert result.exit_code == 0
        assert "deleted" in result.stdout

    @patch("src.cli.commands.messages._delete_message", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_delete_not_found(self, mock_url, mock_delete, monkeypatch):
        """Delete with unknown message ID fails with exit 1."""
        mock_delete.return_value = {"error": f"Message {MSG_ID} not found"}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--delete", MSG_ID])

        assert result.exit_code == 1

    @patch("src.cli.commands.messages._delete_message", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_delete_json(self, mock_url, mock_delete, monkeypatch):
        """Delete with --json outputs valid JSON."""
        mock_delete.return_value = {"status": "deleted", "message_id": MSG_ID}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--delete", MSG_ID, "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "deleted"


# ---------------------------------------------------------------------------
# Archive-all mode tests
# ---------------------------------------------------------------------------


class TestMessagesArchiveAll:
    """Messages --archive-all mode tests."""

    def test_archive_all_requires_swarm_id(self, monkeypatch):
        """--archive-all without --swarm exits with code 2."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["messages", "--archive-all"])

        assert result.exit_code == 2
        assert "Swarm ID is required" in result.stdout

    @patch("src.cli.commands.messages._batch_inbox_action", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_archive_all_success(
        self, mock_url, mock_fetch, mock_batch, monkeypatch,
    ):
        """--archive-all archives read messages."""
        mock_fetch.return_value = {
            "count": 2,
            "messages": [
                {"message_id": "msg-1", "sender_id": "a", "status": "read",
                 "received_at": "2026-02-09T12:00:00", "content_preview": "hi"},
                {"message_id": "msg-2", "sender_id": "b", "status": "read",
                 "received_at": "2026-02-09T12:01:00", "content_preview": "yo"},
            ],
        }
        mock_batch.return_value = {"action": "archive", "updated": 2, "total": 2}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "--archive-all", "-s", SWARM_ID]
            )

        assert result.exit_code == 0
        assert "Archived 2 of 2" in result.stdout
        mock_batch.assert_called_once()
        call_args = mock_batch.call_args
        assert call_args[0][1] == ["msg-1", "msg-2"]
        assert call_args[0][2] == "archive"

    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_archive_all_no_read_messages(
        self, mock_url, mock_fetch, monkeypatch,
    ):
        """--archive-all with no read messages shows info."""
        mock_fetch.return_value = {"count": 0, "messages": []}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "--archive-all", "-s", SWARM_ID]
            )

        assert result.exit_code == 0
        assert "No read messages to archive" in result.stdout

    @patch("src.cli.commands.messages._batch_inbox_action", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_archive_all_json(
        self, mock_url, mock_fetch, mock_batch, monkeypatch,
    ):
        """--archive-all --json outputs batch response."""
        mock_fetch.return_value = {
            "count": 1,
            "messages": [
                {"message_id": "msg-1", "sender_id": "a", "status": "read",
                 "received_at": "2026-02-09T12:00:00", "content_preview": "hi"},
            ],
        }
        mock_batch.return_value = {"action": "archive", "updated": 1, "total": 1}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "--archive-all", "-s", SWARM_ID, "--json"]
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["action"] == "archive"
        assert data["updated"] == 1

    @patch("src.cli.commands.messages._fetch_inbox", new_callable=AsyncMock)
    @patch("src.cli.commands.messages._load_base_url", return_value=BASE_URL)
    def test_archive_all_empty_json(
        self, mock_url, mock_fetch, monkeypatch,
    ):
        """--archive-all --json with no messages returns zero counts."""
        mock_fetch.return_value = {"count": 0, "messages": []}

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["messages", "--archive-all", "-s", SWARM_ID, "--json"]
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["updated"] == 0
