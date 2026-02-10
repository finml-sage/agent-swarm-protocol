# GET /swarm/health

Check if the agent is operational.

## Request

```http
GET /swarm/health HTTP/1.1
Host: agent.example.com
X-Agent-ID: agent-checker-999
X-Swarm-Protocol: 0.1.0
```

## Response (Healthy)

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "status": "healthy",
  "agent_id": "agent-receiver-456",
  "protocol_version": "0.1.0",
  "timestamp": "2026-02-05T14:30:00.000Z"
}
```

## Response (Degraded)

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "status": "degraded",
  "agent_id": "agent-receiver-456",
  "protocol_version": "0.1.0",
  "timestamp": "2026-02-05T14:30:00.000Z",
  "message": "Inbox backlog exceeds threshold"
}
```

## Response Codes

| Code | Description |
|------|-------------|
| 200 | Agent status returned |
| 500 | Server error |

## Status Values

| Status | Description |
|--------|-------------|
| `healthy` | Agent fully operational |
| `degraded` | Agent operational but with issues |
