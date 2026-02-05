# Invite Token Specification

**Version**: 0.1.0
**Status**: Draft

## Overview

Invite tokens enable swarm masters to grant membership to new agents. Tokens are cryptographically signed JWTs that can be shared via any channel (URL, message, file).

## Token URL Format

```
swarm://<swarm_id>@<endpoint>?token=<jwt>
```

**Components**:

| Component | Description | Example |
|-----------|-------------|---------|
| `swarm_id` | UUID of the target swarm | `550e8400-e29b-41d4-a716-446655440000` |
| `endpoint` | Master's HTTPS endpoint | `agent.example.com` |
| `jwt` | Base64URL-encoded JWT | `eyJhbGciOiJFZERTQSJ9...` |

**Example**:
```
swarm://550e8400-e29b-41d4-a716-446655440000@agent.example.com?token=eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJzd2FybV9pZCI6IjU1MGU4NDAwLWUyOWItNDFkNC1hNzE2LTQ0NjY1NTQ0MDAwMCIsIm1hc3RlciI6Im1hc3Rlci1hZ2VudC0wMDEiLCJlbmRwb2ludCI6Imh0dHBzOi8vYWdlbnQuZXhhbXBsZS5jb20iLCJleHBpcmVzX2F0IjoiMjAyNi0wMy0wNVQxNDozMDowMC4wMDBaIiwibWF4X3VzZXMiOjEsImlhdCI6MTczODc2MzgwMH0.signature
```

## JWT Structure

### Header

```json
{
  "alg": "EdDSA",
  "typ": "JWT"
}
```

The signing algorithm MUST be EdDSA (Ed25519) for consistency with message signatures.

### Payload

```json
{
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "master": "master-agent-001",
  "endpoint": "https://agent.example.com",
  "expires_at": "2026-03-05T14:30:00.000Z",
  "max_uses": 1,
  "iat": 1738763800
}
```

**Required Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `swarm_id` | string (UUID) | The swarm this token grants access to |
| `master` | string | Agent ID of the swarm master who issued token |
| `endpoint` | string (URI) | Master's HTTPS endpoint for join requests |
| `iat` | integer | Unix timestamp when token was issued |

**Optional Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `expires_at` | string (ISO-8601) | When token becomes invalid |
| `max_uses` | integer or null | Maximum number of times token can be used |

### Signature

The JWT is signed with the master's Ed25519 private key. The signature covers the base64url-encoded header and payload:

```
signature = Ed25519_sign(
  base64url(header) + "." + base64url(payload),
  master_private_key
)
```

## Validation Steps

When an agent receives an invite token, validate in this order:

1. **Parse URL**: Extract `swarm_id`, `endpoint`, and `jwt` from URL
2. **Decode JWT**: Split into header, payload, signature components
3. **Verify algorithm**: Confirm header `alg` is `EdDSA`
4. **Verify signature**: Validate against master's public key
5. **Check expiration**: If `expires_at` exists, verify current time is before it
6. **Check swarm_id match**: URL `swarm_id` must match payload `swarm_id`
7. **Check endpoint match**: URL `endpoint` must match payload `endpoint` host

**Validation Errors**:

| Error | HTTP Code | Description |
|-------|-----------|-------------|
| `invalid_token_format` | 400 | JWT cannot be parsed |
| `unsupported_algorithm` | 400 | Algorithm is not EdDSA |
| `invalid_signature` | 401 | Signature verification failed |
| `token_expired` | 401 | Current time is past `expires_at` |
| `swarm_id_mismatch` | 400 | URL and payload swarm_id differ |
| `endpoint_mismatch` | 400 | URL and payload endpoint differ |
| `max_uses_exceeded` | 403 | Token has been used maximum times |

## Expiration Handling

Tokens can expire in two ways:

### Time-based Expiration

If `expires_at` is set, the token becomes invalid after that timestamp.

- Masters SHOULD set reasonable expiration times (hours to days, not months)
- Joining agents MUST check expiration before sending join request
- Masters MUST re-check expiration when processing join request

### Use-based Expiration

If `max_uses` is set, the token becomes invalid after that many successful joins.

- Only the master tracks use count (distributed tracking is impractical)
- Masters MUST store: `{ token_hash: { uses: int, max: int } }`
- When `uses >= max`, reject with `max_uses_exceeded`
- Single-use tokens (`max_uses: 1`) are recommended for security

**Master Use Tracking**:

```json
{
  "invite_tokens": {
    "sha256(jwt)": {
      "uses": 0,
      "max_uses": 1,
      "created_at": "2026-02-05T14:30:00.000Z",
      "expires_at": "2026-03-05T14:30:00.000Z"
    }
  }
}
```

## Security Considerations

### Token Distribution

- Tokens grant swarm access; treat as sensitive credentials
- Use secure channels (encrypted messaging, HTTPS) for distribution
- Prefer single-use tokens when inviting specific agents
- Set short expiration for tokens shared in less-secure contexts

### Token Revocation

Masters can revoke tokens before expiration by:

1. Adding token hash to a revocation list
2. Checking revocation list during join validation
3. Returning `token_revoked` (403) for revoked tokens

### Replay Protection

- Single-use tokens prevent replay attacks
- For multi-use tokens, masters MAY track joining agent IDs to prevent duplicate joins

## Example Tokens

### Single-Use Token (Recommended)

```json
{
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "master": "orchestrator-alpha",
  "endpoint": "https://orchestrator.example.com",
  "expires_at": "2026-02-06T14:30:00.000Z",
  "max_uses": 1,
  "iat": 1738763800
}
```

### Multi-Use Token with Expiration

```json
{
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "master": "orchestrator-alpha",
  "endpoint": "https://orchestrator.example.com",
  "expires_at": "2026-02-12T00:00:00.000Z",
  "max_uses": 10,
  "iat": 1738763800
}
```

### Open Token (Use with Caution)

```json
{
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "master": "orchestrator-alpha",
  "endpoint": "https://orchestrator.example.com",
  "iat": 1738763800
}
```

No expiration or use limit. Suitable only for public or trusted-network swarms.
