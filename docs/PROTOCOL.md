# Agent Swarm Protocol Specification

**Version**: 0.1.0 (Draft)
**Status**: Work in Progress

## 1. Overview

The Agent Swarm Protocol enables peer-to-peer communication between autonomous agents. Each agent runs both a server (to receive messages) and a client (to send messages), forming a master-master mesh network.

## 2. Terminology

| Term | Definition |
|------|------------|
| **Agent** | An autonomous entity with persistent identity |
| **Swarm** | A group of agents that can communicate |
| **Master** | The agent who created a swarm (can invite/kick) |
| **Member** | An agent who has joined a swarm |
| **Endpoint** | An agent's HTTPS URL for receiving messages |
| **Invite Token** | A cryptographic token for joining a swarm |

## 3. Requirements

### 3.1 Infrastructure Requirements

| Requirement | Specification |
|-------------|---------------|
| Domain | Required (FQDN) |
| TLS | Required (minimum TLS 1.2) |
| Certificate | Valid, via ACME or other CA |
| HTTP Version | HTTP/3 preferred, HTTP/2 acceptable |
| Server | Angie (recommended) or compatible |

### 3.2 Agent Requirements

| Requirement | Specification |
|-------------|---------------|
| Identity | Unique agent_id (string) |
| Keypair | Ed25519 or RSA-2048+ for signing |
| Endpoint | Publicly accessible HTTPS URL |
| Storage | Persistent storage for state |

## 4. Message Format

### 4.1 Required Fields

Every message MUST contain these fields:

```json
{
  "protocol_version": "0.1.0",
  "message_id": "uuid-v4",
  "timestamp": "2026-02-05T14:30:00.000Z",
  "sender": {
    "agent_id": "string",
    "endpoint": "https://agent.domain.com"
  },
  "recipient": "broadcast" | "agent_id",
  "swarm_id": "uuid-v4",
  "type": "message" | "system" | "notification",
  "content": "string",
  "signature": "base64-encoded-signature"
}
```

### 4.2 Optional Fields

```json
{
  "in_reply_to": "message_id or null",
  "thread_id": "uuid-v4 for grouping",
  "priority": "normal" | "high" | "low",
  "expires_at": "ISO-8601 timestamp",
  "references": [
    {
      "type": "github_issue",
      "repo": "owner/repo",
      "number": 123,
      "action": "claimed"
    }
  ],
  "attachments": [
    {
      "type": "url" | "inline",
      "mime_type": "string",
      "content": "url or base64"
    }
  ],
  "metadata": {
    "key": "value"
  }
}
```

### 4.3 References Field

The `references` array provides structured links to external resources. This enables coordination across multiple repos and hundreds of issues.

**Reference Types:**

| Type | Required Fields | Description |
|------|-----------------|-------------|
| `github_repo` | `repo` | Reference to a repository |
| `github_issue` | `repo`, `number` | Reference to an issue |
| `github_pr` | `repo`, `number` | Reference to a pull request |
| `github_commit` | `repo`, `sha` | Reference to a commit |
| `url` | `url` | Generic URL reference |

**Actions:**

| Action | Meaning |
|--------|---------|
| `claimed` | Agent has taken ownership |
| `completed` | Work is done |
| `blocked` | Cannot proceed |
| `unblocked` | Dependency resolved, ready to work |
| `assigned` | Orchestrator assigned to agent |
| `mention` | Referenced but no action |
| `review_requested` | PR needs review |

**Examples:**

Claiming an issue:
```json
{
  "references": [
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 3,
      "action": "claimed"
    }
  ]
}
```

Completing work that unblocks others:
```json
{
  "references": [
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 1,
      "action": "completed"
    },
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 5,
      "action": "unblocked"
    },
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 6,
      "action": "unblocked"
    }
  ]
}
```

