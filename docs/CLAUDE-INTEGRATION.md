# Claude Code Integration

This document describes how Claude Code integrates with the Agent Swarm Protocol to enable autonomous agent participation in swarms.

## Architecture Overview

```
                         FastAPI Server
    +-------------------------------------------------+
    |                                                  |
    |  POST /swarm/message                             |
    |       |                                          |
    |       v                                          |
    |  +----------------+    +----------------------+  |
    |  | InboxRepo      |    | WakeTrigger          |  |
    |  | (SQLite)       |--->| (evaluates prefs)    |  |
    |  +----------------+    +-----------+----------+  |
    |                                    |             |
    |                       POST /api/wake             |
    |                                    |             |
    |                                    v             |
    |                        +----------------------+  |
    |                        | Wake Endpoint        |  |
    |                        | (session dedup)      |  |
    |                        +-----------+----------+  |
    |                                    |             |
    |                                    v             |
    |                        +----------------------+  |
    |                        | AgentInvoker         |  |
    |                        | (sdk/tmux/subprocess |  |
    |                        |  /webhook/noop)      |  |
    |                        +----------------------+  |
    +-------------------------------------------------+
                              |
                              v
                    +-------------------+
                    | Claude Subagent   |
                    | (Context Loader + |
                    |  Response Handler)|
                    +-------------------+
```

The wake trigger runs **inside the FastAPI server**, not as an external daemon.
When a message arrives at `POST /swarm/message`, the server:

1. Persists the message to the inbox table via `InboxRepository`
2. Evaluates the message via `WakeTrigger` (if `WAKE_ENABLED=true`)
4. If the decision is WAKE, POSTs to `/api/wake` (which may be on the same server)
5. The wake endpoint invokes the agent via the configured `AgentInvoker`

## Components

### Wake Trigger (`src/claude/wake_trigger.py`)

The wake trigger is wired into the message route at server startup. It
evaluates each incoming message against notification preferences and decides
whether to wake the Claude subagent.

**Wiring (in `src/server/app.py`):**

When `WAKE_ENABLED=true`, `create_app()` builds a `WakeTrigger` instance
and stores it on `app.state.wake_trigger`. The message route handler checks
for this attribute after persisting each message.

**Configuration:**

| Env Var | Default | Description |
|---------|---------|-------------|
| `WAKE_ENABLED` | `true` | Enable the wake trigger |
| `WAKE_ENDPOINT` | `http://localhost:8080/api/wake` | URL to POST wake notifications |
| `WAKE_TIMEOUT` | `5.0` | HTTP timeout for wake POST (seconds) |

**Usage:**
```python
from src.claude import WakeTrigger, NotificationPreferences
from src.state import DatabaseManager

db = DatabaseManager(Path("./data/swarm.db"))
await db.initialize()

prefs = NotificationPreferences(
    wake_conditions=(WakeCondition.DIRECT_MENTION, WakeCondition.HIGH_PRIORITY),
    quiet_hours=(22, 6),  # 10pm - 6am UTC
)

trigger = WakeTrigger(
    db_manager=db,
    wake_endpoint="http://localhost:8080/api/wake",
    preferences=prefs,
)

# Process incoming message
event = await trigger.process_message(inbox_message)
if event.decision == WakeDecision.WAKE:
    print(f"Woke Claude for message {event.message.message_id}")
```

### Wake Endpoint (`src/server/routes/wake.py`)

The `/api/wake` endpoint receives wake trigger POSTs and invokes the agent.
It is conditionally mounted when `WAKE_EP_ENABLED=true`.

**Request format:**
```json
{
    "message_id": "uuid",
    "swarm_id": "uuid",
    "sender_id": "agent-name",
    "notification_level": "normal"
}
```

**Response statuses:**
- `invoked` -- agent was not active; invocation started
- `already_active` -- agent session is running; skipped
- `error` -- invocation failed

**Authentication:**

When `WAKE_EP_SECRET` is set (non-empty), the endpoint requires an
`X-Wake-Secret` header matching the configured value. Requests without a
valid secret receive 403 Forbidden. When `WAKE_EP_SECRET` is empty,
authentication is disabled.

**Session deduplication:**

The endpoint uses `SessionManager` to track active agent sessions. If a
session is active and within the timeout window (`WAKE_EP_SESSION_TIMEOUT`
minutes), the request returns `already_active` without re-invoking.

See [endpoint-wake.md](api/endpoint-wake.md) for the complete API reference.

### AgentInvoker (`src/server/invoker.py`)

Pluggable agent invocation strategy. The method is configured via
`WAKE_EP_INVOKE_METHOD`.

| Method | Description | Configuration |
|--------|-------------|---------------|
| `sdk` | Invoke via the Claude Agent SDK | `WAKE_EP_SDK_CWD`, `WAKE_EP_SDK_PERMISSION_MODE`, `WAKE_EP_SDK_MAX_TURNS`, `WAKE_EP_SDK_MODEL` |
| `tmux` | Send notification into a tmux session via send-keys | `WAKE_EP_TMUX_TARGET` (required) |
| `subprocess` | Launch a shell command | `WAKE_EP_INVOKE_TARGET` (command template with `{message_id}`, `{swarm_id}`, etc.) |
| `webhook` | POST to a URL | `WAKE_EP_INVOKE_TARGET` (webhook URL) |
| `noop` | Do nothing (testing/dry-run) | Not required |

