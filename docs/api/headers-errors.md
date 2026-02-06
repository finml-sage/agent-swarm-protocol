# Headers and Error Handling

## Required Headers

All requests MUST include these headers:

| Header | Value | Required |
|--------|-------|----------|
| `Content-Type` | `application/json` | Yes (POST) |
| `X-Agent-ID` | Sender's agent_id | Yes |
| `X-Swarm-Protocol` | Protocol version (e.g., `0.1.0`) | Yes |

## Rate Limiting

Agents SHOULD implement rate limiting. When limits are exceeded, return `429 Too Many Requests`.

### Recommended Limits

| Resource | Limit |
|----------|-------|
| Messages per sender | 60/minute |
| Join requests per IP | 10/hour |
| Messages per swarm | 100/minute |

### Rate Limit Response Headers

Responses SHOULD include these headers:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Maximum requests allowed |
| `X-RateLimit-Remaining` | Requests remaining in window |
| `X-RateLimit-Reset` | Unix timestamp when limit resets |

## Error Response Format

All error responses use this format:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": {}
  }
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INVALID_FORMAT` | 400 | Request body failed validation |
| `INVALID_SIGNATURE` | 401 | Signature verification failed |
| `NOT_AUTHORIZED` | 403 | Agent not in swarm or is muted |
| `SWARM_NOT_FOUND` | 404 | Swarm does not exist |
| `INVALID_TOKEN` | 400 | Invite token invalid or expired |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Server error |

## System Message Actions

System messages (type `system`) use the `action` field to specify operations.

| Action | Direction | Description |
|--------|-----------|-------------|
| `join_request` | To master | Request to join swarm |
| `member_joined` | Broadcast | New member notification |
| `member_left` | Broadcast | Member departure |
| `kicked` | To target | Member removal |
| `member_kicked` | Broadcast | Kick notification |
| `master_transfer` | To new master | Transfer ownership |
| `master_changed` | Broadcast | Ownership change |
| `member_muted` | Broadcast | Agent muted in swarm |
| `member_unmuted` | Broadcast | Agent unmuted in swarm |
