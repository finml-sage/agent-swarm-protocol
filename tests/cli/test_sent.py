"""Tests for swarm sent command."""

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.cli.utils.config import ConfigManager
from src.state import DatabaseManager, OutboxMessage, OutboxRepository

runner = CliRunner()

SWARM_ID = "716a4150-ab9d-4b54-a2a8-f2b7c607c21e"


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


async def _insert_outbox_message(
    db_path: Path, swarm_id: str, recipient: str, content: str, msg_id: str,
) -> None:
    """Insert a test message into the outbox table."""
    db = DatabaseManager(db_path)
    await db.initialize()
    msg = OutboxMessage(
        message_id=msg_id,
        swarm_id=swarm_id,
        recipient_id=recipient,
        message_type="message",
        content=content,
        sent_at=datetime.now(timezone.utc),
    )
    async with db.connection() as conn:
        repo = OutboxRepository(conn)
        await repo.insert(msg)


class TestSentValidation:
    """Validation tests for swarm sent command."""

    def test_sent_without_init_exits_1(self, monkeypatch):
        """Sent without agent init exits with code 1."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["sent", "-s", SWARM_ID])

            assert result.exit_code == 1
            assert "swarm init" in result.stdout.lower()

    def test_sent_invalid_swarm_id_exits_2(self, monkeypatch):
        """Sent with invalid UUID exits with code 2."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(app, ["sent", "-s", "not-a-uuid"])

            assert result.exit_code == 2


class TestSentList:
    """List mode tests for swarm sent command."""

    def test_list_empty(self, monkeypatch):
        """Empty outbox shows warning message."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["sent", "-s", SWARM_ID])

            assert result.exit_code == 0
            assert "No sent messages found" in result.stdout

    def test_list_with_messages(self, monkeypatch):
        """Outbox with messages displays table."""
        import asyncio

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            db_path = config_dir / "swarm.db"
            asyncio.run(
                _insert_outbox_message(
                    db_path, SWARM_ID, "recipient-agent", "Hello!", "msg-001",
                )
            )

            result = runner.invoke(app, ["sent", "-s", SWARM_ID])

            assert result.exit_code == 0
            assert "recipient-agent" in result.stdout
            assert "Sent Messages (1)" in result.stdout

    def test_list_json_output(self, monkeypatch):
        """Sent --json outputs valid JSON."""
        import asyncio

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            db_path = config_dir / "swarm.db"
            asyncio.run(
                _insert_outbox_message(
                    db_path, SWARM_ID, "recipient-agent", "Test msg", "msg-002",
                )
            )

            result = runner.invoke(app, ["sent", "-s", SWARM_ID, "--json"])

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["swarm_id"] == SWARM_ID
            assert data["count"] == 1
            assert len(data["messages"]) == 1
            assert data["messages"][0]["recipient_id"] == "recipient-agent"

    def test_list_empty_json_output(self, monkeypatch):
        """Empty outbox with --json outputs valid JSON."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["sent", "-s", SWARM_ID, "--json"])

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["count"] == 0
            assert data["messages"] == []

    def test_list_respects_limit(self, monkeypatch):
        """Sent --limit restricts the number of messages returned."""
        import asyncio

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            db_path = config_dir / "swarm.db"
            for i in range(5):
                asyncio.run(
                    _insert_outbox_message(
                        db_path, SWARM_ID, "agent", f"msg {i}", f"msg-{i:03d}",
                    )
                )

            result = runner.invoke(
                app, ["sent", "-s", SWARM_ID, "--limit", "2", "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["count"] == 2


class TestSentCount:
    """Count mode tests for swarm sent command."""

    def test_count_zero(self, monkeypatch):
        """Count with empty outbox shows zero."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            result = runner.invoke(app, ["sent", "-s", SWARM_ID, "--count"])

            assert result.exit_code == 0
            assert "0" in result.stdout

    def test_count_with_messages(self, monkeypatch):
        """Count reflects inserted messages."""
        import asyncio

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            db_path = config_dir / "swarm.db"
            asyncio.run(
                _insert_outbox_message(
                    db_path, SWARM_ID, "agent", "hello", "msg-cnt-001",
                )
            )

            result = runner.invoke(app, ["sent", "-s", SWARM_ID, "--count"])

            assert result.exit_code == 0
            assert "1" in result.stdout

    def test_count_json(self, monkeypatch):
        """Count --json outputs valid JSON with totals."""
        import asyncio

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            _init_agent(monkeypatch, config_dir)

            db_path = config_dir / "swarm.db"
            asyncio.run(
                _insert_outbox_message(
                    db_path, SWARM_ID, "agent", "hello", "msg-cnt-002",
                )
            )

            result = runner.invoke(
                app, ["sent", "-s", SWARM_ID, "--count", "--json"]
            )

            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["swarm_id"] == SWARM_ID
            assert data["total"] == 1
            assert data["sent"] == 1

    def test_count_without_init_exits_1(self, monkeypatch):
        """Count without agent init exits with code 1."""
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "swarm"
            monkeypatch.setattr(ConfigManager, "DEFAULT_DIR", config_dir)

            result = runner.invoke(
                app, ["sent", "-s", SWARM_ID, "--count"]
            )

            assert result.exit_code == 1
            assert "swarm init" in result.stdout.lower()
