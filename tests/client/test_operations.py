"""Tests for swarm operations."""

from uuid import UUID

from src.client.crypto import generate_keypair, public_key_to_base64
from src.client.operations import create_swarm


class TestCreateSwarm:
    def test_creates_swarm_with_master(self) -> None:
        _, pub = generate_keypair()
        pk_b64 = public_key_to_base64(pub)
        s = create_swarm("Test", "master", "https://m.com", pk_b64)
        assert s["name"] == "Test"
        assert s["master"] == "master"
        assert len(s["members"]) == 1
        assert s["members"][0]["agent_id"] == "master"
        assert s["members"][0]["public_key"] == pk_b64

    def test_creates_unique_swarm_id(self) -> None:
        _, pub = generate_keypair()
        pk_b64 = public_key_to_base64(pub)
        s1 = create_swarm("S1", "m", "https://m.com", pk_b64)
        s2 = create_swarm("S2", "m", "https://m.com", pk_b64)
        assert s1["swarm_id"] != s2["swarm_id"]

    def test_default_settings_restrict_invites(self) -> None:
        _, pub = generate_keypair()
        s = create_swarm("Test", "m", "https://m.com", public_key_to_base64(pub))
        assert s["settings"]["allow_member_invite"] is False
        assert s["settings"]["require_approval"] is False

    def test_custom_settings_applied(self) -> None:
        _, pub = generate_keypair()
        pk_b64 = public_key_to_base64(pub)
        s = create_swarm("Test", "m", "https://m.com", pk_b64, True, True)
        assert s["settings"]["allow_member_invite"] is True
        assert s["settings"]["require_approval"] is True

    def test_joined_at_is_set(self) -> None:
        _, pub = generate_keypair()
        s = create_swarm("Test", "m", "https://m.com", public_key_to_base64(pub))
        assert s["joined_at"].endswith("Z")
        assert s["members"][0]["joined_at"].endswith("Z")

    def test_swarm_id_is_valid_uuid(self) -> None:
        _, pub = generate_keypair()
        s = create_swarm("Test", "m", "https://m.com", public_key_to_base64(pub))
        assert str(UUID(s["swarm_id"])) == s["swarm_id"]
