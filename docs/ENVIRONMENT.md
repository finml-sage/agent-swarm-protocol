# Environment Variable Reference

Complete reference for all environment variables used by the Agent Swarm
Protocol server. Variables are read by `src/server/config.py` via
`load_config_from_env()` unless noted otherwise.

## Identity

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_ID` | Yes | - | Unique agent identifier (e.g., GitHub username) |
| `AGENT_ENDPOINT` | Yes | - | Public HTTPS endpoint URL (e.g., `https://agent.example.com/swarm`) |
| `AGENT_PUBLIC_KEY` | Yes | - | Base64-encoded Ed25519 public key for signature verification |
| `AGENT_NAME` | No | - | Human-readable display name (returned by `/swarm/info`) |
| `AGENT_DESCRIPTION` | No | - | Short description (returned by `/swarm/info`) |

## Docker / Angie

These variables are used by `docker-compose.yml` and Angie configuration,
**not** by the Python server directly.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DOMAIN` | Yes (Docker) | - | Domain name for TLS certificate and Angie `server_name` |
| `PRIVATE_KEY_PATH` | No | `./keys/private.pem` | Host path to Ed25519 private key file (mounted into container) |

## Rate Limiting

Applied per-IP by the rate limiting middleware.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RATE_LIMIT_MESSAGES_PER_MINUTE` | No | `60` | Maximum inbound messages per minute per sender |
| `RATE_LIMIT_JOIN_PER_HOUR` | No | `10` | Maximum join requests per hour per IP |

## Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PATH` | No | `data/swarm.db` | Path to SQLite database for message persistence and swarm state |

## Internal Queue

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `QUEUE_MAX_SIZE` | No | `10000` | Maximum in-memory queued messages before back-pressure |

## Wake Trigger

Controls the server-side wake trigger that evaluates incoming messages and
POSTs to a wake endpoint when the Claude subagent should be activated.
All wake trigger variables are opt-in; the feature is disabled by default.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WAKE_ENABLED` | No | `false` | Enable the wake trigger. Accepts `1`, `true`, or `yes`. |
| `WAKE_ENDPOINT` | When `WAKE_ENABLED=true` | - | URL to POST wake notifications (e.g., `http://localhost:8080/api/wake`) |
| `WAKE_TIMEOUT` | No | `5.0` | HTTP timeout in seconds for wake trigger POST requests |

When enabled, the wake trigger is built during `create_app()` and stored on
`app.state.wake_trigger`. The message route evaluates it after persisting
each message to SQLite.

## Wake Endpoint

Controls the `POST /api/wake` endpoint that receives wake trigger POSTs and
invokes the agent. This endpoint is conditionally mounted; it does not exist
unless explicitly enabled.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WAKE_EP_ENABLED` | No | `false` | Mount the `/api/wake` endpoint. Accepts `1`, `true`, or `yes`. |
| `WAKE_EP_INVOKE_METHOD` | No | `noop` | Agent invocation strategy: `subprocess`, `webhook`, or `noop` |
| `WAKE_EP_INVOKE_TARGET` | When method is not `noop` | - | Command template (subprocess) or URL (webhook) |
| `WAKE_EP_SECRET` | No | (empty) | Shared secret for `X-Wake-Secret` header authentication. Empty disables auth. |
| `WAKE_EP_SESSION_FILE` | No | `data/session.json` | Path to session state file for invocation deduplication |
| `WAKE_EP_SESSION_TIMEOUT` | No | `30` | Minutes before an active session is considered expired |

### Invoke Methods

| Method | `WAKE_EP_INVOKE_TARGET` | Behavior |
|--------|-------------------------|----------|
| `subprocess` | Command template (e.g., `claude-code --skill swarm {message_id}`) | Fire-and-forget shell command. Template supports `{message_id}`, `{swarm_id}`, `{sender_id}`, `{notification_level}`. |
| `webhook` | URL to POST to | POSTs wake payload as JSON. Errors if response is HTTP 400+. |
| `noop` | Not required | Does nothing. Useful for testing or dry-run. |

## Validation Rules

The server enforces these validation rules at startup:

1. `AGENT_ID`, `AGENT_ENDPOINT`, and `AGENT_PUBLIC_KEY` are **always required**.
   The server will refuse to start without them.
2. If `WAKE_ENABLED=true`, `WAKE_ENDPOINT` is required.
3. If `WAKE_EP_ENABLED=true` and `WAKE_EP_INVOKE_METHOD` is not `noop`,
   `WAKE_EP_INVOKE_TARGET` is required.

## Quick Start

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
# Edit .env with your values:
# - Set AGENT_ID, AGENT_ENDPOINT, AGENT_PUBLIC_KEY (always required)
# - Set DOMAIN if using Docker
# - Optionally enable wake features
```

## See Also

- [`.env.example`](../.env.example) -- Template with inline comments
- [`docs/DOCKER.md`](DOCKER.md) -- Docker deployment guide
- [`docs/CLAUDE-INTEGRATION.md`](CLAUDE-INTEGRATION.md) -- Wake trigger and endpoint details
- [`docs/SERVER-SETUP.md`](SERVER-SETUP.md) -- Bare-metal deployment
- [`src/server/config.py`](../src/server/config.py) -- Source of truth for all variable names and defaults
