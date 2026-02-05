"""Tests for invite token generation and parsing."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.client.crypto import generate_keypair
from src.client.exceptions import TokenError
from src.client.tokens import generate_invite_token, parse_invite_token


class TestGenerateInviteToken:
    def test_generates_valid_url_format(self) -> None:
        priv, _ = generate_keypair()
        sid = uuid4()
        tok = generate_invite_token(priv, sid, "m", "https://m.com")
        assert tok.startswith(f"swarm://{sid}@m.com?token=")

    def test_token_contains_jwt(self) -> None:
        priv, _ = generate_keypair()
        tok = generate_invite_token(priv, uuid4(), "m", "https://m.com")
        assert len(tok.split("?token=")[1].split(".")) == 3

    def test_token_with_expiration(self) -> None:
        priv, pub = generate_keypair()
        exp = datetime.now(timezone.utc) + timedelta(days=1)
        tok = generate_invite_token(priv, uuid4(), "m", "https://m.com", expires_at=exp)
        assert parse_invite_token(tok, pub).get("expires_at") is not None


class TestParseInviteToken:
    def test_parses_valid_token(self) -> None:
        priv, pub = generate_keypair()
        sid = uuid4()
        tok = generate_invite_token(priv, sid, "master", "https://m.com")
        p = parse_invite_token(tok, pub)
        assert p["swarm_id"] == str(sid) and p["master"] == "master" and "iat" in p

    def test_rejects_invalid_scheme(self) -> None:
        with pytest.raises(TokenError, match="scheme"):
            parse_invite_token("http://bad?token=x")

    def test_rejects_invalid_jwt_format(self) -> None:
        with pytest.raises(TokenError):
            parse_invite_token("swarm://x@y?token=bad")

    def test_rejects_expired_token(self) -> None:
        priv, pub = generate_keypair()
        expired = datetime.now(timezone.utc) - timedelta(hours=1)
        tok = generate_invite_token(priv, uuid4(), "m", "https://m.com", expires_at=expired)
        with pytest.raises(TokenError, match="expired"):
            parse_invite_token(tok, pub)

    def test_rejects_invalid_signature(self) -> None:
        priv, _ = generate_keypair()
        _, wrong = generate_keypair()
        tok = generate_invite_token(priv, uuid4(), "m", "https://m.com")
        with pytest.raises(TokenError, match="signature"):
            parse_invite_token(tok, wrong)

    def test_parses_without_verification(self) -> None:
        priv, _ = generate_keypair()
        sid = uuid4()
        tok = generate_invite_token(priv, sid, "m", "https://m.com")
        assert parse_invite_token(tok)["swarm_id"] == str(sid)

    def test_roundtrip_with_max_uses(self) -> None:
        priv, pub = generate_keypair()
        tok = generate_invite_token(priv, uuid4(), "m", "https://m.com", max_uses=5)
        assert parse_invite_token(tok, pub).get("max_uses") == 5
