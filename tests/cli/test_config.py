"""Tests for CLI configuration management."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.cli.utils.config import AgentConfig, ConfigError, ConfigManager
from src.client import generate_keypair


class TestConfigManager:
    """Tests for ConfigManager."""

    def test_default_config_dir(self):
        """Default config dir is ~/.swarm."""
        manager = ConfigManager()
        assert manager.config_dir == Path.home() / ".swarm"

    def test_custom_config_dir(self):
        """Custom config dir is respected."""
        custom = Path("/tmp/custom-swarm")
        manager = ConfigManager(custom)
        assert manager.config_dir == custom

    def test_exists_returns_false_when_missing(self):
        """exists() returns False when config doesn't exist."""
        with TemporaryDirectory() as tmpdir:
            manager = ConfigManager(Path(tmpdir) / "nonexistent")
            assert manager.exists() is False

    def test_save_and_load(self):
        """Configuration can be saved and loaded."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            manager = ConfigManager(config_dir)

            private_key, _ = generate_keypair()
            manager.save("test-agent", "https://example.com/swarm", private_key)

            assert manager.exists()

            loaded = manager.load()
            assert isinstance(loaded, AgentConfig)
            assert loaded.agent_id == "test-agent"
            assert loaded.endpoint == "https://example.com/swarm"
            assert loaded.db_path == config_dir / "swarm.db"

    def test_key_file_permissions(self):
        """Private key file is chmod 600."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            manager = ConfigManager(config_dir)

            private_key, _ = generate_keypair()
            manager.save("test-agent", "https://example.com/swarm", private_key)

            key_path = config_dir / "agent.key"
            mode = key_path.stat().st_mode & 0o777
            assert mode == 0o600

    def test_load_missing_config_raises(self):
        """Loading missing config raises ConfigError."""
        with TemporaryDirectory() as tmpdir:
            manager = ConfigManager(Path(tmpdir) / "nonexistent")
            with pytest.raises(ConfigError, match="Config not found"):
                manager.load()

    def test_load_missing_key_raises(self):
        """Loading with missing key file raises ConfigError."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            config_dir.mkdir()

            config_file = config_dir / "config.yaml"
            config_file.write_text("agent_id: test\nendpoint: https://example.com")

            manager = ConfigManager(config_dir)
            with pytest.raises(ConfigError, match="Key file not found"):
                manager.load()