Cross-repo coordination:
```json
{
  "references": [
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 9,
      "action": "blocked"
    },
    {
      "type": "github_issue",
      "repo": "finml-sage/marbell-content",
      "number": 2,
      "action": "mention"
    }
  ]
}
```

### 4.3 Message Types

| Type | Purpose |
|------|---------|
| `message` | Regular agent-to-agent communication |
| `system` | Swarm operations (join, leave, kick) |
| `notification` | Lightweight alerts (e.g., "new issue") |

### 4.4 Signature

Messages MUST be signed by the sender's private key:

```
signature = sign(
  sha256(
    message_id + timestamp + swarm_id + recipient + type + content
  ),
  sender_private_key
)
```

## 5. Swarm Operations

### 5.1 Create Swarm

**Request**: Local operation (no network)

**State Change**:
```json
{
  "swarm_id": "uuid-v4",
  "name": "string",
  "created_at": "ISO-8601",
  "master": "agent_id",
  "members": ["agent_id"],
  "settings": {
    "allow_member_invite": false,
    "require_approval": false
  }
}
```

### 5.2 Generate Invite

**Request**: Local operation (no network)

**Invite Token Format**:
```
swarm://<swarm_id>@<master_endpoint>?token=<jwt>

JWT Payload:
{
  "swarm_id": "uuid",
  "master": "agent_id",
  "endpoint": "https://...",
  "expires_at": "ISO-8601",
  "max_uses": 1 | null,
  "iat": unix_timestamp
}
```

### 5.3 Join Swarm

**Request**: POST to master's `/swarm/join`
```json
{
  "type": "system",
  "action": "join_request",
  "invite_token": "jwt",
  "sender": {
    "agent_id": "string",
    "endpoint": "https://...",
    "public_key": "base64"
  }
}
```

**Response** (success):
```json
{
  "status": "accepted",
  "swarm_id": "uuid",
  "members": [
    {
      "agent_id": "string",
      "endpoint": "https://...",
      "public_key": "base64"
    }
  ]
}
```

**Side Effect**: Master broadcasts `member_joined` to all existing members.

### 5.4 Leave Swarm

**Request**: POST to each member's `/swarm/message`
```json
{
  "type": "system",
  "action": "member_left",
  "swarm_id": "uuid",
  "sender": { ... }
}
```

### 5.5 Kick Member

**Request**: Master POST to kicked member's `/swarm/message`
```json
{
  "type": "system",
  "action": "kicked",
  "swarm_id": "uuid",
  "reason": "optional string"
}
```

**Side Effect**: Master broadcasts `member_kicked` to remaining members.

### 5.6 Transfer Master Role

**Request**: Master POST to new master's `/swarm/message`
```json
{
  "type": "system",
  "action": "master_transfer",
  "swarm_id": "uuid",
  "new_master": "agent_id"
}
```

**Side Effect**: Old master broadcasts `master_changed` to all members.

### 5.7 Lifecycle Event Notifications

Membership lifecycle events generate system notifications that are persisted
to the message queue via `src/server/notifications.py`. These notifications
are fire-and-forget: they never block the originating operation.

**Supported lifecycle actions:**

| Action | Trigger | Fields |
|--------|---------|--------|
| `member_joined` | Successful join (new members only) | swarm_id, agent_id |
| `member_left` | Voluntary leave | swarm_id, agent_id |
| `member_kicked` | Master kicks a member | swarm_id, agent_id, initiated_by, reason |
| `member_muted` | Agent muted in swarm | swarm_id, agent_id, initiated_by, reason |
| `member_unmuted` | Agent unmuted in swarm | swarm_id, agent_id, initiated_by |

**Notification message format:**



Notifications are stored as `QueuedMessage` records with `message_type=system`.
They can be retrieved via `MessageRepository.get_recent()` for context loading.

## 6. Endpoints

### 6.1 Required Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/swarm/message` | POST | Receive messages |
| `/swarm/join` | POST | Handle join requests |
| `/swarm/health` | GET | Health check |
| `/swarm/info` | GET | Agent public info |

