"""Integration tests: messages received via HTTP are persisted to SQLite."""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.config import (
    AgentConfig, RateLimitConfig, ServerConfig, WakeConfig, WakeEndpointConfig,
)
from src.state.database import DatabaseManager
from src.state.repositories.messages import MessageRepository


def _make_config(tmp_path: Path) -> ServerConfig:
    """Build a minimal ServerConfig pointing at a temp database.

    Wake trigger and endpoint are explicitly disabled so persistence
    tests run in isolation without network calls.
    """
    return ServerConfig(
        agent=AgentConfig(
            agent_id="test-agent-001",
            endpoint="https://test.example.com",
            public_key="dGVzdC1wdWJsaWMta2V5LWJhc2U2NA==",
            protocol_version="0.1.0",
        ),
        rate_limit=RateLimitConfig(messages_per_minute=100),
        db_path=tmp_path / "persist.db",
        wake=WakeConfig(enabled=False, endpoint=""),
        wake_endpoint=WakeEndpointConfig(enabled=False),
    )


def _valid_message(message_id: str = "550e8400-e29b-41d4-a716-446655440000") -> dict:
    """Return a well-formed message payload."""
    return {
        "protocol_version": "0.1.0",
        "message_id": message_id,
        "timestamp": "2026-02-05T14:30:00.000Z",
        "sender": {
            "agent_id": "sender-agent-123",
            "endpoint": "https://sender.example.com",
        },
        "recipient": "test-agent-001",
        "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
        "type": "message",
        "content": "Hello from integration test",
        "signature": "dGVzdC1zaWduYXR1cmUtYmFzZTY0",
    }


class TestMessagePersistence:
    """Verify that POST /swarm/message stores rows in message_queue."""

    def test_message_persisted_to_sqlite(self, tmp_path: Path) -> None:
        """A valid message is stored in the message_queue table."""
        config = _make_config(tmp_path)
        msg = _valid_message()

        with TestClient(create_app(config)) as client:
            response = client.post(
                "/swarm/message",
                json=msg,
                headers={"Content-Type": "application/json"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "queued"

        # Read back from the database directly
        async def _verify() -> None:
            db = DatabaseManager(config.db_path)
            await db.initialize()
            async with db.connection() as conn:
                repo = MessageRepository(conn)
                stored = await repo.get_by_id(msg["message_id"])
            assert stored is not None
            assert stored.message_id == msg["message_id"]
            assert stored.swarm_id == msg["swarm_id"]
            assert stored.sender_id == msg["sender"]["agent_id"]
            assert stored.message_type == msg["type"]
            # content stores the full JSON payload
            payload = json.loads(stored.content)
            assert payload["content"] == "Hello from integration test"
            assert payload["signature"] == msg["signature"]
            await db.close()

        asyncio.run(_verify())

    def test_duplicate_message_id_is_idempotent(self, tmp_path: Path) -> None:
        """Posting the same message_id twice returns 200 both times."""
        config = _make_config(tmp_path)
        msg = _valid_message()

        with TestClient(create_app(config)) as client:
            r1 = client.post(
                "/swarm/message",
                json=msg,
                headers={"Content-Type": "application/json"},
            )
            r2 = client.post(
                "/swarm/message",
                json=msg,
                headers={"Content-Type": "application/json"},
            )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["status"] == "queued"
        assert r2.json()["status"] == "queued"

    def test_multiple_distinct_messages_persisted(self, tmp_path: Path) -> None:
        """Multiple messages with distinct IDs are all persisted."""
        config = _make_config(tmp_path)
        ids = [
            "550e8400-e29b-41d4-a716-446655440001",
            "550e8400-e29b-41d4-a716-446655440002",
            "550e8400-e29b-41d4-a716-446655440003",
        ]

        with TestClient(create_app(config)) as client:
            for mid in ids:
                r = client.post(
                    "/swarm/message",
                    json=_valid_message(mid),
                    headers={"Content-Type": "application/json"},
                )
                assert r.status_code == 200

        async def _verify() -> None:
            db = DatabaseManager(config.db_path)
            await db.initialize()
            async with db.connection() as conn:
                repo = MessageRepository(conn)
                for mid in ids:
                    stored = await repo.get_by_id(mid)
                    assert stored is not None, f"Message {mid} not found in DB"
                count = await repo.get_pending_count(
                    "660e8400-e29b-41d4-a716-446655440001"
                )
            assert count == 3
            await db.close()

        asyncio.run(_verify())
