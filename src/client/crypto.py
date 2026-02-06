"""Cryptographic operations for Ed25519 signing and verification."""

import base64
import hashlib
from datetime import datetime
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .exceptions import SignatureError


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate a new Ed25519 keypair."""
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def public_key_to_bytes(public_key: Ed25519PublicKey) -> bytes:
    """Serialize public key to raw 32 bytes."""
    return public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def public_key_to_base64(public_key: Ed25519PublicKey) -> str:
    """Encode public key as base64 string."""
    return base64.b64encode(public_key_to_bytes(public_key)).decode("utf-8")


def public_key_from_base64(encoded: str) -> Ed25519PublicKey:
    """Decode public key from base64 string."""
    try:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded))
    except Exception as e:
        raise SignatureError(f"Invalid public key encoding: {e}") from e


def build_signing_payload(
    message_id: UUID, timestamp: datetime, swarm_id: UUID,
    recipient: str, message_type: str, content: str,
) -> bytes:
    """Build the canonical payload for signing (SHA256 hash of concatenated fields)."""
    timestamp_str = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    payload = str(message_id) + timestamp_str + str(swarm_id) + recipient + message_type + content
    return hashlib.sha256(payload.encode("utf-8")).digest()


def sign_message(
    private_key: Ed25519PrivateKey, message_id: UUID, timestamp: datetime,
    swarm_id: UUID, recipient: str, message_type: str, content: str,
) -> str:
    """Sign a message with Ed25519 private key. Returns base64-encoded signature."""
    try:
        payload = build_signing_payload(message_id, timestamp, swarm_id, recipient, message_type, content)
        return base64.b64encode(private_key.sign(payload)).decode("utf-8")
    except Exception as e:
        raise SignatureError(f"Failed to sign message: {e}") from e


def verify_signature(
    public_key: Ed25519PublicKey, signature_b64: str, message_id: UUID,
    timestamp: datetime, swarm_id: UUID, recipient: str, message_type: str, content: str,
) -> bool:
    """Verify a message signature. Returns True if valid, False otherwise."""
    try:
        payload = build_signing_payload(message_id, timestamp, swarm_id, recipient, message_type, content)
        public_key.verify(base64.b64decode(signature_b64), payload)
        return True
    except Exception:
        return False