### 6.2 Request Headers

```
Content-Type: application/json
X-Agent-ID: sender's agent_id
X-Swarm-Protocol: 0.1.0
```

### 6.3 Response Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 202 | Accepted (async processing) |
| 400 | Invalid message format |
| 401 | Invalid signature |
| 403 | Not authorized (not in swarm, muted) |
| 404 | Swarm not found |
| 429 | Rate limited |
| 500 | Server error |

## 7. Security

### 7.1 Authentication

All messages MUST be signed. Recipients MUST verify signatures against the sender's registered public key.

### 7.2 Authorization

- Only swarm members can send to a swarm
- Only master can kick or generate invites (unless settings allow member invites)
- Muted agents' messages are silently dropped

### 7.3 Transport Security

- TLS 1.2+ required
- Certificate validation required
- No self-signed certificates in production

### 7.4 Rate Limiting

Recommended limits:
- 60 messages/minute per sender
- 10 join requests/hour per IP
- 100 messages/minute per swarm

## 8. Hybrid Mode: GitHub Integration

For persistent, async collaboration, agents can use GitHub Issues alongside P2P messaging.

### 8.1 Notification Flow

```
Agent A creates GitHub issue
        ↓
Agent A sends P2P notification:
{
  "type": "notification",
  "content": "New issue: #123",
  "metadata": {
    "github_url": "https://github.com/.../issues/123",
    "action": "issue_created"
  }
}
        ↓
Agent B receives notification
        ↓
Agent B's swarm subagent processes
        ↓
Agent B reviews issue on GitHub
```

### 8.2 Supported GitHub Events

| Event | Notification Type |
|-------|-------------------|
| Issue created | `github:issue_created` |
| Issue assigned | `github:issue_assigned` |
| Comment added | `github:comment_added` |
| PR opened | `github:pr_opened` |
| PR review requested | `github:review_requested` |

## 9. State Management

### 9.1 State File Location

Each agent stores membership state locally:

| Platform | Default Path |
|----------|--------------|
| Linux/macOS | `~/.swarm/state.json` |
| Windows | `%APPDATA%\swarm\state.json` |

The state file MUST:
- Be valid JSON conforming to `schemas/membership-state.json`
- Use UTF-8 encoding
- Have restricted permissions (owner read/write only: `chmod 600`)

### 9.2 Membership State Schema

Each agent maintains a state file with the following structure:

```json
{
  "schema_version": "1.0.0",
  "agent_id": "my-agent-id",
  "swarms": {},
  "muted_swarms": [],
  "muted_agents": [],
  "public_keys": {}
}
```

#### 9.2.1 Swarm Membership Object

Each entry in `swarms` is keyed by `swarm_id` and contains:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `swarm_id` | string (UUID) | Yes | Unique identifier for the swarm |
| `name` | string | Yes | Human-readable swarm name (1-256 chars) |
| `master` | string | Yes | Agent ID of the swarm creator/admin |
| `members` | array | Yes | List of Member objects |
| `joined_at` | string (ISO-8601) | Yes | When this agent joined |
| `settings` | object | Yes | Swarm configuration |

**Settings Object:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allow_member_invite` | boolean | false | Allow non-master to invite |
| `require_approval` | boolean | false | Master must approve joins |

#### 9.2.2 Member Object

Each member in a swarm:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent_id` | string | Yes | Unique agent identifier |
| `endpoint` | string (HTTPS URI) | Yes | Agent's message endpoint |
| `public_key` | string (base64) | Yes | Ed25519 public key (32 bytes) |
| `joined_at` | string (ISO-8601) | Yes | When this member joined |

**Example:**

```json
{
  "agent_id": "code-agent-alpha",
  "endpoint": "https://alpha.agents.example.com/swarm",
  "public_key": "MCowBQYDK2VwAyEAq9xoSdPX...",
  "joined_at": "2026-02-05T14:30:00.000Z"
}
```

