"""Tests for the /api/messages inbox endpoints (issue #151).

These endpoints expose the server-side message_queue to CLI clients,
replacing the broken pattern of reading the always-empty client DB.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.config import (
    AgentConfig,
    ServerConfig,
    WakeConfig,
    WakeEndpointConfig,
)
from src.state.database import DatabaseManager
from src.state.models.message import MessageStatus, QueuedMessage
from src.state.repositories.messages import MessageRepository

SWARM_ID = "716a4150-ab9d-4b54-a2a8-f2b7c607c21e"
MSG_ID_1 = "aaa00000-0000-0000-0000-000000000001"
MSG_ID_2 = "aaa00000-0000-0000-0000-000000000002"
MSG_ID_3 = "aaa00000-0000-0000-0000-000000000003"

_NO_WAKE = WakeConfig(enabled=False, endpoint="")
_NO_WAKE_EP = WakeEndpointConfig(enabled=False)


def _make_config(agent_config: AgentConfig, db_path: Path) -> ServerConfig:
    return ServerConfig(
        agent=agent_config,
        db_path=db_path,
        wake=_NO_WAKE,
        wake_endpoint=_NO_WAKE_EP,
    )


def _seed_messages(db_path: Path) -> None:
    """Seed three messages into the server DB: 2 pending, 1 completed."""

    async def _seed() -> None:
        db = DatabaseManager(db_path)
        await db.initialize()
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.enqueue(
                QueuedMessage(
                    message_id=MSG_ID_1,
                    swarm_id=SWARM_ID,
                    sender_id="agent-alpha",
                    message_type="message",
                    content='{"text": "Hello from alpha"}',
                    received_at=datetime(2026, 2, 9, 10, 0, 0, tzinfo=timezone.utc),
                    status=MessageStatus.PENDING,
                )
            )
            await repo.enqueue(
                QueuedMessage(
                    message_id=MSG_ID_2,
                    swarm_id=SWARM_ID,
                    sender_id="agent-beta",
                    message_type="message",
                    content='{"text": "Hello from beta"}',
                    received_at=datetime(2026, 2, 9, 11, 0, 0, tzinfo=timezone.utc),
                    status=MessageStatus.PENDING,
                )
            )
            await repo.enqueue(
                QueuedMessage(
                    message_id=MSG_ID_3,
                    swarm_id=SWARM_ID,
                    sender_id="agent-gamma",
                    message_type="message",
                    content='{"text": "Hello from gamma"}',
                    received_at=datetime(2026, 2, 9, 12, 0, 0, tzinfo=timezone.utc),
                    status=MessageStatus.PENDING,
                )
            )
            # Mark the third message as completed
            await repo.complete(MSG_ID_3)
        await db.close()

    asyncio.run(_seed())


# ---------------------------------------------------------------------------
# GET /api/messages
# ---------------------------------------------------------------------------


class TestListMessages:
    """Tests for GET /api/messages."""

    def test_list_pending_messages(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Returns only pending messages by default."""
        db_path = tmp_path / "inbox_list.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get("/api/messages", params={"swarm_id": SWARM_ID})

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert all(m["status"] == "pending" for m in data["messages"])

    def test_list_completed_messages(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Filtering by completed returns only completed messages."""
        db_path = tmp_path / "inbox_completed.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get(
                "/api/messages",
                params={"swarm_id": SWARM_ID, "status": "completed"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["messages"][0]["sender_id"] == "agent-gamma"

    def test_list_all_messages(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Status=all returns messages of every status."""
        db_path = tmp_path / "inbox_all.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get(
                "/api/messages",
                params={"swarm_id": SWARM_ID, "status": "all"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3

    def test_list_respects_limit(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Limit parameter caps the number of returned messages."""
        db_path = tmp_path / "inbox_limit.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get(
                "/api/messages",
                params={"swarm_id": SWARM_ID, "status": "all", "limit": 1},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_list_empty_swarm(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Non-existent swarm returns empty list."""
        db_path = tmp_path / "inbox_empty.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get(
                "/api/messages",
                params={"swarm_id": "00000000-0000-0000-0000-000000000000"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["messages"] == []

    def test_list_invalid_status(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Invalid status filter returns 400."""
        db_path = tmp_path / "inbox_badstatus.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get(
                "/api/messages",
                params={"swarm_id": SWARM_ID, "status": "bogus"},
            )

        assert resp.status_code == 400
        assert "Invalid status" in resp.json()["error"]

    def test_list_requires_swarm_id(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Missing swarm_id returns 422 (FastAPI validation)."""
        db_path = tmp_path / "inbox_noswarm.db"
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get("/api/messages")

        assert resp.status_code == 422

    def test_list_message_fields(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Each message has the expected fields."""
        db_path = tmp_path / "inbox_fields.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get(
                "/api/messages",
                params={"swarm_id": SWARM_ID, "status": "all", "limit": 1},
            )

        msg = resp.json()["messages"][0]
        assert "message_id" in msg
        assert "swarm_id" in msg
        assert "sender_id" in msg
        assert "message_type" in msg
        assert "status" in msg
        assert "received_at" in msg
        assert "content_preview" in msg

    def test_content_preview_truncated(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Content preview is capped at 200 characters."""
        db_path = tmp_path / "inbox_truncate.db"

        async def _seed_long():
            db = DatabaseManager(db_path)
            await db.initialize()
            async with db.connection() as conn:
                repo = MessageRepository(conn)
                await repo.enqueue(
                    QueuedMessage(
                        message_id=MSG_ID_1,
                        swarm_id=SWARM_ID,
                        sender_id="verbose-agent",
                        message_type="message",
                        content="x" * 500,
                        received_at=datetime(2026, 2, 9, 10, 0, tzinfo=timezone.utc),
                    )
                )
            await db.close()

        asyncio.run(_seed_long())
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get("/api/messages", params={"swarm_id": SWARM_ID})

        msg = resp.json()["messages"][0]
        assert len(msg["content_preview"]) == 200


# ---------------------------------------------------------------------------
# GET /api/messages/count
# ---------------------------------------------------------------------------


class TestMessageCount:
    """Tests for GET /api/messages/count."""

    def test_count_with_seeded_data(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Returns correct counts per status."""
        db_path = tmp_path / "inbox_count.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get(
                "/api/messages/count", params={"swarm_id": SWARM_ID},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending"] == 2
        assert data["completed"] == 1
        assert data["failed"] == 0
        assert data["total"] == 3

    def test_count_empty_swarm(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Empty swarm returns all-zero counts."""
        db_path = tmp_path / "inbox_count_empty.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get(
                "/api/messages/count",
                params={"swarm_id": "00000000-0000-0000-0000-000000000000"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_count_requires_swarm_id(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Missing swarm_id returns 422."""
        db_path = tmp_path / "inbox_count_noswarm.db"
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.get("/api/messages/count")

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/messages/{message_id}/ack
# ---------------------------------------------------------------------------


class TestAckMessage:
    """Tests for POST /api/messages/{message_id}/ack."""

    def test_ack_pending_message(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Acknowledging a pending message marks it as completed."""
        db_path = tmp_path / "inbox_ack.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            resp = c.post(f"/api/messages/{MSG_ID_1}/ack")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "acked"
        assert data["message_id"] == MSG_ID_1

    def test_ack_unknown_message(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Acknowledging a non-existent message returns not_found."""
        db_path = tmp_path / "inbox_ack_unknown.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)
        fake_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"

        with TestClient(create_app(config)) as c:
            resp = c.post(f"/api/messages/{fake_id}/ack")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_found"
        assert data["message_id"] == fake_id

    def test_ack_changes_status_in_db(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """After ack, message no longer appears in pending list."""
        db_path = tmp_path / "inbox_ack_verify.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            # Ack one of the pending messages
            ack_resp = c.post(f"/api/messages/{MSG_ID_1}/ack")
            assert ack_resp.json()["status"] == "acked"

            # List pending -- should now have only 1
            list_resp = c.get(
                "/api/messages",
                params={"swarm_id": SWARM_ID, "status": "pending"},
            )

        assert list_resp.json()["count"] == 1
        remaining_ids = [m["message_id"] for m in list_resp.json()["messages"]]
        assert MSG_ID_1 not in remaining_ids

    def test_ack_idempotent(
        self, agent_config: AgentConfig, tmp_path: Path,
    ) -> None:
        """Acknowledging an already-completed message still returns acked."""
        db_path = tmp_path / "inbox_ack_idempotent.db"
        _seed_messages(db_path)
        config = _make_config(agent_config, db_path)

        with TestClient(create_app(config)) as c:
            # MSG_ID_3 is already completed from seeding
            resp = c.post(f"/api/messages/{MSG_ID_3}/ack")

        # MessageRepository.complete() updates status even if already completed
        # (UPDATE WHERE message_id = ?), so rowcount > 0 => "acked"
        assert resp.status_code == 200
        assert resp.json()["status"] == "acked"
