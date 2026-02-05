"""Configuration file management for CLI."""

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)


@dataclass
class AgentConfig:
    """Agent configuration loaded from config file."""

    agent_id: str
    endpoint: str
    private_key: Ed25519PrivateKey
    db_path: Path


class ConfigError(Exception):
    """Configuration file error."""

    pass


class ConfigManager:
    """Manages agent configuration in ~/.swarm/config.yaml."""

    DEFAULT_DIR = Path.home() / ".swarm"
    CONFIG_FILE = "config.yaml"
    KEY_FILE = "agent.key"
    DB_FILE = "swarm.db"

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._config_dir = config_dir or self.DEFAULT_DIR
        self._config_path = self._config_dir / self.CONFIG_FILE
        self._key_path = self._config_dir / self.KEY_FILE
        self._db_path = self._config_dir / self.DB_FILE

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def db_path(self) -> Path:
        return self._db_path

    def exists(self) -> bool:
        """Check if configuration exists."""
        return self._config_path.exists() and self._key_path.exists()

    def load(self) -> AgentConfig:
        """Load configuration from file. Raises ConfigError if not found."""
        if not self._config_path.exists():
            raise ConfigError(
                f"Config not found at {self._config_path}. Run 'swarm init' first."
            )
        if not self._key_path.exists():
            raise ConfigError(
                f"Key file not found at {self._key_path}. Run 'swarm init' first."
            )

        with open(self._config_path) as f:
            data = yaml.safe_load(f)

        if not data or "agent_id" not in data or "endpoint" not in data:
            raise ConfigError("Invalid config: missing agent_id or endpoint")

        with open(self._key_path, "rb") as f:
            key_bytes = f.read()

        try:
            private_key = Ed25519PrivateKey.from_private_bytes(key_bytes)
        except Exception as e:
            raise ConfigError(f"Invalid key file: {e}") from e

        return AgentConfig(
            agent_id=data["agent_id"],
            endpoint=data["endpoint"],
            private_key=private_key,
            db_path=self._db_path,
        )

    def save(
        self, agent_id: str, endpoint: str, private_key: Ed25519PrivateKey
    ) -> None:
        """Save configuration to file."""
        self._config_dir.mkdir(parents=True, exist_ok=True)

        config_data = {"agent_id": agent_id, "endpoint": endpoint}

        with open(self._config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)

        key_bytes = private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        with open(self._key_path, "wb") as f:
            f.write(key_bytes)

        self._key_path.chmod(0o600)

    def get_public_key_base64(self) -> str:
        """Get public key as base64 string from saved config."""
        config = self.load()
        pub_bytes = config.private_key.public_key().public_bytes(
            Encoding.Raw,
            format=__import__(
                "cryptography.hazmat.primitives.serialization",
                fromlist=["PublicFormat"],
            ).PublicFormat.Raw,
        )
        return base64.b64encode(pub_bytes).decode("utf-8")
