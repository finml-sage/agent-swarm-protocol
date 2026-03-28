"""Tests for swarm config command."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from src.cli.main import app
from src.cli.utils.config import ConfigManager

runner = CliRunner()

SWARM_UUID = "716a4150-ab9d-4b54-a2a8-f2b7c607c21e"


def _init_agent(monkeypatch, config_dir: Path) -> None:
    monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)
    result = runner.invoke(
        app,
        ["init", "--agent-id", "test-agent", "--endpoint", "https://example.com/swarm"],
    )
    assert result.exit_code == 0


class TestConfigCommand:
    """Tests for swarm config subcommand."""

    def test_config_shows_agent_info(self, monkeypatch):
        monkeypatch.delenv("SWARM_ID", raising=False)
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            with patch(
                "src.cli.commands.config._auto_detect_single_swarm",
                return_value=None,
            ):
                result = runner.invoke(app, ["config"])

        assert result.exit_code == 0
        assert "test-agent" in result.stdout
        assert "example.com" in result.stdout

    def test_config_shows_resolved_swarm(self, monkeypatch):
        monkeypatch.setenv("SWARM_ID", SWARM_UUID)
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["config"])

        assert result.exit_code == 0
        assert SWARM_UUID in result.stdout
        assert "environment variable" in result.stdout

    def test_config_json_output(self, monkeypatch):
        monkeypatch.delenv("SWARM_ID", raising=False)
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            with patch(
                "src.cli.commands.config._auto_detect_single_swarm",
                return_value=None,
            ):
                result = runner.invoke(app, ["config", "--json"])

        assert result.exit_code == 0
        import json
        data = json.loads(result.stdout)
        assert data["agent_id"] == "test-agent"
        assert data["resolved_swarm_id"] is None
        assert data["resolved_via"] == "not resolved"

    def test_config_shows_default_swarm(self, monkeypatch):
        monkeypatch.delenv("SWARM_ID", raising=False)
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            # Add default_swarm to config
            config_path = config_dir / "config.yaml"
            with open(config_path) as f:
                data = yaml.safe_load(f)
            data["default_swarm"] = SWARM_UUID
            with open(config_path, "w") as f:
                yaml.safe_dump(data, f)

            result = runner.invoke(app, ["config"])

        assert result.exit_code == 0
        assert SWARM_UUID in result.stdout
        assert "default_swarm" in result.stdout

    def test_config_fails_without_init(self, monkeypatch):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["config"])

        assert result.exit_code == 1
        assert "Config not found" in result.stdout
