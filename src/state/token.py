"""Invite token validation using Ed25519 signatures."""
import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature


class TokenError(Exception):
    """Base class for token validation errors."""


class TokenSignatureError(TokenError):
    """Raised when the token signature is invalid."""


class TokenExpiredError(TokenError):
    """Raised when the token has expired."""


class TokenPayloadError(TokenError):
    """Raised when the token payload is malformed or missing fields."""


@dataclass(frozen=True)
class InviteTokenClaims:
    """Validated claims from an invite token JWT."""

    swarm_id: str
    master: str
    endpoint: str
    iat: int
    expires_at: Optional[str] = None
    max_uses: Optional[int] = None


def _base64url_decode(data: str) -> bytes:
    """Decode base64url-encoded data with padding normalization."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _parse_jwt_parts(token: str) -> tuple[str, bytes, bytes, bytes]:
    """Split a JWT into header, payload, and signature bytes.

    Returns (signing_input, header_bytes, payload_bytes, signature_bytes).
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenPayloadError(
            f"Invalid JWT structure: expected 3 parts, got {len(parts)}"
        )
    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}"
    header_bytes = _base64url_decode(header_b64)
    payload_bytes = _base64url_decode(payload_b64)
    signature_bytes = _base64url_decode(sig_b64)
    return signing_input, header_bytes, payload_bytes, signature_bytes


def _validate_header(header_bytes: bytes) -> None:
    """Validate that the JWT header specifies EdDSA algorithm."""
    try:
        header = json.loads(header_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TokenPayloadError(f"Invalid JWT header: {exc}") from exc
    alg = header.get("alg")
    if alg != "EdDSA":
        raise TokenPayloadError(
            f"Unsupported algorithm: {alg}, expected EdDSA"
        )


def _extract_claims(payload_bytes: bytes) -> dict[str, Any]:
    """Parse and validate the JWT payload claims."""
    try:
        claims = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TokenPayloadError(f"Invalid JWT payload: {exc}") from exc
    if not isinstance(claims, dict):
        raise TokenPayloadError("JWT payload must be a JSON object")
    required = ("swarm_id", "master", "endpoint", "iat")
    missing = [f for f in required if f not in claims]
    if missing:
        raise TokenPayloadError(
            f"Missing required claims: {', '.join(missing)}"
        )
    return claims


def verify_invite_token(
    token: str,
    public_key_bytes: bytes,
    expected_swarm_id: Optional[str] = None,
) -> InviteTokenClaims:
    """Verify an invite token JWT and return its claims.

    Args:
        token: The raw JWT string (header.payload.signature).
        public_key_bytes: The Ed25519 public key bytes (32 bytes raw).
        expected_swarm_id: If provided, verify the token's swarm_id matches.

    Returns:
        InviteTokenClaims with the validated token data.

    Raises:
        TokenSignatureError: If the Ed25519 signature is invalid.
        TokenExpiredError: If the token has expired.
        TokenPayloadError: If the token structure or claims are invalid.
    """
    signing_input, header_bytes, payload_bytes, signature_bytes = (
        _parse_jwt_parts(token)
    )
    _validate_header(header_bytes)

    try:
        key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    except (ValueError, TypeError) as exc:
        raise TokenSignatureError(
            f"Invalid public key: {exc}"
        ) from exc

    try:
        key.verify(signature_bytes, signing_input.encode("ascii"))
    except InvalidSignature as exc:
        raise TokenSignatureError("Token signature verification failed") from exc

    claims = _extract_claims(payload_bytes)

    if claims.get("expires_at"):
        try:
            exp_dt = datetime.fromisoformat(claims["expires_at"])
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if exp_dt < datetime.now(timezone.utc):
                raise TokenExpiredError(
                    f"Token expired at {claims['expires_at']}"
                )
        except ValueError as exc:
            raise TokenPayloadError(
                f"Invalid expires_at format: {claims['expires_at']}"
            ) from exc

    if expected_swarm_id and claims["swarm_id"] != expected_swarm_id:
        raise TokenPayloadError(
            f"Token swarm_id '{claims['swarm_id']}' does not match "
            f"expected '{expected_swarm_id}'"
        )

    return InviteTokenClaims(
        swarm_id=claims["swarm_id"],
        master=claims["master"],
        endpoint=claims["endpoint"],
        iat=claims["iat"],
        expires_at=claims.get("expires_at"),
        max_uses=claims.get("max_uses"),
    )
