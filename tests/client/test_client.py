"""Tests for SwarmClient class."""

from uuid import UUID, uuid4

import pytest

from src.client.client import SwarmClient
from src.client.crypto import generate_keypair
from src.client.exceptions import NotMemberError


class TestSwarmClientProperties:
    def test_client_properties(self) -> None:
        priv, _ = generate_keypair()
        c = SwarmClient("test", "https://test.com", priv)
        assert c.agent_id == "test"
        assert c.endpoint == "https://test.com"
        assert len(c.public_key_base64) == 44


class TestSwarmClientSwarmManagement:
    @pytest.mark.asyncio
    async def test_create_swarm_adds_to_internal_state(self) -> None:
        priv, _ = generate_keypair()
        c = SwarmClient("test", "https://test.com", priv)
        s = await c.create_swarm("Test")
        assert c.get_swarm(UUID(s["swarm_id"])) is not None
        assert len(c.list_swarms()) == 1

    @pytest.mark.asyncio
    async def test_create_multiple_swarms(self) -> None:
        priv, _ = generate_keypair()
        c = SwarmClient("test", "https://test.com", priv)
        s1 = await c.create_swarm("S1")
        s2 = await c.create_swarm("S2")
        assert len(c.list_swarms()) == 2
        assert c.get_swarm(UUID(s1["swarm_id"])) is not None
        assert c.get_swarm(UUID(s2["swarm_id"])) is not None

    def test_get_nonexistent_swarm_returns_none(self) -> None:
        priv, _ = generate_keypair()
        c = SwarmClient("test", "https://test.com", priv)
        assert c.get_swarm(uuid4()) is None


class TestSwarmClientInviteGeneration:
    @pytest.mark.asyncio
    async def test_generate_invite_as_master(self) -> None:
        priv, _ = generate_keypair()
        c = SwarmClient("master", "https://m.com", priv)
        s = await c.create_swarm("Test")
        inv = c.generate_invite(UUID(s["swarm_id"]))
        assert inv.startswith("swarm://")
        assert s["swarm_id"] in inv

    def test_generate_invite_not_member_raises_error(self) -> None:
        priv, _ = generate_keypair()
        c = SwarmClient("agent", "https://a.com", priv)
        with pytest.raises(NotMemberError):
            c.generate_invite(uuid4())


class TestSwarmClientAddSwarm:
    def test_add_swarm_tracks_membership(self) -> None:
        priv, _ = generate_keypair()
        c = SwarmClient("test", "https://test.com", priv)
        m = {
            "swarm_id": str(uuid4()),
            "name": "Ext",
            "master": "other",
            "members": [],
            "joined_at": "2026-02-05T14:30:00.000Z",
            "settings": {"allow_member_invite": False, "require_approval": False},
        }
        c.add_swarm(m)
        assert len(c.list_swarms()) == 1
        assert c.get_swarm(UUID(m["swarm_id"])) == m
