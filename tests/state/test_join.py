"""Tests for join flow state operations."""
import base64
import json
import time

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from src.state import (
    DatabaseManager,
    SwarmMember,
    SwarmMembership,
    SwarmSettings,
)
from src.state.join import (
    AlreadyMemberError,
    ApprovalRequiredError,
    JoinResult,
    SwarmNotFoundError,
    lookup_swarm,
    member_exists,
    validate_and_join,
)
from src.state.token import (
    InviteTokenClaims,
    TokenExpiredError,
    TokenPayloadError,
    TokenSignatureError,
    verify_invite_token,
)


def _b64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_jwt(
    header: dict,
    payload: dict,
    private_key: Ed25519PrivateKey,
) -> str:
    """Create a signed JWT for testing."""
    header_b64 = _b64url_encode(json.dumps(header).encode())
    payload_b64 = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header_b64}.{payload_b64}"
    signature = private_key.sign(signing_input.encode("ascii"))
    sig_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


@pytest.fixture
def ed25519_keypair():
    """Generate an Ed25519 keypair for testing."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes_raw()
    return private_key, public_bytes


@pytest.fixture
def valid_claims():
    """Standard valid JWT claims."""
    return {
        "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
        "master": "master-agent",
        "endpoint": "https://master.example.com/swarm",
        "iat": int(time.time()),
    }


@pytest.fixture
def valid_jwt(ed25519_keypair, valid_claims):
    """A properly signed JWT invite token."""
    private_key, _ = ed25519_keypair
    header = {"alg": "EdDSA", "typ": "JWT"}
    return _make_jwt(header, valid_claims, private_key)


@pytest_asyncio.fixture
async def db():
    """Create a temporary test database."""
    with TemporaryDirectory() as tmpdir:
        manager = DatabaseManager(Path(tmpdir) / "test.db")
        await manager.initialize()
        yield manager


@pytest_asyncio.fixture
async def seeded_db(db):
    """Database with a swarm already created."""
    master_member = SwarmMember(
        agent_id="master-agent",
        endpoint="https://master.example.com/swarm",
        public_key="bWFzdGVyLXB1YmxpYy1rZXk=",
        joined_at=datetime.now(timezone.utc),
    )
    swarm = SwarmMembership(
        swarm_id="550e8400-e29b-41d4-a716-446655440000",
        name="Test Swarm",
        master="master-agent",
        members=(master_member,),
        joined_at=datetime.now(timezone.utc),
        settings=SwarmSettings(
            allow_member_invite=False,
            require_approval=False,
        ),
    )
    async with db.connection() as conn:
        from src.state.repositories.membership import MembershipRepository

        await MembershipRepository(conn).create_swarm(swarm)
    return db


@pytest_asyncio.fixture
async def approval_db(db):
    """Database with a swarm that requires approval."""
    master_member = SwarmMember(
        agent_id="master-agent",
        endpoint="https://master.example.com/swarm",
        public_key="bWFzdGVyLXB1YmxpYy1rZXk=",
        joined_at=datetime.now(timezone.utc),
    )
    swarm = SwarmMembership(
        swarm_id="550e8400-e29b-41d4-a716-446655440000",
        name="Approval Swarm",
        master="master-agent",
        members=(master_member,),
        joined_at=datetime.now(timezone.utc),
        settings=SwarmSettings(
            allow_member_invite=False,
            require_approval=True,
        ),
    )
    async with db.connection() as conn:
        from src.state.repositories.membership import MembershipRepository

        await MembershipRepository(conn).create_swarm(swarm)
    return db


class TestVerifyInviteToken:
    """Tests for Ed25519 JWT token verification."""

    def test_valid_token(self, ed25519_keypair, valid_jwt, valid_claims):
        _, pub_bytes = ed25519_keypair
        claims = verify_invite_token(valid_jwt, pub_bytes)
        assert claims.swarm_id == valid_claims["swarm_id"]
        assert claims.master == valid_claims["master"]
        assert claims.endpoint == valid_claims["endpoint"]
        assert claims.iat == valid_claims["iat"]

    def test_invalid_signature_wrong_key(self, valid_jwt):
        wrong_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        with pytest.raises(TokenSignatureError, match="signature verification"):
            verify_invite_token(valid_jwt, wrong_key)

    def test_tampered_payload(self, ed25519_keypair, valid_jwt):
        _, pub_bytes = ed25519_keypair
        parts = valid_jwt.split(".")
        tampered_payload = _b64url_encode(
            json.dumps({"swarm_id": "evil", "master": "m", "endpoint": "https://e", "iat": 1}).encode()
        )
        tampered = f"{parts[0]}.{tampered_payload}.{parts[2]}"
        with pytest.raises(TokenSignatureError, match="signature verification"):
            verify_invite_token(tampered, pub_bytes)

    def test_expired_token(self, ed25519_keypair):
        private_key, pub_bytes = ed25519_keypair
        header = {"alg": "EdDSA", "typ": "JWT"}
        payload = {
            "swarm_id": "test-swarm",
            "master": "master-agent",
            "endpoint": "https://master.example.com",
            "iat": int(time.time()) - 7200,
            "expires_at": "2020-01-01T00:00:00+00:00",
        }
        token = _make_jwt(header, payload, private_key)
        with pytest.raises(TokenExpiredError, match="expired"):
            verify_invite_token(token, pub_bytes)

    def test_missing_claims(self, ed25519_keypair):
        private_key, pub_bytes = ed25519_keypair
        header = {"alg": "EdDSA", "typ": "JWT"}
        payload = {"swarm_id": "test-swarm"}
        token = _make_jwt(header, payload, private_key)
        with pytest.raises(TokenPayloadError, match="Missing required"):
            verify_invite_token(token, pub_bytes)

    def test_wrong_algorithm(self, ed25519_keypair, valid_claims):
        private_key, pub_bytes = ed25519_keypair
        header = {"alg": "HS256", "typ": "JWT"}
        token = _make_jwt(header, valid_claims, private_key)
        with pytest.raises(TokenPayloadError, match="Unsupported algorithm"):
            verify_invite_token(token, pub_bytes)

    def test_swarm_id_mismatch(self, ed25519_keypair, valid_jwt):
        _, pub_bytes = ed25519_keypair
        with pytest.raises(TokenPayloadError, match="does not match"):
            verify_invite_token(
                valid_jwt, pub_bytes, expected_swarm_id="wrong-id"
            )

    def test_malformed_jwt_structure(self, ed25519_keypair):
        _, pub_bytes = ed25519_keypair
        with pytest.raises(TokenPayloadError, match="expected 3 parts"):
            verify_invite_token("not.a.valid.jwt.token", pub_bytes)

    def test_invalid_public_key_bytes(self, valid_jwt):
        with pytest.raises(TokenSignatureError, match="Invalid public key"):
            verify_invite_token(valid_jwt, b"short")

    def test_token_without_expiry_is_valid(self, ed25519_keypair, valid_jwt):
        _, pub_bytes = ed25519_keypair
        claims = verify_invite_token(valid_jwt, pub_bytes)
        assert claims.expires_at is None


class TestValidateAndJoin:
    """Tests for the full join flow."""

    @pytest.mark.asyncio
    async def test_successful_join(
        self, seeded_db, ed25519_keypair, valid_jwt
    ):
        _, pub_bytes = ed25519_keypair
        async with seeded_db.connection() as conn:
            result = await validate_and_join(
                conn=conn,
                invite_token=valid_jwt,
                master_public_key=pub_bytes,
                agent_id="new-agent",
                agent_endpoint="https://new-agent.example.com/swarm",
                agent_public_key="bmV3LWFnZW50LWtleQ==",
            )
        assert isinstance(result, JoinResult)
        assert result.swarm_id == "550e8400-e29b-41d4-a716-446655440000"
        assert result.swarm_name == "Test Swarm"
        agent_ids = [m.agent_id for m in result.members]
        assert "new-agent" in agent_ids
        assert "master-agent" in agent_ids

    @pytest.mark.asyncio
    async def test_join_swarm_not_found(
        self, db, ed25519_keypair, valid_jwt
    ):
        _, pub_bytes = ed25519_keypair
        async with db.connection() as conn:
            with pytest.raises(SwarmNotFoundError, match="not found"):
                await validate_and_join(
                    conn=conn,
                    invite_token=valid_jwt,
                    master_public_key=pub_bytes,
                    agent_id="new-agent",
                    agent_endpoint="https://new-agent.example.com/swarm",
                    agent_public_key="bmV3LWFnZW50LWtleQ==",
                )

    @pytest.mark.asyncio
    async def test_join_already_member(
        self, seeded_db, ed25519_keypair, valid_jwt
    ):
        _, pub_bytes = ed25519_keypair
        async with seeded_db.connection() as conn:
            with pytest.raises(AlreadyMemberError, match="already a member"):
                await validate_and_join(
                    conn=conn,
                    invite_token=valid_jwt,
                    master_public_key=pub_bytes,
                    agent_id="master-agent",
                    agent_endpoint="https://master.example.com/swarm",
                    agent_public_key="bWFzdGVyLXB1YmxpYy1rZXk=",
                )

    @pytest.mark.asyncio
    async def test_join_requires_approval(
        self, approval_db, ed25519_keypair, valid_jwt
    ):
        _, pub_bytes = ed25519_keypair
        async with approval_db.connection() as conn:
            with pytest.raises(ApprovalRequiredError, match="requires master"):
                await validate_and_join(
                    conn=conn,
                    invite_token=valid_jwt,
                    master_public_key=pub_bytes,
                    agent_id="new-agent",
                    agent_endpoint="https://new-agent.example.com/swarm",
                    agent_public_key="bmV3LWFnZW50LWtleQ==",
                )

    @pytest.mark.asyncio
    async def test_join_invalid_token(self, seeded_db):
        wrong_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        async with seeded_db.connection() as conn:
            with pytest.raises(TokenSignatureError):
                await validate_and_join(
                    conn=conn,
                    invite_token="eyJhbGciOiJFZERTQSJ9.eyJ0ZXN0IjoxfQ.badsig",
                    master_public_key=wrong_key,
                    agent_id="new-agent",
                    agent_endpoint="https://new-agent.example.com/swarm",
                    agent_public_key="bmV3LWFnZW50LWtleQ==",
                )


class TestLookupSwarm:
    """Tests for swarm lookup."""

    @pytest.mark.asyncio
    async def test_lookup_existing(self, seeded_db):
        async with seeded_db.connection() as conn:
            swarm = await lookup_swarm(
                conn, "550e8400-e29b-41d4-a716-446655440000"
            )
        assert swarm.name == "Test Swarm"
        assert swarm.master == "master-agent"

    @pytest.mark.asyncio
    async def test_lookup_missing(self, db):
        async with db.connection() as conn:
            with pytest.raises(SwarmNotFoundError, match="not found"):
                await lookup_swarm(conn, "nonexistent-id")


class TestMemberExists:
    """Tests for membership check."""

    @pytest.mark.asyncio
    async def test_existing_member(self, seeded_db):
        async with seeded_db.connection() as conn:
            exists = await member_exists(
                conn,
                "550e8400-e29b-41d4-a716-446655440000",
                "master-agent",
            )
        assert exists is True

    @pytest.mark.asyncio
    async def test_nonexistent_member(self, seeded_db):
        async with seeded_db.connection() as conn:
            exists = await member_exists(
                conn,
                "550e8400-e29b-41d4-a716-446655440000",
                "unknown-agent",
            )
        assert exists is False

    @pytest.mark.asyncio
    async def test_nonexistent_swarm(self, db):
        async with db.connection() as conn:
            exists = await member_exists(conn, "fake-swarm", "fake-agent")
        assert exists is False
