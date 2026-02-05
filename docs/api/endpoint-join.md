# POST /swarm/join

Request to join a swarm using an invite token.

## Request

```http
POST /swarm/join HTTP/1.1
Host: master.example.com
Content-Type: application/json
X-Agent-ID: agent-new-789
X-Swarm-Protocol: 0.1.0
```

```json
{
  "type": "system",
  "action": "join_request",
  "invite_token": "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9...",
  "sender": {
    "agent_id": "agent-new-789",
    "endpoint": "https://newagent.example.com",
    "public_key": "base64-encoded-ed25519-public-key"
  }
}
```

## Response (Success)

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "status": "accepted",
  "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
  "swarm_name": "Project Alpha Swarm",
  "members": [
    {
      "agent_id": "master-agent-001",
      "endpoint": "https://master.example.com",
      "public_key": "base64-encoded-public-key-1"
    },
    {
      "agent_id": "agent-existing-002",
      "endpoint": "https://existing.example.com",
      "public_key": "base64-encoded-public-key-2"
    }
  ]
}
```

## Response (Pending Approval)

```http
HTTP/1.1 202 Accepted
Content-Type: application/json
```

```json
{
  "status": "pending",
  "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
  "message": "Join request requires master approval"
}
```

## Response (Error - Invalid Token)

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json
```

```json
{
  "error": {
    "code": "INVALID_TOKEN",
    "message": "Invite token has expired",
    "details": {
      "expired_at": "2026-02-04T12:00:00.000Z"
    }
  }
}
```

## Response Codes

| Code | Description |
|------|-------------|
| 200 | Join request accepted |
| 202 | Join request pending approval |
| 400 | Invalid request or token |
| 429 | Rate limited |
| 500 | Server error |
