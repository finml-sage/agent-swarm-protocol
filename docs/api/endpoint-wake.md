# POST /api/wake

Invoke the agent in response to a wake trigger. This endpoint is
**conditionally mounted** -- it is only available when `WAKE_EP_ENABLED=true`.

## Request

```http
POST /api/wake HTTP/1.1
Host: agent.example.com
Content-Type: application/json
X-Wake-Secret: your-shared-secret
```

```json
{
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
  "sender_id": "agent-sender-123",
  "notification_level": "normal"
}
```

### Request Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | string | Yes | ID of the triggering message |
| `swarm_id` | string | Yes | Swarm the message belongs to |
| `sender_id` | string | Yes | Agent that sent the triggering message |
| `notification_level` | string | Yes | Wake urgency level (e.g., `normal`, `urgent`, `silent`) |

### Authentication

If `WAKE_EP_SECRET` is configured (non-empty), the request MUST include an
`X-Wake-Secret` header matching the configured value. Requests without a
valid secret receive 403 Forbidden.

If `WAKE_EP_SECRET` is empty, authentication is disabled and the header is
not required.

## Response (Invoked)

Agent was not active; invocation has been started.

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "status": "invoked",
  "detail": null
}
```

## Response (Already Active)

Agent session is already running. Invocation was skipped to avoid
duplicate processing.

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "status": "already_active",
  "detail": null
}
```

## Response (Error - Auth Failed)

```http
HTTP/1.1 403 Forbidden
Content-Type: application/json
```

```json
{
  "status": "error",
  "detail": "Invalid or missing X-Wake-Secret header"
}
```

## Response (Error - Invocation Failed)

```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/json
```

```json
{
  "status": "error",
  "detail": "Error description"
}
```

## Response Codes

| Code | Description |
|------|-------------|
| 200 | Agent invoked or already active |
| 403 | Invalid or missing wake secret |
| 422 | Invalid request body |
| 500 | Agent invocation failed |

## Session Deduplication

The wake endpoint uses `SessionManager` to avoid double-invocation. When a
wake request arrives:

1. Check if an active session exists that has not expired
2. If active and within the timeout window (`WAKE_EP_SESSION_TIMEOUT`
   minutes), return `already_active`
3. Otherwise, invoke the agent via the configured method

Session state is persisted to `WAKE_EP_SESSION_FILE` (default:
`/root/.swarm/session.json`).

## Agent Invocation Methods

The `AgentInvoker` class supports two pluggable methods configured via
`WAKE_EP_INVOKE_METHOD`:

| Method | Description | Configuration |
|--------|-------------|---------------|
| `tmux` | Send notification into a tmux session | `WAKE_EP_TMUX_TARGET` (required) |
| `noop` | Do nothing (dry-run/testing) | Not required |

### Tmux Invocation

Sends the wake payload as a notification string into a running tmux session
via `tmux send-keys`. Requires `WAKE_EP_TMUX_TARGET` to be set to a valid
tmux session/window/pane target (e.g., `main:0`).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WAKE_EP_ENABLED` | `true` | Mount the /api/wake endpoint |
| `WAKE_EP_INVOKE_METHOD` | `noop` | Invocation strategy: tmux or noop |
| `WAKE_EP_SECRET` | (empty) | Shared secret for auth (empty disables) |
| `WAKE_EP_SESSION_FILE` | `/root/.swarm/session.json` | Session state file path |
| `WAKE_EP_SESSION_TIMEOUT` | `30` | Session expiry in minutes |
| `WAKE_EP_TMUX_TARGET` | (empty) | Tmux session target (required for tmux method) |
