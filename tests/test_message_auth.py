"""End-to-end authentication tests for inbound swarm messages."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from src.client.crypto import public_key_to_base64, sign_message
from src.server.app import create_app
from src.server.config import (
    AgentConfig,
    RateLimitConfig,
    ServerConfig,
    WakeConfig,
    WakeEndpointConfig,
)
from src.state.database import DatabaseManager
from src.state.models.member import SwarmMember, SwarmMembership
from src.state.repositories.inbox import InboxRepository
from src.state.repositories.membership import MembershipRepository

LOCAL_AGENT_ID = "receiver-agent"
SENDER_AGENT_ID = "sender-agent"
SENDER_ENDPOINT = "https://sender.example.com/swarm"
SWARM_ID = "660e8400-e29b-41d4-a716-446655440001"
MESSAGE_ID = "550e8400-e29b-41d4-a716-446655440000"
TIMESTAMP = "2026-02-05T14:30:00.000Z"


def _config(db_path: Path) -> ServerConfig:
    return ServerConfig(
        agent=AgentConfig(
            agent_id=LOCAL_AGENT_ID,
            endpoint="https://receiver.example.com",
            public_key="not-used-for-inbound-verification",
            protocol_version="0.1.0",
        ),
        rate_limit=RateLimitConfig(messages_per_minute=100),
        db_path=db_path,
        wake=WakeConfig(enabled=False, endpoint=""),
        wake_endpoint=WakeEndpointConfig(enabled=False),
    )


def _seed_sender(
    db_path: Path,
    private_key: Ed25519PrivateKey,
    *,
    endpoint: str = SENDER_ENDPOINT,
    public_key: str | None = None,
) -> None:
    async def _seed() -> None:
        db = DatabaseManager(db_path)
        await db.initialize()
        member = SwarmMember(
            agent_id=SENDER_AGENT_ID,
            endpoint=endpoint,
            public_key=public_key
            or public_key_to_base64(private_key.public_key()),
            joined_at=datetime.now(timezone.utc),
        )
        membership = SwarmMembership(
            swarm_id=SWARM_ID,
            name="Authentication Test Swarm",
            master=SENDER_AGENT_ID,
            members=(member,),
            joined_at=datetime.now(timezone.utc),
        )
        async with db.connection() as conn:
            await MembershipRepository(conn).create_swarm(membership)
        await db.close()

    asyncio.run(_seed())


def _signed_message(
    private_key: Ed25519PrivateKey,
    *,
    recipient: str = LOCAL_AGENT_ID,
    endpoint: str = SENDER_ENDPOINT,
    content: str = "authenticated test message",
    timestamp: str = TIMESTAMP,
) -> dict:
    parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    signature = sign_message(
        private_key,
        UUID(MESSAGE_ID),
        parsed_timestamp,
        UUID(SWARM_ID),
        recipient,
        "message",
        content,
    )
    return {
        "protocol_version": "0.1.0",
        "message_id": MESSAGE_ID,
        "timestamp": timestamp,
        "sender": {
            "agent_id": SENDER_AGENT_ID,
            "endpoint": endpoint,
        },
        "recipient": recipient,
        "swarm_id": SWARM_ID,
        "type": "message",
        "content": content,
        "signature": signature,
    }


def _headers(
    *,
    sender: str = SENDER_AGENT_ID,
    protocol: str = "0.1.0",
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Agent-ID": sender,
        "X-Swarm-Protocol": protocol,
    }


def _post(db_path: Path, message: dict, headers: dict[str, str]):
    with TestClient(create_app(_config(db_path))) as client:
        return client.post("/swarm/message", json=message, headers=headers)


def test_accepts_registered_sender_with_valid_signature(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "valid.db"
    _seed_sender(db_path, key)

    response = _post(db_path, _signed_message(key), _headers())

    assert response.status_code == 200
    assert response.json() == {"status": "queued", "message_id": MESSAGE_ID}


def test_rejects_sender_header_mismatch(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "sender-header.db"
    _seed_sender(db_path, key)

    response = _post(
        db_path,
        _signed_message(key),
        _headers(sender="different-agent"),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_AUTHORIZED"


def test_rejects_protocol_header_mismatch(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "protocol-header.db"
    _seed_sender(db_path, key)

    response = _post(
        db_path,
        _signed_message(key),
        _headers(protocol="9.9.9"),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_AUTHORIZED"


def test_rejects_unknown_swarm(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "unknown-swarm.db"

    response = _post(db_path, _signed_message(key), _headers())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SWARM_NOT_FOUND"


def test_rejects_unregistered_sender(tmp_path: Path) -> None:
    registered_key = Ed25519PrivateKey.generate()
    unregistered_key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "unregistered.db"
    _seed_sender(db_path, registered_key)
    message = _signed_message(unregistered_key)
    message["sender"]["agent_id"] = "unregistered-agent"

    response = _post(
        db_path,
        message,
        _headers(sender="unregistered-agent"),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_AUTHORIZED"


def test_rejects_sender_endpoint_mismatch(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "endpoint.db"
    _seed_sender(db_path, key)

    response = _post(
        db_path,
        _signed_message(key, endpoint="https://other.example.com/swarm"),
        _headers(),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_AUTHORIZED"


def test_rejects_message_for_another_recipient(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "recipient.db"
    _seed_sender(db_path, key)

    response = _post(
        db_path,
        _signed_message(key, recipient="another-agent"),
        _headers(),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_AUTHORIZED"


def test_accepts_signed_broadcast(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "broadcast.db"
    _seed_sender(db_path, key)

    response = _post(
        db_path,
        _signed_message(key, recipient="broadcast"),
        _headers(),
    )

    assert response.status_code == 200


def test_rejects_tampered_content_without_persisting(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "tampered.db"
    _seed_sender(db_path, key)
    message = _signed_message(key)
    message["content"] = "tampered after signing"

    response = _post(db_path, message, _headers())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_SIGNATURE"

    async def _verify_absent() -> None:
        db = DatabaseManager(db_path)
        await db.initialize()
        async with db.connection() as conn:
            stored = await InboxRepository(conn).get_by_id(MESSAGE_ID)
        await db.close()
        assert stored is None

    asyncio.run(_verify_absent())


def test_rejects_invalid_registered_public_key(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "invalid-public-key.db"
    _seed_sender(db_path, key, public_key="invalid-public-key")

    response = _post(db_path, _signed_message(key), _headers())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"


def test_rejects_timestamp_without_timezone(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "timestamp.db"
    _seed_sender(db_path, key)
    message = _signed_message(key)
    message["timestamp"] = "2026-02-05T14:30:00.000"

    response = _post(db_path, message, _headers())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FORMAT"


def test_duplicate_does_not_repeat_dispatch_or_wake(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    db_path = tmp_path / "duplicate.db"
    _seed_sender(db_path, key)
    app = create_app(_config(db_path))
    wake_trigger = MagicMock()
    wake_trigger.process_message = AsyncMock()

    with patch(
        "src.server.routes.message.dispatch_system_message",
        new_callable=AsyncMock,
    ) as dispatch:
        with TestClient(app) as client:
            app.state.wake_trigger = wake_trigger
            first = client.post(
                "/swarm/message",
                json=_signed_message(key),
                headers=_headers(),
            )
            second = client.post(
                "/swarm/message",
                json=_signed_message(key),
                headers=_headers(),
            )

    assert first.status_code == 200
    assert second.status_code == 200
    dispatch.assert_awaited_once()
    wake_trigger.process_message.assert_awaited_once()