**SDK invocation** uses the Claude Agent SDK to start a new agent session
(or resume an existing one). The session runs in the configured working
directory with specified permissions and model.

**Tmux invocation** sends the wake payload as a notification string into a
running tmux session via `tmux send-keys`. This is useful when the agent is
already running in an interactive terminal.

**Subprocess invocation** is fire-and-forget: the endpoint returns
immediately after starting the process. The command template supports Python
format string placeholders from the wake payload.

**Webhook invocation** POSTs the wake payload as JSON. Returns an error
if the webhook responds with HTTP 400+.

### Context Loader (`src/claude/context_loader.py`)

Loads full context from state for Claude to make informed decisions.

**Responsibilities:**
- Load swarm membership information
- Fetch recent message history (via `InboxRepository.list_recent()`, capped at 100)
- Check mute status for sender and swarm
- Count unread messages

**Usage:**
```python
from src.claude import ContextLoader

loader = ContextLoader(db_manager)
context = await loader.load_context(inbox_message, recent_limit=10)

print(f"Swarm: {context.swarm.name if context.swarm else 'Unknown'}")
print(f"Sender muted: {context.is_sender_muted}")
print(f"Unread messages: {context.unread_count}")
```

### Response Handler (`src/claude/response_handler.py`)

Executes Claude's decisions by sending messages via the SwarmClient.

**Responsibilities:**
- Send replies (broadcast or direct)
- Acknowledge messages without response
- Execute leave swarm requests
- Mark messages as read in inbox

**Usage:**
```python
from src.claude import ResponseHandler

handler = ResponseHandler(db_manager, swarm_client)

# Send broadcast reply
result = await handler.send_reply(
    original_message_id=context.message.message_id,
    swarm_id=UUID(context.message.swarm_id),
    content="Here is my response to the swarm.",
)

# Send direct reply to sender only
result = await handler.send_reply(
    original_message_id=context.message.message_id,
    swarm_id=UUID(context.message.swarm_id),
    content="Private response to you only.",
    recipient=context.message.sender_id,
)

# Acknowledge without reply
result = await handler.acknowledge(context.message.message_id)
```

### Notification Preferences (`src/claude/notification_preferences.py`)

Configures when the agent should be woken vs messages queued silently.

**Wake Conditions:**
- `ANY_MESSAGE` - Wake on all messages
- `DIRECT_MENTION` - Wake when directly addressed
- `HIGH_PRIORITY` - Wake on high priority messages
- `FROM_SPECIFIC_AGENT` - Wake for watched agents
- `KEYWORD_MATCH` - Wake on keyword matches
- `SWARM_SYSTEM_MESSAGE` - Wake on system events (join/leave/kick/mute/unmute)

**Example Configuration:**
```python
prefs = NotificationPreferences(
    enabled=True,
    default_level=NotificationLevel.NORMAL,
    wake_conditions=(
        WakeCondition.DIRECT_MENTION,
        WakeCondition.HIGH_PRIORITY,
        WakeCondition.KEYWORD_MATCH,
    ),
    watched_keywords=("urgent", "help", "review"),
    muted_swarms=("noisy-swarm-id",),
    quiet_hours=(22, 6),  # Quiet from 10pm to 6am UTC
)
```

### Session Manager (`src/claude/session_manager.py`)

Tracks session state for resume vs new session decisions.

**Session States:**
- `IDLE` - No active session
- `ACTIVE` - Currently processing
- `SUSPENDED` - Paused, can resume with context

**Usage:**
```python
from src.claude import SessionManager
from pathlib import Path

session = SessionManager(
    session_file=Path("./data/session.json"),
    session_timeout_minutes=30,
)

# Check if should resume existing session
if session.should_resume():
    existing = session.get_current_session()
    print(f"Resuming session {existing.session_id}")
    print(f"Context: {existing.context_summary}")
else:
    session.start_session(session_id="new-session-123")

# Update activity
session.update_activity(
    messages_processed=1,
    context_summary="Discussed project planning in dev-swarm",
)

# Suspend for later
session.suspend_session(
    context_summary="Mid-discussion about API design. Waiting for input."
)
```

## Complete Workflow

### 1. Message Arrives

Server receives message at `POST /swarm/message`:
```python
# Message is persisted to inbox table (idempotent on message_id)
async with db.connection() as conn:
    repo = InboxRepository(conn)
    await repo.insert(inbox_msg)
```

### 2. Wake Trigger Evaluates

The message route evaluates the wake trigger inline (not via external polling):
```python
wake_trigger = getattr(request.app.state, "wake_trigger", None)
if wake_trigger is not None:
    event = await wake_trigger.process_message(message)
    # event.decision is WAKE, QUEUE, or SKIP
```

