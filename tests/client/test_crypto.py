"""Tests for cryptographic operations."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.client.crypto import build_signing_payload, generate_keypair, private_key_to_bytes
from src.client.crypto import public_key_from_base64, public_key_to_base64, public_key_to_bytes
from src.client.crypto import sign_message, verify_signature
from src.client.exceptions import SignatureError


class TestKeypairGeneration:
    def test_generate_keypair_returns_tuple(self) -> None:
        private_key, public_key = generate_keypair()
        assert private_key is not None and public_key is not None

    def test_private_key_to_bytes_returns_32_bytes(self) -> None:
        assert len(private_key_to_bytes(generate_keypair()[0])) == 32

    def test_public_key_to_bytes_returns_32_bytes(self) -> None:
        assert len(public_key_to_bytes(generate_keypair()[1])) == 32

    def test_public_key_base64_roundtrip(self) -> None:
        _, pk = generate_keypair()
        decoded = public_key_from_base64(public_key_to_base64(pk))
        assert public_key_to_bytes(decoded) == public_key_to_bytes(pk)

    def test_invalid_base64_raises_signature_error(self) -> None:
        with pytest.raises(SignatureError):
            public_key_from_base64("not-valid-base64!!!")


class TestSigningPayload:
    def test_build_signing_payload_deterministic(self) -> None:
        mid, ts, sid = uuid4(), datetime(2026, 2, 5, 14, 30, 0, tzinfo=timezone.utc), uuid4()
        p1 = build_signing_payload(mid, ts, sid, "r", "m", "c")
        p2 = build_signing_payload(mid, ts, sid, "r", "m", "c")
        assert p1 == p2

    def test_build_signing_payload_different_content(self) -> None:
        mid, ts, sid = uuid4(), datetime(2026, 2, 5, 14, 30, 0, tzinfo=timezone.utc), uuid4()
        p1 = build_signing_payload(mid, ts, sid, "r", "m", "c1")
        p2 = build_signing_payload(mid, ts, sid, "r", "m", "c2")
        assert p1 != p2


class TestMessageSigning:
    def test_sign_and_verify_valid_signature(self) -> None:
        priv, pub = generate_keypair()
        mid, ts, sid = uuid4(), datetime.now(timezone.utc), uuid4()
        sig = sign_message(priv, mid, ts, sid, "r", "m", "test")
        assert verify_signature(pub, sig, mid, ts, sid, "r", "m", "test")

    def test_verify_rejects_tampered_content(self) -> None:
        priv, pub = generate_keypair()
        mid, ts, sid = uuid4(), datetime.now(timezone.utc), uuid4()
        sig = sign_message(priv, mid, ts, sid, "r", "m", "test")
        assert not verify_signature(pub, sig, mid, ts, sid, "r", "m", "tampered")

    def test_verify_rejects_wrong_key(self) -> None:
        priv, _ = generate_keypair()
        _, wrong = generate_keypair()
        mid, ts, sid = uuid4(), datetime.now(timezone.utc), uuid4()
        sig = sign_message(priv, mid, ts, sid, "r", "m", "test")
        assert not verify_signature(wrong, sig, mid, ts, sid, "r", "m", "test")
