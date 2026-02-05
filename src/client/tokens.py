"""Invite token generation and parsing."""

import base64
import json
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .exceptions import TokenError
from .types import InviteTokenPayload


def generate_invite_token(
    private_key: Ed25519PrivateKey, swarm_id: UUID, master_id: str, endpoint: str,
    expires_at: datetime | None = None, max_uses: int | None = None,
) -> str:
    try:
        header = _b64url_enc(json.dumps({"alg": "EdDSA", "typ": "JWT"}, separators=(",", ":")))
        payload: dict = {"swarm_id": str(swarm_id), "master": master_id, "endpoint": endpoint, "iat": int(time.time())}
        if expires_at:
            payload["expires_at"] = expires_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        if max_uses:
            payload["max_uses"] = max_uses
        payload_b64 = _b64url_enc(json.dumps(payload, separators=(",", ":")))
        sig = _b64url_enc_bytes(private_key.sign(f"{header}.{payload_b64}".encode()))
        return f"swarm://{swarm_id}@{urlparse(endpoint).netloc}?token={header}.{payload_b64}.{sig}"
    except Exception as e:
        raise TokenError(f"Failed to generate invite token: {e}") from e


def parse_invite_token(token_url: str, public_key: Ed25519PublicKey | None = None) -> InviteTokenPayload:
    try:
        if not token_url.startswith("swarm://"):
            raise TokenError("Invalid token URL scheme")
        rest = token_url[8:]
        url_swarm_id = rest[:rest.index("@")]
        jwt = parse_qs(rest[rest.index("?") + 1:])["token"][0]
        parts = jwt.split(".")
        if len(parts) != 3:
            raise TokenError("Invalid JWT format")
        header = json.loads(_b64url_dec(parts[0]))
        payload = json.loads(_b64url_dec(parts[1]))
        if header.get("alg") != "EdDSA":
            raise TokenError(f"Unsupported algorithm: {header.get('alg')}")
        if payload.get("swarm_id") != url_swarm_id:
            raise TokenError("swarm_id mismatch")
        if public_key:
            try:
                public_key.verify(_b64url_dec_bytes(parts[2]), f"{parts[0]}.{parts[1]}".encode())
            except Exception as e:
                raise TokenError(f"Invalid token signature: {e}") from e
        if expires := payload.get("expires_at"):
            if datetime.now(timezone.utc) > datetime.fromisoformat(expires.replace("Z", "+00:00")):
                raise TokenError(f"Token expired at {expires}")
        return InviteTokenPayload(swarm_id=payload["swarm_id"], master=payload["master"], endpoint=payload["endpoint"],
            iat=payload["iat"], expires_at=payload.get("expires_at"), max_uses=payload.get("max_uses"))
    except TokenError:
        raise
    except Exception as e:
        raise TokenError(f"Failed to parse token: {e}") from e


def _b64url_enc(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).rstrip(b"=").decode()


def _b64url_enc_bytes(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64url_dec(s: str) -> str:
    return base64.urlsafe_b64decode(s + "=" * (4 - len(s) % 4)).decode()


def _b64url_dec_bytes(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (4 - len(s) % 4))