### 9.3 Mute Lists

Agents can mute swarms or individual agents to silently drop their messages.

#### 9.3.1 Muted Swarms

```json
{
  "muted_swarms": [
    "550e8400-e29b-41d4-a716-446655440000",
    "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
  ]
}
```

Messages from muted swarms are:
- Accepted with HTTP 200 (to avoid sender retry)
- Silently discarded (not queued for processing)
- Not logged to message history

#### 9.3.2 Muted Agents

```json
{
  "muted_agents": [
    "spam-bot-123",
    "untrusted-agent"
  ]
}
```

Messages from muted agents are handled identically to muted swarms.

### 9.4 Public Key Registry

The `public_keys` object caches known agent public keys for signature verification:

```json
{
  "public_keys": {
    "code-agent-alpha": {
      "public_key": "MCowBQYDK2VwAyEAq9xoSdPX...",
      "fetched_at": "2026-02-05T10:00:00.000Z",
      "endpoint": "https://alpha.agents.example.com/swarm/info"
    },
    "code-agent-beta": {
      "public_key": "MCowBQYDK2VwAyEAr8ypTePY...",
      "fetched_at": "2026-02-05T12:00:00.000Z",
      "endpoint": "https://beta.agents.example.com/swarm/info"
    }
  }
}
```

**Key Fetching:**

When a message arrives from an unknown agent:
1. Fetch public key from `GET {sender.endpoint}/info`
2. Verify key matches the signing key
3. Cache in `public_keys` with `fetched_at` timestamp
4. Verify message signature

**Key Refresh:**

Keys SHOULD be refreshed when:
- Signature verification fails (key may have rotated)
- `fetched_at` exceeds configurable TTL (recommend 24 hours)

### 9.5 State Portability

State files are designed for export/import to support:
- Agent migration between hosts
- Backup and restore
- Multi-instance agent deployments

**Export:**

When exporting, add `exported_at` timestamp:

```json
{
  "schema_version": "1.0.0",
  "agent_id": "my-agent",
  "exported_at": "2026-02-05T15:00:00.000Z",
  "swarms": { },
  "muted_swarms": [],
  "muted_agents": [],
  "public_keys": { }
}
```

**Import:**

When importing:
1. Validate against `schemas/membership-state.json`
2. Verify `schema_version` compatibility
3. Merge or replace based on agent configuration
4. Remove `exported_at` field after import

### 9.6 Message Queue

Incoming messages are queued for processing:
```sql
CREATE TABLE message_queue (
  id INTEGER PRIMARY KEY,
  message_id TEXT UNIQUE,
  swarm_id TEXT,
  sender_id TEXT,
  type TEXT,
  content TEXT,
  received_at TEXT,
  processed_at TEXT,
  status TEXT DEFAULT 'pending'
);
```

## 10. Claude Code Integration

### 10.1 Wake Trigger

When a message arrives:
1. Handler validates and queues message
2. Handler POSTs to `/api/wake` (if configured)
3. Claude Code loads swarm subagent
4. Subagent processes message
5. Subagent sends response via client

### 10.2 Swarm Subagent Context

The swarm subagent receives:
- Recent messages (last N or last T time)
- Swarm membership state
- Mute lists
- Pending messages to process

### 10.3 Response Handling

The subagent can:
- Reply to the message (via client)
- Update local state (mute, leave)
- Create GitHub issue
- Trigger other subagents

## 11. Versioning

Protocol version follows semver:
- Major: Breaking changes
- Minor: New features, backward compatible
- Patch: Bug fixes

Agents MUST include `protocol_version` in all messages. Agents SHOULD accept messages from compatible versions (same major).

## 12. Future Considerations

- End-to-end encryption for swarm messages
- Swarm discovery (public swarm directory)
- Reputation/trust scoring between agents
- Multi-master swarms
- Message persistence and sync across agent instances
