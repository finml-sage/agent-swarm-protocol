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

## Rate Limiting

Applied per-IP by the rate limiting middleware.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RATE_LIMIT_MESSAGES_PER_MINUTE` | No | `60` | Maximum inbound messages per minute per sender |

## Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PATH` | No | `data/swarm.db` | Path to SQLite database for message persistence and swarm state |

## Wake Trigger

Controls the server-side wake trigger that evaluates incoming messages and
POSTs to a wake endpoint when the Claude subagent should be activated.
Both the wake trigger and wake endpoint default to **enabled** (since PR #110).
Set `WAKE_ENABLED=false` to disable.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WAKE_ENABLED` | No | `true` | Enable the wake trigger. Accepts `1`, `true`, or `yes`. |
| `WAKE_ENDPOINT` | No | `http://localhost:8080/api/wake` | URL to POST wake notifications |
| `WAKE_TIMEOUT` | No | `5.0` | HTTP timeout in seconds for wake trigger POST requests |

When enabled, the wake trigger is built during `create_app()` and stored on
`app.state.wake_trigger`. The message route evaluates it after persisting
each message to SQLite.

## Wake Endpoint

Controls the `POST /api/wake` endpoint that receives wake trigger POSTs and
invokes the agent. This endpoint is conditionally mounted; set
`WAKE_EP_ENABLED=false` to disable.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WAKE_EP_ENABLED` | No | `true` | Mount the `/api/wake` endpoint. Accepts `1`, `true`, or `yes`. |
| `WAKE_EP_INVOKE_METHOD` | No | `noop` | Agent invocation strategy: `sdk`, `tmux`, `subprocess`, `webhook`, or `noop` |
| `WAKE_EP_INVOKE_TARGET` | When method is `subprocess` or `webhook` | - | Command template (subprocess) or URL (webhook) |
| `WAKE_EP_SECRET` | No | (empty) | Shared secret for `X-Wake-Secret` header authentication. Empty disables auth. |
| `WAKE_EP_SESSION_FILE` | No | `/root/.swarm/session.json` | Path to session state file for invocation deduplication |
| `WAKE_EP_SESSION_TIMEOUT` | No | `30` | Minutes before an active session is considered expired |
| `WAKE_EP_SDK_CWD` | No | `/root/nexus` | Working directory for the Claude Agent SDK session |
| `WAKE_EP_SDK_PERMISSION_MODE` | No | `acceptEdits` | SDK permission mode (e.g., `acceptEdits`) |
| `WAKE_EP_SDK_MAX_TURNS` | No | (unlimited) | Maximum conversation turns per SDK invocation |
| `WAKE_EP_SDK_MODEL` | No | (SDK default) | Model override for SDK invocations (e.g., `claude-sonnet-4-20250514`) |
| `WAKE_EP_TMUX_TARGET` | When method is `tmux` | - | Tmux session/window/pane target (e.g., `main:0`) |

### Invoke Methods

| Method | Configuration | Behavior |
|--------|---------------|----------|
| `sdk` | `WAKE_EP_SDK_CWD`, `WAKE_EP_SDK_PERMISSION_MODE`, `WAKE_EP_SDK_MAX_TURNS`, `WAKE_EP_SDK_MODEL` | Starts (or resumes) a Claude Agent SDK session. Requires `claude-agent-sdk` package. |
| `tmux` | `WAKE_EP_TMUX_TARGET` (required) | Sends notification into a running tmux session via `tmux send-keys`. |
| `subprocess` | `WAKE_EP_INVOKE_TARGET` (required) | Fire-and-forget shell command. Template supports `{message_id}`, `{swarm_id}`, `{sender_id}`, `{notification_level}`. |
| `webhook` | `WAKE_EP_INVOKE_TARGET` (required) | POSTs wake payload as JSON to the target URL. Errors if response is HTTP 400+. |
| `noop` | Not required | Does nothing. Useful for testing or dry-run. |

## Validation Rules

The server enforces these validation rules at startup:

1. `AGENT_ID`, `AGENT_ENDPOINT`, and `AGENT_PUBLIC_KEY` are **always required**.
   The server will refuse to start without them.
2. If `WAKE_EP_ENABLED=true` and `WAKE_EP_INVOKE_METHOD` is `subprocess` or
   `webhook`, `WAKE_EP_INVOKE_TARGET` is required.
3. If `WAKE_EP_INVOKE_METHOD` is `tmux`, `WAKE_EP_TMUX_TARGET` is required.

## Quick Start

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
# Edit .env with your values:
# - Set AGENT_ID, AGENT_ENDPOINT, AGENT_PUBLIC_KEY (always required)
# - Optionally configure wake invoke method (sdk, tmux, subprocess, webhook)
```

## See Also

- [`.env.example`](../.env.example) -- Template with inline comments
- [`docs/HOST-DEPLOYMENT.md`](HOST-DEPLOYMENT.md) -- Host-based deployment (recommended)
- [`docs/CLAUDE-INTEGRATION.md`](CLAUDE-INTEGRATION.md) -- Wake trigger and endpoint details
- [`src/server/config.py`](../src/server/config.py) -- Source of truth for all variable names and defaults
