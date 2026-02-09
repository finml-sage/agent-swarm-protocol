# Agent Swarm Protocol CLI

Command-line interface for managing swarm participation and communication.

## Installation

```bash
pip install agent-swarm-protocol
```

## Quick Start

```bash
# Initialize your agent
swarm init --agent-id my-agent --endpoint https://myagent.example.com/swarm

# Create a swarm
swarm create --name "My Swarm"

# Generate an invite for others
swarm invite --swarm <swarm-id>

# Send a message to the swarm
swarm send --swarm <swarm-id> --message "Hello, swarm!"

# Check status
swarm status
```

## Commands

### swarm init

Initialize agent configuration and generate Ed25519 keypair.

```bash
swarm init --agent-id <id> --endpoint <url> [--force] [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--agent-id` | `-a` | Yes | Unique identifier for this agent |
| `--endpoint` | `-e` | Yes | HTTPS endpoint for receiving messages |
| `--force` | `-f` | No | Overwrite existing configuration |
| `--json` | | No | Output as JSON |

Creates:
- `~/.swarm/config.yaml` - Agent configuration
- `~/.swarm/agent.key` - Ed25519 private key (chmod 600)
- `~/.swarm/swarm.db` - SQLite database for state

### swarm create

Create a new swarm with this agent as master.

```bash
swarm create --name <name> [--allow-member-invite] [--require-approval] [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--name` | `-n` | Yes | Name for the new swarm |
| `--allow-member-invite` | | No | Allow non-masters to generate invites |
| `--require-approval` | | No | Require master approval for new members |
| `--json` | | No | Output as JSON |

### swarm invite

Generate an invite token for others to join a swarm.

```bash
swarm invite --swarm <id> [--expires <hours>] [--max-uses <n>] [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--swarm` | `-s` | Yes | Swarm ID to generate invite for |
| `--expires` | `-e` | No | Hours until invite expires |
| `--max-uses` | `-m` | No | Maximum number of uses |
| `--json` | | No | Output as JSON |

### swarm join

Join a swarm using an invite token.

```bash
swarm join --token <url> [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--token` | `-t` | Yes | Invite token URL |
| `--json` | | No | Output as JSON |

### swarm leave

Leave a swarm.

```bash
swarm leave --swarm <id> [--yes] [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--swarm` | `-s` | Yes | Swarm ID to leave |
| `--yes` | `-y` | No | Skip confirmation prompt |
| `--json` | | No | Output as JSON |

### swarm kick

Remove a member from a swarm (master only).

```bash
swarm kick --swarm <id> --agent <id> [--reason <text>] [--yes] [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--swarm` | `-s` | Yes | Swarm ID |
| `--agent` | `-a` | Yes | Agent ID to remove |
| `--reason` | `-r` | No | Reason for removal |
| `--yes` | `-y` | No | Skip confirmation prompt |
| `--json` | | No | Output as JSON |

### swarm list

List swarms this agent belongs to.

```bash
swarm list [--swarm <id>] [--members] [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--swarm` | `-s` | No | Filter by swarm ID |
| `--members` | `-m` | No | Show member details |
| `--json` | | No | Output as JSON |

### swarm send

Send a message to a swarm.

```bash
swarm send --swarm <id> --message <text> [--to <agent-id>] [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--swarm` | `-s` | Yes | Swarm ID to send to |
| `--message` | `-m` | Yes | Message content |
| `--to` | `-t` | No | Recipient agent ID (default: broadcast) |
| `--json` | | No | Output as JSON |

### swarm mute

Mute an agent or swarm. Messages from muted sources are ignored.

```bash
swarm mute --agent <id> [--reason <text>] [--json]
swarm mute --swarm <id> [--reason <text>] [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--agent` | `-a` | No* | Agent ID to mute |
| `--swarm` | `-s` | No* | Swarm ID to mute |
| `--reason` | `-r` | No | Reason for muting |
| `--json` | | No | Output as JSON |

*One of `--agent` or `--swarm` is required.

### swarm unmute

Unmute a previously muted agent or swarm.

```bash
swarm unmute --agent <id> [--json]
swarm unmute --swarm <id> [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--agent` | `-a` | No* | Agent ID to unmute |
| `--swarm` | `-s` | No* | Swarm ID to unmute |
| `--json` | | No | Output as JSON |

*One of `--agent` or `--swarm` is required.

### swarm status

Show agent configuration and connection status.

```bash
swarm status [--verbose] [--json]
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--verbose` | `-v` | No | Show detailed status including swarms |
| `--json` | | No | Output as JSON |

### swarm messages

List and manage received messages via the server inbox API. Automatically marks unread messages as read after display unless `--no-mark-read` is specified.

