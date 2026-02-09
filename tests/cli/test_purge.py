"""Tests for swarm purge command (inbox schema v2.0.0).

Purge now operates on the inbox table: --messages purges soft-deleted
messages, --include-archived also purges archived messages.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.cli.utils.config import ConfigManager

runner = CliRunner()


def _init_agent(monkeypatch, config_dir: Path) -> None:
    """Initialize a test agent with config and database."""
    monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)
    result = runner.invoke(
        app,
        [
            "init",
            "--agent-id",
            "test-agent",
            "--endpoint",
            "https://example.com/swarm",
        ],
    )
    assert result.exit_code == 0


class TestPurgeValidation:
    """Tests for purge command input validation."""

    def test_purge_without_flags_exits_2(self, monkeypatch):
        """Purge without --messages or --sessions exits with code 2."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["purge", "--yes"])

            assert result.exit_code == 2
            assert "Specify --messages, --sessions, or both" in result.stdout

    def test_purge_without_init_exits_1(self, monkeypatch):
        """Purge without agent init exits with code 1."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["purge", "--messages", "--yes"])

            assert result.exit_code == 1
            assert "swarm init" in result.stdout

    def test_purge_confirmation_cancelled(self, monkeypatch):
        """Purge prompts for confirmation and exits on decline."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["purge", "--messages"], input="n\n"
            )

            assert result.exit_code == 0
            assert "Cancelled" in result.stdout


class TestPurgeMessages:
    """Tests for purge --messages (inbox deleted messages)."""

    def test_purge_messages(self, monkeypatch):
        """Purge --messages --yes succeeds with zero purged."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["purge", "--messages", "--yes"])

            assert result.exit_code == 0
            assert "Purged 0 deleted messages" in result.stdout

    def test_purge_messages_json(self, monkeypatch):
        """Purge --messages --json outputs valid JSON."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["purge", "--messages", "--yes", "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["status"] == "purged"
            assert data["messages_purged"] == 0


class TestPurgeIncludeArchived:
    """Tests for purge --messages --include-archived."""

    def test_purge_include_archived(self, monkeypatch):
        """Purge --messages --include-archived --yes reports both counts."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["purge", "--messages", "--include-archived", "--yes"]
            )

            assert result.exit_code == 0
            assert "Purged 0 deleted messages" in result.stdout
            assert "Purged 0 archived messages" in result.stdout

    def test_purge_include_archived_json(self, monkeypatch):
        """Purge --include-archived --json includes archived_purged key."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app,
                ["purge", "--messages", "--include-archived", "--yes", "--json"],
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["status"] == "purged"
            assert data["messages_purged"] == 0
            assert data["archived_purged"] == 0

    def test_purge_confirmation_shows_archived_label(self, monkeypatch):
        """Confirmation prompt mentions archived when --include-archived."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["purge", "--messages", "--include-archived"], input="n\n"
            )

            assert result.exit_code == 0
            assert "archived" in result.stdout.lower()


class TestPurgeSessions:
    """Tests for purge --sessions."""

    def test_purge_sessions(self, monkeypatch):
        """Purge --sessions --yes succeeds with zero purged."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["purge", "--sessions", "--yes"])

            assert result.exit_code == 0
            assert "Purged 0 expired sessions" in result.stdout

    def test_purge_both(self, monkeypatch):
        """Purge --messages --sessions --yes shows both results."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["purge", "--messages", "--sessions", "--yes"]
            )

            assert result.exit_code == 0
            assert "Purged 0 deleted messages" in result.stdout
            assert "Purged 0 expired sessions" in result.stdout

    def test_purge_both_json(self, monkeypatch):
        """Purge --messages --sessions --json outputs complete JSON."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["purge", "--messages", "--sessions", "--yes", "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["status"] == "purged"
            assert data["messages_purged"] == 0
            assert data["sessions_purged"] == 0

    def test_purge_custom_timeout(self, monkeypatch):
        """Purge respects --timeout-minutes flag."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app,
                ["purge", "--sessions", "--yes", "--json", "--timeout-minutes", "120"],
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["timeout_minutes"] == 120
