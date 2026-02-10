# Swarm Operations Specification

**Protocol Version**: 0.1.0

This document specifies all swarm lifecycle operations for the Agent Swarm Protocol.

## Overview

Swarm operations fall into two categories:

| Category | Operations | Network Required |
|----------|------------|------------------|
| Local | Create, Generate Invite | No |
| Remote | Join, Leave, Kick, Transfer Master | Yes |

## 1. Create Swarm

Creates a new swarm. This is a local operation requiring no network communication.

### Request

None (local operation).

### Response

The operation returns the initial swarm state:

```json
{
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-agent-swarm",
  "created_at": "2026-02-05T14:30:00.000Z",
  "master": "agent-001",
  "members": [
    {
      "agent_id": "agent-001",
      "endpoint": "https://agent-001.example.com",
      "public_key": "MCowBQYDK2VwAyEA1234567890abcdef...",
      "joined_at": "2026-02-05T14:30:00.000Z"
    }
  ],
  "settings": {
    "allow_member_invite": false,
    "require_approval": false
  }
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| swarm_id | string (UUID) | Yes | Unique identifier for the swarm |
| name | string | Yes | Human-readable swarm name |
| created_at | string (ISO 8601) | Yes | Timestamp when swarm was created |
| master | string | Yes | agent_id of the swarm creator |
| members | array | Yes | Array of Member objects |
| settings | object | Yes | Swarm configuration settings |

### Error Responses

| Condition | Error |
|-----------|-------|
| Invalid name (empty/too long) | `INVALID_SWARM_NAME` |
| Storage unavailable | `STORAGE_ERROR` |

## 2. Generate Invite

Generates an invite token for the swarm. This is a local operation.

### Request

```json
{
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "expires_in_seconds": 86400,
  "max_uses": 1
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| swarm_id | string (UUID) | Yes | Target swarm |
| expires_in_seconds | integer | No | Token validity period (default: 86400) |
| max_uses | integer or null | No | Maximum uses (null = unlimited) |

### Response

```json
{
  "invite_url": "swarm://550e8400-e29b-41d4-a716-446655440000@agent-001.example.com?token=eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9...",
  "token": "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9...",
  "expires_at": "2026-02-06T14:30:00.000Z",
  "max_uses": 1
}
```

### JWT Payload Structure

```json
{
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "master": "agent-001",
  "endpoint": "https://agent-001.example.com",
  "expires_at": "2026-02-06T14:30:00.000Z",
  "max_uses": 1,
  "iat": 1738766400
}
```

### Error Responses

| Condition | Error |
|-----------|-------|
| Swarm not found | `SWARM_NOT_FOUND` |
| Not swarm master | `NOT_AUTHORIZED` |
| Member invites disabled | `INVITES_DISABLED` |

## 3. Join Swarm

Joins an existing swarm using an invite token. This is a remote operation.

### Endpoint

`POST /swarm/join` on the master's endpoint

### Request

```json
{
  "protocol_version": "0.1.0",
  "message_id": "123e4567-e89b-12d3-a456-426614174000",
  "timestamp": "2026-02-05T15:00:00.000Z",
  "type": "system",
  "action": "join_request",
  "invite_token": "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9...",
  "sender": {
    "agent_id": "agent-002",
    "endpoint": "https://agent-002.example.com",
    "public_key": "MCowBQYDK2VwAyEAabcdef1234567890..."
  },
  "signature": "SGVsbG8gV29ybGQhIFRoaXMgaXMgYSB0ZXN0IHNpZ25hdHVyZQ..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| protocol_version | string | Yes | Protocol version |
| message_id | string (UUID) | Yes | Unique request identifier |
| timestamp | string (ISO 8601) | Yes | Request timestamp |
| type | string | Yes | Must be "system" |
| action | string | Yes | Must be "join_request" |
| invite_token | string | Yes | JWT invite token |
| sender | object | Yes | Joining agent's info |
| signature | string | Yes | Ed25519 signature |

### Success Response (200)

```json
{
  "status": "accepted",
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-agent-swarm",
  "members": [
    {
      "agent_id": "agent-001",
      "endpoint": "https://agent-001.example.com",
      "public_key": "MCowBQYDK2VwAyEA1234567890abcdef...",
      "joined_at": "2026-02-05T14:30:00.000Z"
    },
    {
      "agent_id": "agent-002",
      "endpoint": "https://agent-002.example.com",
      "public_key": "MCowBQYDK2VwAyEAabcdef1234567890...",
      "joined_at": "2026-02-05T15:00:00.000Z"
    }
  ],
  "settings": {
    "allow_member_invite": false,
    "require_approval": false
  }
}
```

### Error Responses

| HTTP | Error Code | Condition |
|------|------------|-----------|
| 400 | `INVALID_TOKEN` | Token malformed or invalid signature |
| 400 | `TOKEN_EXPIRED` | Token has expired |
| 400 | `TOKEN_EXHAUSTED` | Max uses reached |
| 401 | `INVALID_SIGNATURE` | Request signature invalid |
| 403 | `APPROVAL_REQUIRED` | Swarm requires approval (pending) |
| 404 | `SWARM_NOT_FOUND` | Swarm no longer exists |
| 200 | (idempotent) | Agent already in swarm (returns current membership) |

### Idempotent Behavior

If the joining agent is already a member of the swarm, the endpoint returns
200 with the current membership data instead of 409. No `member_joined`
notification is generated for idempotent re-joins. This allows agents to
re-synchronize their local state without side effects.

### Side Effects

On genuinely new joins, the master persists a `member_joined` notification
to the inbox. The notification is fire-and-forget and never blocks
the join response. Master broadcasts `member_joined` notification to all existing members:

```json
{
  "protocol_version": "0.1.0",
  "message_id": "789e0123-e89b-12d3-a456-426614174000",
  "timestamp": "2026-02-05T15:00:01.000Z",
  "sender": {
    "agent_id": "agent-001",
    "endpoint": "https://agent-001.example.com"
  },
  "recipient": "broadcast",
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "system",
  "content": "{\"action\":\"member_joined\",\"member\":{\"agent_id\":\"agent-002\",\"endpoint\":\"https://agent-002.example.com\",\"public_key\":\"MCowBQYDK2VwAyEAabcdef1234567890...\",\"joined_at\":\"2026-02-05T15:00:00.000Z\"}}",
  "signature": "..."
}
```

## 4. Leave Swarm

Voluntarily leaves a swarm. The leaving agent broadcasts to all members.

### Endpoint

`POST /swarm/message` on each member's endpoint

### Request (Broadcast)

```json
{
  "protocol_version": "0.1.0",
  "message_id": "456e7890-e89b-12d3-a456-426614174000",
  "timestamp": "2026-02-05T16:00:00.000Z",
  "sender": {
    "agent_id": "agent-002",
    "endpoint": "https://agent-002.example.com"
  },
  "recipient": "broadcast",
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "system",
  "content": "{\"action\":\"member_left\"}",
  "signature": "..."
}
```

### Success Response (200)

```json
{
  "status": "acknowledged",
  "message_id": "456e7890-e89b-12d3-a456-426614174000"
}
```

### Error Responses

| HTTP | Error Code | Condition |
|------|------------|-----------|
| 401 | `INVALID_SIGNATURE` | Request signature invalid |
| 403 | `NOT_MEMBER` | Sender not in swarm |
| 404 | `SWARM_NOT_FOUND` | Swarm not found |

### Special Case: Master Leaving

If the master leaves without transferring the role:
1. The swarm is dissolved
2. All members receive `swarm_dissolved` notification

```json
{
  "type": "system",
  "content": "{\"action\":\"swarm_dissolved\",\"reason\":\"master_left\"}"
}
```

## 5. Kick Member

Removes a member from the swarm. Only the master can perform this operation.

### Step 1: Notify Kicked Member

`POST /swarm/message` on the kicked member's endpoint

```json
{
  "protocol_version": "0.1.0",
  "message_id": "abc12345-e89b-12d3-a456-426614174000",
  "timestamp": "2026-02-05T17:00:00.000Z",
  "sender": {
    "agent_id": "agent-001",
    "endpoint": "https://agent-001.example.com"
  },
  "recipient": "agent-003",
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "system",
  "content": "{\"action\":\"kicked\",\"reason\":\"Inactive for 30 days\"}",
  "signature": "..."
}
```

### Step 2: Broadcast to Remaining Members

```json
{
  "protocol_version": "0.1.0",
  "message_id": "def67890-e89b-12d3-a456-426614174000",
  "timestamp": "2026-02-05T17:00:01.000Z",
  "sender": {
    "agent_id": "agent-001",
    "endpoint": "https://agent-001.example.com"
  },
  "recipient": "broadcast",
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "system",
  "content": "{\"action\":\"member_kicked\",\"member\":\"agent-003\",\"reason\":\"Inactive for 30 days\"}",
  "signature": "..."
}
```

### Success Response (200)

```json
{
  "status": "acknowledged",
  "message_id": "abc12345-e89b-12d3-a456-426614174000"
}
```

### Error Responses

| HTTP | Error Code | Condition |
|------|------------|-----------|
| 401 | `INVALID_SIGNATURE` | Request signature invalid |
| 403 | `NOT_MASTER` | Sender is not swarm master |
| 404 | `MEMBER_NOT_FOUND` | Target not in swarm |
| 404 | `SWARM_NOT_FOUND` | Swarm not found |

## 6. Transfer Master Role

Transfers the master role to another member.

### Step 1: Notify New Master

`POST /swarm/message` on the new master's endpoint

```json
{
  "protocol_version": "0.1.0",
  "message_id": "fedcba98-e89b-12d3-a456-426614174000",
  "timestamp": "2026-02-05T18:00:00.000Z",
  "sender": {
    "agent_id": "agent-001",
    "endpoint": "https://agent-001.example.com"
  },
  "recipient": "agent-002",
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "system",
  "content": "{\"action\":\"master_transfer\"}",
  "signature": "..."
}
```

### Step 2: New Master Accepts

The new master responds with acceptance:

```json
{
  "status": "accepted",
  "message_id": "fedcba98-e89b-12d3-a456-426614174000"
}
```

### Step 3: Broadcast to All Members

Old master broadcasts master change:

```json
{
  "protocol_version": "0.1.0",
  "message_id": "01234567-e89b-12d3-a456-426614174000",
  "timestamp": "2026-02-05T18:00:01.000Z",
  "sender": {
    "agent_id": "agent-001",
    "endpoint": "https://agent-001.example.com"
  },
  "recipient": "broadcast",
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "system",
  "content": "{\"action\":\"master_changed\",\"old_master\":\"agent-001\",\"new_master\":\"agent-002\"}",
  "signature": "..."
}
```

### Success Response (200)

```json
{
  "status": "acknowledged",
  "message_id": "fedcba98-e89b-12d3-a456-426614174000"
}
```

### Error Responses

| HTTP | Error Code | Condition |
|------|------------|-----------|
| 401 | `INVALID_SIGNATURE` | Request signature invalid |
| 403 | `NOT_MASTER` | Sender is not current master |
| 403 | `TRANSFER_DECLINED` | New master declined the role |
| 404 | `MEMBER_NOT_FOUND` | Target not in swarm |
| 404 | `SWARM_NOT_FOUND` | Swarm not found |

## Error Response Format

All error responses follow this structure:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error description",
    "details": {}
  }
}
```

### Standard Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INVALID_TOKEN` | 400 | Token malformed or tampered |
| `TOKEN_EXPIRED` | 400 | Invite token has expired |
| `TOKEN_EXHAUSTED` | 400 | Token max uses reached |
| `INVALID_SIGNATURE` | 401 | Message signature invalid |
| `NOT_AUTHORIZED` | 403 | Generic authorization failure |
| `NOT_MASTER` | 403 | Operation requires master role |
| `NOT_MEMBER` | 403 | Sender not a swarm member |
| `INVITES_DISABLED` | 403 | Member invites not allowed |
| `APPROVAL_REQUIRED` | 403 | Join requires master approval |
| `TRANSFER_DECLINED` | 403 | New master declined transfer |
| `SWARM_NOT_FOUND` | 404 | Swarm does not exist |
| `MEMBER_NOT_FOUND` | 404 | Target member not in swarm |
| `ALREADY_MEMBER` | ~~409~~ 200 | Agent already in swarm (idempotent: returns current membership) |
| `INVALID_SWARM_NAME` | 400 | Swarm name validation failed |
| `STORAGE_ERROR` | 500 | Persistent storage failure |

## 7. Lifecycle Event Notifications

All membership lifecycle events are recorded as system notifications via
`src/server/notifications.py`. Notifications are persisted to the message
inbox as `InboxMessage` records and are fire-and-forget: they never block
the originating operation.

### Supported Events

| Action | Trigger | Notification Fields |
|--------|---------|---------------------|
| `member_joined` | New member joins (not on re-join) | swarm_id, agent_id |
| `member_left` | Member voluntarily leaves | swarm_id, agent_id |
| `member_kicked` | Master removes member | swarm_id, agent_id, initiated_by, reason |
| `member_muted` | Agent muted in swarm | swarm_id, agent_id, initiated_by, reason |
| `member_unmuted` | Agent unmuted in swarm | swarm_id, agent_id, initiated_by |

### Notification Message Format

Each notification is stored as a system message with this content structure:

```json
{
  "type": "system",
  "action": "member_joined",
  "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
  "agent_id": "agent-002",
  "initiated_by": null,
  "reason": null
}
```

### Integration with Wake Trigger

Lifecycle notifications are persisted to the same inbox used by the
wake trigger. If `WAKE_ENABLED=true`, the wake trigger evaluates these
system messages against the agent's notification preferences. Agents
configured with `SWARM_SYSTEM_MESSAGE` in their wake conditions will be
activated when lifecycle events occur.
