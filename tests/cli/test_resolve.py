"""Tests for swarm ID resolution helper."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
import yaml

from src.cli.utils.config import ConfigManager
from src.cli.utils.resolve import (
    SwarmIdError,
    _auto_detect_single_swarm,
    _read_default_swarm_from_config,
    resolve_swarm_id,
)

SWARM_UUID = "716a4150-ab9d-4b54-a2a8-f2b7c607c21e"
SWARM_UUID2 = "826b5260-bc0e-5c65-b3b9-03c8d718d32f"


class TestResolveSwarmIdCliFlag:
    """Step 1: CLI flag takes highest priority."""

    def test_cli_flag_valid_uuid(self):
        result = resolve_swarm_id(SWARM_UUID)
        assert result == UUID(SWARM_UUID)

    def test_cli_flag_invalid_uuid(self):
        with pytest.raises(ValueError, match="valid UUID"):
            resolve_swarm_id("not-a-uuid")

    def test_cli_flag_empty_string_falls_through(self, monkeypatch):
        """Empty string is falsy, treated as no CLI flag provided."""
        monkeypatch.delenv("SWARM_ID", raising=False)
        with patch(
            "src.cli.utils.resolve._read_default_swarm_from_config",
            return_value=None,
        ), patch(
            "src.cli.utils.resolve._auto_detect_single_swarm",
            return_value=None,
        ):
            with pytest.raises(SwarmIdError, match="No swarm ID"):
                resolve_swarm_id("")


class TestResolveSwarmIdEnvVar:
    """Step 2: SWARM_ID environment variable."""

    def test_env_var_used_when_no_cli_flag(self, monkeypatch):
        monkeypatch.setenv("SWARM_ID", SWARM_UUID)
        result = resolve_swarm_id(None)
        assert result == UUID(SWARM_UUID)

    def test_cli_flag_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("SWARM_ID", SWARM_UUID2)
        result = resolve_swarm_id(SWARM_UUID)
        assert result == UUID(SWARM_UUID)

    def test_env_var_invalid_uuid(self, monkeypatch):
        monkeypatch.setenv("SWARM_ID", "bad-uuid")
        with pytest.raises(ValueError, match="valid UUID"):
            resolve_swarm_id(None)


class TestResolveSwarmIdConfig:
    """Step 3: default_swarm in config.yaml."""

    def test_config_default_swarm_used(self, monkeypatch):
        monkeypatch.delenv("SWARM_ID", raising=False)
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            config_dir.mkdir()
            config_path = config_dir / "config.yaml"
            config_path.write_text(
                yaml.dump({"agent_id": "test", "endpoint": "https://x.com", "default_swarm": SWARM_UUID})
            )
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            with patch(
                "src.cli.utils.resolve._auto_detect_single_swarm",
                return_value=None,
            ):
                result = resolve_swarm_id(None)

        assert result == UUID(SWARM_UUID)

    def test_config_no_default_swarm(self, monkeypatch):
        monkeypatch.delenv("SWARM_ID", raising=False)
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            config_dir.mkdir()
            config_path = config_dir / "config.yaml"
            config_path.write_text(
                yaml.dump({"agent_id": "test", "endpoint": "https://x.com"})
            )
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            with patch(
                "src.cli.utils.resolve._auto_detect_single_swarm",
                return_value=None,
            ):
                with pytest.raises(SwarmIdError, match="No swarm ID"):
                    resolve_swarm_id(None)


class TestResolveSwarmIdAutoDetect:
    """Step 4: Auto-detect single swarm from DB."""

    def test_auto_detect_single_swarm(self, monkeypatch):
        monkeypatch.delenv("SWARM_ID", raising=False)
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            with patch(
                "src.cli.utils.resolve._read_default_swarm_from_config",
                return_value=None,
            ), patch(
                "src.cli.utils.resolve._auto_detect_single_swarm",
                return_value=SWARM_UUID,
            ):
                result = resolve_swarm_id(None)

        assert result == UUID(SWARM_UUID)


class TestResolveSwarmIdError:
    """Step 5: Helpful error when nothing resolved."""

    def test_error_when_nothing_found(self, monkeypatch):
        monkeypatch.delenv("SWARM_ID", raising=False)
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            with patch(
                "src.cli.utils.resolve._auto_detect_single_swarm",
                return_value=None,
            ):
                with pytest.raises(SwarmIdError) as exc_info:
                    resolve_swarm_id(None)

        error_msg = str(exc_info.value)
        assert "default_swarm" in error_msg
        assert "SWARM_ID" in error_msg
        assert "-s" in error_msg


class TestReadDefaultSwarmFromConfig:
    """Tests for _read_default_swarm_from_config."""

    def test_returns_none_when_no_config(self, monkeypatch):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "nonexistent"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)
            assert _read_default_swarm_from_config() is None

    def test_returns_value_when_present(self, monkeypatch):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            config_dir.mkdir()
            config_path = config_dir / "config.yaml"
            config_path.write_text(
                yaml.dump({"agent_id": "a", "endpoint": "https://x.com", "default_swarm": SWARM_UUID})
            )
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)
            assert _read_default_swarm_from_config() == SWARM_UUID

    def test_returns_none_when_field_missing(self, monkeypatch):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            config_dir.mkdir()
            config_path = config_dir / "config.yaml"
            config_path.write_text(yaml.dump({"agent_id": "a"}))
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)
            assert _read_default_swarm_from_config() is None


class TestAutoDetectSingleSwarm:
    """Tests for _auto_detect_single_swarm."""

    def test_returns_none_when_no_config(self, monkeypatch):
        """Returns None when config doesn't exist."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "nonexistent"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)
            import asyncio
            result = asyncio.run(_auto_detect_single_swarm())
            assert result is None
