"""Tests for swarm import command."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.cli.utils.config import ConfigManager

runner = CliRunner()

VALID_STATE = {
    "schema_version": "1.0.0",
    "agent_id": "test-agent",
    "exported_at": "2025-01-01T00:00:00+00:00",
    "swarms": {},
    "public_keys": {},
    "muted_agents": [],
    "muted_swarms": [],
}


def _init_agent(monkeypatch, config_dir: Path) -> None:
    """Initialize an agent in the given config directory."""
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


def _write_state(tmpdir: str, state: dict | None = None) -> Path:
    """Write a state JSON file and return its path."""
    path = Path(tmpdir) / "state.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state or VALID_STATE, f)
    return path


class TestImportCommand:
    """Tests for swarm import command."""

    def test_import_without_init(self, monkeypatch):
        """Import fails if agent not initialized."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)
            state_path = _write_state(tmpdir)

            result = runner.invoke(
                app, ["import", "--input", str(state_path), "--yes"]
            )

            assert result.exit_code == 1
            assert "swarm init" in result.stdout

    def test_import_file_not_found(self, monkeypatch):
        """Import fails with exit 5 if file does not exist."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(
                app, ["import", "--input", "/nonexistent/file.json", "--yes"]
            )

            assert result.exit_code == 5
            assert "File not found" in result.stdout

    def test_import_with_yes_skips_confirmation(self, monkeypatch):
        """Import with --yes skips the confirmation prompt."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)
            state_path = _write_state(tmpdir)

            result = runner.invoke(
                app, ["import", "--input", str(state_path), "--yes"]
            )

            assert result.exit_code == 0
            assert "imported to" in result.stdout

    def test_import_json_output(self, monkeypatch):
        """Import with --json outputs valid JSON."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)
            state_path = _write_state(tmpdir)

            result = runner.invoke(
                app, ["import", "--input", str(state_path), "--yes", "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["status"] == "imported"
            assert data["swarms"] == 0
            assert data["merge"] is False

    def test_import_merge_flag(self, monkeypatch):
        """Import with --merge skips confirmation and merges state."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)
            state_path = _write_state(tmpdir)

            result = runner.invoke(
                app, ["import", "--input", str(state_path), "--merge", "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["status"] == "imported"
            assert data["merge"] is True

    def test_import_invalid_schema(self, monkeypatch):
        """Import fails with exit 2 on invalid schema version."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)
            bad_state = {**VALID_STATE, "schema_version": "99.0.0"}
            state_path = _write_state(tmpdir, bad_state)

            result = runner.invoke(
                app, ["import", "--input", str(state_path), "--yes"]
            )

            assert result.exit_code == 2
            assert "Import failed" in result.stdout

    def test_import_counts_entries(self, monkeypatch):
        """Import reports correct counts in JSON output."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)
            state = {
                **VALID_STATE,
                "swarms": {
                    "s1": {
                        "swarm_id": "s1",
                        "name": "Test",
                        "master": "test-agent",
                        "members": [],
                        "joined_at": "2025-01-01T00:00:00+00:00",
                        "settings": {},
                    }
                },
                "muted_agents": ["agent-a", "agent-b"],
                "public_keys": {
                    "pk1": {
                        "public_key": "abc",
                        "fetched_at": "2025-01-01T00:00:00+00:00",
                    }
                },
            }
            state_path = _write_state(tmpdir, state)

            result = runner.invoke(
                app, ["import", "--input", str(state_path), "--yes", "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["swarms"] == 1
            assert data["muted_agents"] == 2
            assert data["public_keys"] == 1
