"""Tests for CLI commands."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.cli.utils.config import ConfigManager
from src.client import generate_keypair

runner = CliRunner()


class TestInitCommand:
    """Tests for swarm init command."""

    def test_init_creates_config(self, monkeypatch):
        """Init creates config files in ~/.swarm."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
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
            assert "initialized successfully" in result.stdout
            assert (config_dir / "config.yaml").exists()
            assert (config_dir / "agent.key").exists()

    def test_init_json_output(self, monkeypatch):
        """Init with --json outputs JSON."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(
                app,
                [
                    "init",
                    "--agent-id",
                    "test-agent",
                    "--endpoint",
                    "https://example.com/swarm",
                    "--json",
                ],
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["status"] == "initialized"
            assert data["agent_id"] == "test-agent"

    def test_init_fails_without_force(self, monkeypatch):
        """Init fails if config exists without --force."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            runner.invoke(
                app,
                [
                    "init",
                    "--agent-id",
                    "first",
                    "--endpoint",
                    "https://example.com",
                ],
            )

            result = runner.invoke(
                app,
                [
                    "init",
                    "--agent-id",
                    "second",
                    "--endpoint",
                    "https://example.com",
                ],
            )

            assert result.exit_code == 1
            assert "already exists" in result.stdout

    def test_init_with_force_overwrites(self, monkeypatch):
        """Init with --force overwrites existing config."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            runner.invoke(
                app,
                [
                    "init",
                    "--agent-id",
                    "first",
                    "--endpoint",
                    "https://example.com",
                ],
            )

            result = runner.invoke(
                app,
                [
                    "init",
                    "--agent-id",
                    "second",
                    "--endpoint",
                    "https://example.com",
                    "--force",
                ],
            )

            assert result.exit_code == 0
            assert "initialized successfully" in result.stdout

    def test_init_validates_agent_id(self, monkeypatch):
        """Init validates agent ID format."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(
                app,
                [
                    "init",
                    "--agent-id",
                    "invalid@agent",
                    "--endpoint",
                    "https://example.com",
                ],
            )

            assert result.exit_code == 2

    def test_init_validates_endpoint(self, monkeypatch):
        """Init validates endpoint is HTTPS."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(
                app,
                [
                    "init",
                    "--agent-id",
                    "test-agent",
                    "--endpoint",
                    "http://example.com",
                ],
            )

            assert result.exit_code == 2
            assert "HTTPS" in result.stdout


class TestStatusCommand:
    """Tests for swarm status command."""

    def test_status_without_init(self, monkeypatch):
        """Status fails if not initialized."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["status"])

            assert result.exit_code == 1
            assert "swarm init" in result.stdout

    def test_status_shows_config(self, monkeypatch):
        """Status shows agent configuration."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            runner.invoke(
                app,
                [
                    "init",
                    "--agent-id",
                    "test-agent",
                    "--endpoint",
                    "https://example.com",
                ],
            )

            result = runner.invoke(app, ["status"])

            assert result.exit_code == 0
            assert "test-agent" in result.stdout
            assert "https://example.com" in result.stdout

    def test_status_json_output(self, monkeypatch):
        """Status with --json outputs JSON."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            runner.invoke(
                app,
                [
                    "init",
                    "--agent-id",
                    "test-agent",
                    "--endpoint",
                    "https://example.com",
                ],
            )

            result = runner.invoke(app, ["status", "--json"])

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["status"] == "initialized"
            assert data["agent_id"] == "test-agent"
