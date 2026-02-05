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
