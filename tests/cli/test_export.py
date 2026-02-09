"""Tests for swarm export command."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.cli.utils.config import ConfigManager

runner = CliRunner()


def _init_agent(monkeypatch, config_dir: Path) -> None:
    """Initialize an agent for testing."""
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


class TestExportCommand:
    """Tests for swarm export command."""

    def test_export_without_init(self, monkeypatch):
        """Export fails if agent is not initialized."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["export"])

            assert result.exit_code == 1
            assert "swarm init" in result.stdout.lower()

    def test_export_to_stdout(self, monkeypatch):
        """Export without -o prints JSON to stdout."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["export"])

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["agent_id"] == "test-agent"
            assert data["schema_version"] == "1.0.0"
            assert "swarms" in data
            assert "muted_agents" in data

    def test_export_to_file(self, monkeypatch):
        """Export with -o writes state to file."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            output_path = Path(tmpdir) / "state.json"
            result = runner.invoke(app, ["export", "-o", str(output_path)])

            assert result.exit_code == 0
            assert output_path.exists()
            assert "exported to" in result.stdout.lower()

            with open(output_path) as f:
                data = json.load(f)
            assert data["agent_id"] == "test-agent"
            assert data["schema_version"] == "1.0.0"

    def test_export_json_flag(self, monkeypatch):
        """Export with --json outputs JSON even with -o."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            output_path = Path(tmpdir) / "state.json"
            result = runner.invoke(
                app, ["export", "-o", str(output_path), "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["agent_id"] == "test-agent"
            assert output_path.exists()

    def test_export_file_summary(self, monkeypatch):
        """Export to file shows human-readable summary."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            output_path = Path(tmpdir) / "state.json"
            result = runner.invoke(app, ["export", "-o", str(output_path)])

            assert result.exit_code == 0
            assert "Swarms:" in result.stdout
            assert "Public Keys:" in result.stdout
            assert "Muted Agents:" in result.stdout
            assert "Muted Swarms:" in result.stdout
