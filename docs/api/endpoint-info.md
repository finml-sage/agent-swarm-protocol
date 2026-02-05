# GET /swarm/info

Get public information about an agent.

## Request

```http
GET /swarm/info HTTP/1.1
Host: agent.example.com
X-Agent-ID: agent-checker-999
X-Swarm-Protocol: 0.1.0
```

## Response

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "agent_id": "agent-receiver-456",
  "endpoint": "https://agent.example.com",
  "public_key": "base64-encoded-ed25519-public-key",
  "protocol_version": "0.1.0",
  "capabilities": ["message", "system", "notification"],
  "metadata": {
    "name": "Research Assistant Agent",
    "description": "Handles research and documentation tasks"
  }
}
```

## Response Codes

| Code | Description |
|------|-------------|
| 200 | Agent information returned |
| 500 | Server error |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | string | This agent's unique identifier |
| `endpoint` | string | HTTPS URL for receiving messages |
| `public_key` | string | Base64-encoded Ed25519 public key |
| `protocol_version` | string | Supported protocol version |
| `capabilities` | array | Supported message types |
| `metadata` | object | Optional agent metadata |

## Capabilities

| Capability | Description |
|------------|-------------|
| `message` | Standard agent-to-agent messages |
| `system` | Swarm operations (join, leave, kick) |
| `notification` | One-way informational messages |
