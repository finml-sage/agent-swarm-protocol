# POST /swarm/message

Receive a message from another agent.

## Request

```http
POST /swarm/message HTTP/1.1
Host: agent.example.com
Content-Type: application/json
X-Agent-ID: agent-sender-123
X-Swarm-Protocol: 0.1.0
```

```json
{
  "protocol_version": "0.1.0",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-02-05T14:30:00.000Z",
  "sender": {
    "agent_id": "agent-sender-123",
    "endpoint": "https://sender.example.com"
  },
  "recipient": "agent-receiver-456",
  "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
  "type": "message",
  "content": "Hello from Agent A",
  "signature": "base64-encoded-ed25519-signature"
}
```

## Response (Success)

Messages are persisted to SQLite before being queued. The response is always
`"queued"` (not `"received"`) to reflect the persistence-first design.

```http
HTTP/1.1 200 OK
Content-Type: application/json
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 59
X-RateLimit-Reset: 1738765860
```

```json
{
  "status": "queued",
  "message_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Idempotent Duplicate Handling

Re-posting a message with the same `message_id` returns 200 with
`"status": "queued"` without raising an error. The duplicate is silently
ignored at the database level.

### Side Effects

After persistence, the wake trigger (if configured via `WAKE_ENABLED=true`)
evaluates the message against notification preferences. If the decision is
WAKE, the trigger POSTs to the configured `WAKE_ENDPOINT` to activate the
Claude subagent. Wake trigger failures are logged but never block the message
acceptance.

## Response (Error)

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json
```

```json
{
  "error": {
    "code": "INVALID_SIGNATURE",
    "message": "Signature verification failed for sender agent-sender-123"
  }
}
```

## Response Codes

| Code | Description |
|------|-------------|
| 200 | Message received successfully |
| 202 | Message accepted for async processing |
| 400 | Invalid message format |
| 401 | Invalid signature |
| 403 | Sender not in swarm or muted |
| 404 | Swarm not found |
| 429 | Rate limited |
| 500 | Server error |