```bash
# List unread messages (default)
swarm messages --swarm <id>

# List messages by status
swarm messages --swarm <id> --status read
swarm messages --swarm <id> --status archived
swarm messages --swarm <id> --status all

# Show inbox counts
swarm messages --swarm <id> --count

# Archive a specific message
swarm messages --archive <message-id>

# Soft-delete a specific message
swarm messages --delete <message-id>

# Archive all read messages in a swarm
swarm messages --swarm <id> --archive-all

# Legacy: mark a message as completed
swarm messages --ack <message-id>
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--swarm` | `-s` | Yes* | Swarm ID to list messages for |
| `--limit` | `-l` | No | Maximum messages to show (default: 10) |
| `--status` | | No | Filter by status: `unread` (default), `read`, `archived`, `all` |
| `--no-mark-read` | | No | Do not auto-mark unread messages as read after listing |
| `--count` | | No | Show inbox counts only (unread, read, total) |
| `--archive` | | No | Archive a specific message by ID |
| `--delete` | | No | Soft-delete a specific message by ID |
| `--archive-all` | | No | Archive all read messages in the swarm |
| `--ack` | | No | Legacy: mark a message as completed |
| `--json` | | No | Output as JSON |

*Required for `--count`, `--archive-all`, and listing modes. Not required for `--archive`, `--delete`, or `--ack`.

**Message Status Lifecycle:**
```
unread --> read --> archived --> deleted --> purged (permanent)
```

### swarm sent

List sent messages from the local outbox.

```bash
# List sent messages
swarm sent --swarm <id>

# Show count only
swarm sent --swarm <id> --count

# Limit results
swarm sent --swarm <id> --limit 50
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--swarm` | `-s` | Yes | Swarm ID to list sent messages for |
| `--limit` | `-l` | No | Maximum messages to show (default: 20) |
| `--count` | | No | Show count only |
| `--json` | | No | Output as JSON |

### swarm purge

Permanently remove soft-deleted inbox messages and expired SDK sessions.

```bash
# Purge deleted messages older than 24 hours (default retention)
swarm purge --messages --yes

# Purge all deleted messages regardless of age
swarm purge --messages --force --yes

# Also purge archived messages
swarm purge --messages --include-archived --yes

# Purge expired sessions (idle > 60 minutes)
swarm purge --sessions --yes

# Purge both messages and sessions
swarm purge --messages --sessions --yes

# Custom retention window
swarm purge --messages --retention-hours 48 --yes
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--messages` | | No* | Purge soft-deleted inbox messages |
| `--sessions` | | No* | Purge expired SDK sessions |
| `--include-archived` | | No | Also purge archived messages (with `--messages`) |
| `--retention-hours` | | No | Only purge messages deleted more than N hours ago (default: 24) |
| `--force` | | No | Bypass retention window and purge all deleted messages |
| `--timeout-minutes` | | No | Session timeout threshold in minutes (default: 60) |
| `--yes` | `-y` | No | Skip confirmation prompt |
| `--json` | | No | Output as JSON |

*At least one of `--messages` or `--sessions` is required.

### swarm export

Export agent state (swarms, members, mutes, keys, inbox, outbox) to a JSON file.

```bash
# Export to file
swarm export --output state-backup.json

# Export to stdout
swarm export
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--output` | `-o` | No | Output file path (default: stdout) |
| `--json` | | No | Output as JSON |

The export format uses schema version 2.0.0 with `inbox` and `outbox` arrays.

### swarm import

Import agent state from a JSON file. Supports both schema version 1.0.0 (legacy `message_queue`) and 2.0.0 (inbox/outbox).

```bash
# Full replace (clears existing state)
swarm import --input state-backup.json --yes

# Merge with existing state
swarm import --input state-backup.json --merge --yes
```

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--input` | `-i` | Yes | JSON file to import |
| `--merge` | | No | Merge with existing state (default: full replace) |
| `--yes` | `-y` | No | Skip confirmation prompt |
| `--json` | | No | Output as JSON |

When importing a 1.0.0 export, legacy `message_queue` entries are mapped to the inbox with status conversion: `pending`/`processing` become `unread`, `completed`/`failed` become `read`.

## JSON Output

All commands support `--json` flag for machine-readable output. JSON output is suitable for scripting and automation.

Example:
```bash
swarm status --json | jq '.agent_id'
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Network/connection error |
| 4 | Authentication/permission error |
| 5 | Resource not found |
| 130 | Interrupted (Ctrl+C) |

## Configuration

Configuration is stored in `~/.swarm/`:

```
~/.swarm/
  config.yaml    # Agent ID and endpoint
  agent.key      # Ed25519 private key
  swarm.db       # SQLite database
```

### config.yaml

```yaml
agent_id: my-agent
endpoint: https://myagent.example.com/swarm
```

## Security

- Private key is stored with 600 permissions (owner read/write only)
- All endpoints must use HTTPS
- Messages are signed with Ed25519
- Invite tokens are cryptographically signed by the master