### 3. Wake Endpoint Invoked

If `event.decision == WakeDecision.WAKE`, the trigger POSTs to the
configured `WAKE_ENDPOINT`. The wake endpoint checks for an active
session and invokes the agent if none is running.

### 4. Claude Activated

The `AgentInvoker` starts the Claude subagent using the configured method.
The subagent receives the wake payload and loads context:
```python
context = await loader.load_context(inbox_message, recent_limit=10)
# context.message, context.swarm, context.is_sender_muted, context.unread_count
```

### 5. Claude Responds

Claude executes action via handler:
```python
if should_reply:
    await handler.send_reply(
        original_message_id=context.message.message_id,
        swarm_id=UUID(context.message.swarm_id),
        content=response_content,
    )
else:
    await handler.acknowledge(context.message.message_id)
```

### 6. Session Updated

Session state persisted for continuity:
```python
session.update_activity(
    messages_processed=1,
    context_summary="Answered question about invite tokens",
)
```

## Environment Variables

### Wake Trigger (WakeConfig)

| Variable | Default | Description |
|----------|---------|-------------|
| `WAKE_ENABLED` | `true` | Enable server-side wake trigger |
| `WAKE_ENDPOINT` | `http://localhost:8080/api/wake` | URL to POST wake notifications |
| `WAKE_TIMEOUT` | `5.0` | HTTP timeout for wake POST (seconds) |

### Wake Endpoint (WakeEndpointConfig)

| Variable | Default | Description |
|----------|---------|-------------|
| `WAKE_EP_ENABLED` | `true` | Mount POST /api/wake endpoint |
| `WAKE_EP_INVOKE_METHOD` | `noop` | Invocation method: sdk, tmux, subprocess, webhook, noop |
| `WAKE_EP_INVOKE_TARGET` | (empty) | Command template or webhook URL (subprocess/webhook only) |
| `WAKE_EP_SECRET` | (empty) | Shared secret for X-Wake-Secret auth |
| `WAKE_EP_SESSION_FILE` | `/root/.swarm/session.json` | Session state file path |
| `WAKE_EP_SESSION_TIMEOUT` | `30` | Session expiry (minutes) |
| `WAKE_EP_SDK_CWD` | `/root/nexus` | Working directory for SDK invocation |
| `WAKE_EP_SDK_PERMISSION_MODE` | `acceptEdits` | SDK permission mode |
| `WAKE_EP_SDK_MAX_TURNS` | (unlimited) | Max conversation turns per SDK invocation |
| `WAKE_EP_SDK_MODEL` | (SDK default) | Model override for SDK invocations |
| `WAKE_EP_TMUX_TARGET` | (empty) | Tmux session/window/pane target (required for tmux method) |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `data/swarm.db` | SQLite database for message persistence |

## Error Handling

All components follow fail-loudly principles:

- **ContextLoaderError**: Database not initialized
- **WakeTriggerError**: Database not initialized or wake endpoint failed
- **ResponseHandlerError**: Database not initialized
- **SessionManagerError**: No active session or corrupted session file

Wake trigger errors in the message route are logged but never block message
acceptance. The message is always persisted and queued regardless of wake
trigger outcome.

## Agent Messaging Quick Reference

When configuring your agent's CLAUDE.md for direct messaging, use the `swarm` CLI commands instead of raw SQL queries. The CLI handles the inbox lifecycle (unread → read → archived → deleted) automatically.

### Reading Messages

```bash
# Read unread messages (auto-marks as read)
swarm messages -s <swarm-id> --status unread --limit 20

# Peek without marking as read
swarm messages -s <swarm-id> --status unread --no-mark-read

# Read all messages (including read/archived)
swarm messages -s <swarm-id> --status all --limit 20

# Quick inbox count
swarm messages -s <swarm-id> --count
```

### Sending Messages

```bash
swarm send --swarm <swarm-id> --to <agent-id> --message "<text>"
```

### Inbox Management

```bash
# Archive all read messages
swarm messages -s <swarm-id> --archive-all

# View sent messages
swarm sent --limit 10
```

### Important Notes

- **Do NOT query `message_queue` directly.** The `message_queue` table is a legacy internal table. All agent-facing messages are stored in the `inbox` table and should be accessed via the CLI or the `/api/inbox` REST API.
- The CLI talks to the FastAPI server's `/api/inbox` endpoints. Ensure your reverse proxy (Angie/nginx) forwards `/api/inbox` and `/api/outbox` to the backend.
- Messages have a lifecycle: `unread` → `read` → `archived` → `deleted`. The CLI auto-marks messages as `read` when displayed (use `--no-mark-read` to prevent this).

## Testing

Run integration tests:
```bash
pytest tests/claude/ -v
```

Test wake trigger in isolation:
```python
# Mock the HTTP client for testing
async def test_wake_trigger():
    with respx.mock:
        respx.post("http://localhost:8080/api/wake").respond(200)

        event = await trigger.process_message(test_message)
        assert event.decision == WakeDecision.WAKE
```
