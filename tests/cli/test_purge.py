"""Tests for swarm purge command."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

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


class TestPurgeCommand:
    """Tests for swarm purge command."""

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

    def test_purge_messages(self, monkeypatch):
        """Purge --messages --yes succeeds with zero purged."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["purge", "--messages", "--yes"])

            assert result.exit_code == 0
            assert "Purged 0 old messages" in result.stdout

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
            assert "Purged 0 old messages" in result.stdout
            assert "Purged 0 expired sessions" in result.stdout

    def test_purge_json_output(self, monkeypatch):
        """Purge --json outputs valid JSON with purge counts."""
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
            assert data["retention_days"] == 30
            assert data["timeout_minutes"] == 60

    def test_purge_custom_retention(self, monkeypatch):
        """Purge respects --retention-days flag."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app,
                ["purge", "--messages", "--yes", "--json", "--retention-days", "7"],
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["retention_days"] == 7

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
