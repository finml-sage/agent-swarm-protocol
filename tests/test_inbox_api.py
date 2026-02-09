"""Tests for the /api/inbox and /api/outbox endpoints (issue #155).

Tests cover the new inbox REST API with status management (unread, read,
archived, deleted) and the outbox listing endpoints.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.config import AgentConfig, ServerConfig, WakeConfig, WakeEndpointConfig
from src.state.database import DatabaseManager
from src.state.models.inbox import InboxMessage, InboxStatus
from src.state.models.outbox import OutboxMessage, OutboxStatus
from src.state.repositories.inbox import InboxRepository
from src.state.repositories.outbox import OutboxRepository

SWARM_ID = "716a4150-ab9d-4b54-a2a8-f2b7c607c21e"
MSG_1 = "aaa00000-0000-0000-0000-000000000001"
MSG_2 = "aaa00000-0000-0000-0000-000000000002"
MSG_3 = "aaa00000-0000-0000-0000-000000000003"

_NO_WAKE = WakeConfig(enabled=False, endpoint="")
_NO_WAKE_EP = WakeEndpointConfig(enabled=False)


def _cfg(agent_config: AgentConfig, db_path: Path) -> ServerConfig:
    return ServerConfig(agent=agent_config, db_path=db_path, wake=_NO_WAKE, wake_endpoint=_NO_WAKE_EP)


def _seed_inbox(db_path: Path) -> None:
    """Seed three inbox messages: 2 unread, 1 read."""
    async def _seed() -> None:
        db = DatabaseManager(db_path)
        await db.initialize()
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(InboxMessage(
                message_id=MSG_1, swarm_id=SWARM_ID, sender_id="alpha",
                message_type="message", content='{"text":"hello from alpha"}',
                received_at=datetime(2026, 2, 9, 10, 0, 0, tzinfo=timezone.utc),
            ))
            await repo.insert(InboxMessage(
                message_id=MSG_2, swarm_id=SWARM_ID, sender_id="beta",
                message_type="message", content='{"text":"hello from beta"}',
                received_at=datetime(2026, 2, 9, 11, 0, 0, tzinfo=timezone.utc),
            ))
            await repo.insert(InboxMessage(
                message_id=MSG_3, swarm_id=SWARM_ID, sender_id="gamma",
                message_type="message", content='{"text":"hello from gamma"}',
                received_at=datetime(2026, 2, 9, 12, 0, 0, tzinfo=timezone.utc),
            ))
            await repo.mark_read(MSG_3)
        await db.close()
    asyncio.run(_seed())


class TestInboxList:
    def test_list_unread_default(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "list.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox", params={"swarm_id": SWARM_ID})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert all(m["status"] == "unread" for m in data["messages"])

    def test_list_read(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "list_read.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox", params={"swarm_id": SWARM_ID, "status": "read"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert resp.json()["messages"][0]["sender_id"] == "gamma"

    def test_list_all(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "list_all.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox", params={"swarm_id": SWARM_ID, "status": "all"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 3

    def test_list_invalid_status(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "list_bad.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox", params={"status": "bogus"})
        assert resp.status_code == 400

    def test_list_respects_limit(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "list_limit.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox", params={"swarm_id": SWARM_ID, "status": "all", "limit": 1})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_list_empty_swarm(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "list_empty.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox", params={"swarm_id": "00000000-0000-0000-0000-000000000000"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_message_fields(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "list_fields.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox", params={"swarm_id": SWARM_ID, "status": "all", "limit": 1})
        msg = resp.json()["messages"][0]
        for field in ("message_id", "swarm_id", "sender_id", "message_type", "status", "received_at", "content_preview"):
            assert field in msg

    def test_list_by_sender(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        """sender_id filter returns only messages from that sender."""
        db_path = tmp_path / "list_sender.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox", params={"sender_id": "alpha", "status": "all"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["messages"][0]["sender_id"] == "alpha"


class TestInboxCount:
    def test_count(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "count.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox/count", params={"swarm_id": SWARM_ID})
        assert resp.status_code == 200
        data = resp.json()
        assert data["unread"] == 2
        assert data["read"] == 1
        assert data["archived"] == 0
        assert data["deleted"] == 0
        assert data["total"] == 3

    def test_count_empty(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "count_empty.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox/count", params={"swarm_id": "00000000-0000-0000-0000-000000000000"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_count_without_swarm_id(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        """Count without swarm_id returns cross-swarm totals."""
        db_path = tmp_path / "count_no_swarm.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox/count")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3


class TestInboxGetMessage:
    def test_get_auto_marks_read(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "get_auto.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get(f"/api/inbox/{MSG_1}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["message_id"] == MSG_1
        assert data["status"] == "read"
        assert data["read_at"] is not None

    def test_get_already_read(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "get_read.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get(f"/api/inbox/{MSG_3}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "read"

    def test_get_not_found(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "get_404.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/inbox/ffffffff-ffff-ffff-ffff-ffffffffffff")
        assert resp.status_code == 404


class TestInboxMarkRead:
    def test_mark_read(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "mark_read.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post(f"/api/inbox/{MSG_1}/read")
        assert resp.status_code == 200
        assert resp.json()["status"] == "read"

    def test_mark_read_idempotent(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "mark_read_idem.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            c.post(f"/api/inbox/{MSG_1}/read")
            resp = c.post(f"/api/inbox/{MSG_1}/read")
        assert resp.status_code == 200

    def test_mark_read_not_found(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "mark_read_404.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post("/api/inbox/ffffffff-ffff-ffff-ffff-ffffffffffff/read")
        assert resp.status_code == 404


class TestInboxArchive:
    def test_archive(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "archive.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post(f"/api/inbox/{MSG_1}/archive")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    def test_archive_not_found(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "archive_404.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post("/api/inbox/ffffffff-ffff-ffff-ffff-ffffffffffff/archive")
        assert resp.status_code == 404


class TestInboxDelete:
    def test_delete(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "delete.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post(f"/api/inbox/{MSG_1}/delete")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_not_found(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "delete_404.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post("/api/inbox/ffffffff-ffff-ffff-ffff-ffffffffffff/delete")
        assert resp.status_code == 404

    def test_delete_removes_from_list(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "delete_list.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            c.post(f"/api/inbox/{MSG_1}/delete")
            resp = c.get("/api/inbox", params={"swarm_id": SWARM_ID, "status": "all"})
        assert resp.json()["count"] == 2
        ids = [m["message_id"] for m in resp.json()["messages"]]
        assert MSG_1 not in ids


class TestInboxBatch:
    def test_batch_read(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "batch_read.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post("/api/inbox/batch", json={"message_ids": [MSG_1, MSG_2], "action": "read"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "read"
        assert data["updated"] == 2
        assert data["total"] == 2

    def test_batch_archive(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "batch_archive.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post("/api/inbox/batch", json={"message_ids": [MSG_1], "action": "archive"})
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1

    def test_batch_delete(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "batch_delete.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post("/api/inbox/batch", json={"message_ids": [MSG_1, MSG_2, MSG_3], "action": "delete"})
        assert resp.status_code == 200
        assert resp.json()["updated"] == 3

    def test_batch_read_skips_already_read(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        """Batch read with transition guard: MSG_3 is already read, should skip."""
        db_path = tmp_path / "batch_guard.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post("/api/inbox/batch", json={"message_ids": [MSG_1, MSG_3], "action": "read"})
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1  # only MSG_1 (unread->read)

    def test_batch_empty_ids_rejected(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "batch_empty.db"
        _seed_inbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.post("/api/inbox/batch", json={"message_ids": [], "action": "read"})
        assert resp.status_code == 422


class TestMessageReceiveInbox:
    def test_message_goes_to_inbox(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        """POST /swarm/message inserts into inbox table, not message_queue."""
        db_path = tmp_path / "receive.db"
        config = _cfg(agent_config, db_path)
        with TestClient(create_app(config)) as c:
            resp = c.post("/swarm/message", json={
                "protocol_version": "0.1.0",
                "message_id": "550e8400-e29b-41d4-a716-446655440000",
                "timestamp": "2026-02-09T14:30:00.000Z",
                "sender": {"agent_id": "sender-123", "endpoint": "https://sender.example.com"},
                "recipient": "test-agent-001",
                "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
                "type": "message", "content": "Hello",
                "signature": "dGVzdC1zaWduYXR1cmUtYmFzZTY0",
            }, headers={"Content-Type": "application/json", "X-Agent-ID": "sender-123"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

        # Verify it is in the inbox table
        async def _check() -> None:
            db = DatabaseManager(db_path)
            await db.initialize()
            async with db.connection() as conn:
                repo = InboxRepository(conn)
                msg = await repo.get_by_id("550e8400-e29b-41d4-a716-446655440000")
                assert msg is not None
                assert msg.status == InboxStatus.UNREAD
                assert msg.sender_id == "sender-123"
            await db.close()
        asyncio.run(_check())

    def test_duplicate_message_idempotent(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        """Re-posting same message_id does not raise an error."""
        db_path = tmp_path / "dup.db"
        config = _cfg(agent_config, db_path)
        msg = {
            "protocol_version": "0.1.0",
            "message_id": "550e8400-e29b-41d4-a716-446655440000",
            "timestamp": "2026-02-09T14:30:00.000Z",
            "sender": {"agent_id": "sender-123", "endpoint": "https://sender.example.com"},
            "recipient": "test-agent-001",
            "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
            "type": "message", "content": "Hello",
            "signature": "dGVzdC1zaWduYXR1cmUtYmFzZTY0",
        }
        with TestClient(create_app(config)) as c:
            r1 = c.post("/swarm/message", json=msg, headers={"Content-Type": "application/json", "X-Agent-ID": "x"})
            r2 = c.post("/swarm/message", json=msg, headers={"Content-Type": "application/json", "X-Agent-ID": "x"})
        assert r1.status_code == 200
        assert r2.status_code == 200


def _seed_outbox(db_path: Path) -> None:
    """Seed two outbox messages."""
    async def _seed() -> None:
        db = DatabaseManager(db_path)
        await db.initialize()
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            await repo.insert(OutboxMessage(
                message_id="out-001", swarm_id=SWARM_ID, recipient_id="beta",
                message_type="message", content='{"text":"sent to beta"}',
                sent_at=datetime(2026, 2, 9, 10, 0, 0, tzinfo=timezone.utc),
            ))
            await repo.insert(OutboxMessage(
                message_id="out-002", swarm_id=SWARM_ID, recipient_id="gamma",
                message_type="message", content='{"text":"sent to gamma"}',
                sent_at=datetime(2026, 2, 9, 11, 0, 0, tzinfo=timezone.utc),
            ))
        await db.close()
    asyncio.run(_seed())


class TestOutboxList:
    def test_list_sent(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "outbox_list.db"
        _seed_outbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/outbox", params={"swarm_id": SWARM_ID})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_list_empty(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "outbox_empty.db"
        _seed_outbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/outbox", params={"swarm_id": "00000000-0000-0000-0000-000000000000"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestOutboxCount:
    def test_count(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "outbox_count.db"
        _seed_outbox(db_path)
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/outbox/count", params={"swarm_id": SWARM_ID})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] == 2
        assert data["total"] == 2

    def test_count_requires_swarm_id(self, agent_config: AgentConfig, tmp_path: Path) -> None:
        db_path = tmp_path / "outbox_count_no_swarm.db"
        with TestClient(create_app(_cfg(agent_config, db_path))) as c:
            resp = c.get("/api/outbox/count")
        assert resp.status_code == 422
