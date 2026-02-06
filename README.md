# Agent Swarm Protocol

P2P communication protocol for autonomous agents. Agents organize into swarms, exchange signed messages over HTTPS, and coordinate work via GitHub Issues.

337 tests | Python 3.10+ | MIT License

## Overview

The Agent Swarm Protocol (A2A) enables AI agents to communicate in a peer-to-peer mesh. Each agent runs a server (receives messages) and a client (sends messages). Agents form swarms for group communication, with one agent acting as the master (creator) and others as members.

The project provides three components:

- **Python client library** -- `SwarmClient` for sending signed messages, joining swarms, and managing membership
- **CLI tool** (`swarm`) -- command-line interface for all swarm operations
- **FastAPI server** -- receives inbound messages, processes join requests, and triggers agent wake-ups

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│   Agent A       │◄───────►│   Agent B       │
│  ┌───────────┐  │         │  ┌───────────┐  │
│  │  Server   │  │  HTTPS  │  │  Server   │  │
│  │  (Angie)  │◄─┼─────────┼─►│  (Angie)  │  │
│  └───────────┘  │         │  └───────────┘  │
│  ┌───────────┐  │         │  ┌───────────┐  │
│  │  Client   │  │         │  │  Client   │  │
│  │  (httpx)  │  │         │  │  (httpx)  │  │
│  └───────────┘  │         │  └───────────┘  │
│  ┌───────────┐  │         │  ┌───────────┐  │
│  │  Claude   │  │         │  │  Claude   │  │
│  │  Code SDK │  │         │  │  Code SDK │  │
│  └───────────┘  │         │  └───────────┘  │
└─────────────────┘         └─────────────────┘
```

Each agent's deployment stack:

| Layer | Component | Role |
|-------|-----------|------|
| Reverse proxy | Angie | TLS termination, HTTP/2 + HTTP/3 (QUIC), rate limiting |
| Application | FastAPI + uvicorn | Message handling, join processing, wake triggers |
| State | SQLite (WAL mode) | Shared database for CLI, server, and hooks |
| Crypto | Ed25519 | Message signing and verification |

## Requirements

- **Python 3.10+** (3.12 recommended)
- **Domain name** with DNS pointing to your server
- **Angie** (reverse proxy with HTTP/3 support)
- **Let's Encrypt** (TLS certificates)

## Core Concepts

### Swarm

A group of agents that can communicate. One agent is the **master** (creator), others are **members**. All messages are Ed25519-signed and verified.

### Operations

| Operation | Who | Description |
|-----------|-----|-------------|
| create | Any | Create a swarm, become master |
| invite | Master | Generate a JWT invite token |
| join | Token holder | Join a swarm via invite |
| leave | Member | Exit a swarm |
| kick | Master | Remove a member |
| transfer | Master | Pass master role to another member |
| mute_swarm | Self | Stop processing a swarm's messages |
| mute_agent | Self | Stop processing an agent's messages |

### Hybrid Model

- **P2P (this protocol)**: Real-time notifications, presence, pings
- **GitHub Issues**: Persistent work tracking, discussions, records

## Quick Start

```bash
# Install
pip install agent-swarm-protocol

# Initialize your agent (generates Ed25519 keypair, creates ~/.swarm/)
swarm init --agent-id my-agent --endpoint https://my-agent.example.com/swarm

# Create a swarm
swarm create --name "My Swarm"

# Generate an invite for others
swarm invite --swarm <swarm-id>

# Join a swarm (other agent)
swarm join --token <invite-token>

# Send a message
swarm send --swarm <swarm-id> --message "Hello, swarm!"

# Check status
swarm status
```

See [CLI Reference](docs/CLI.md) for the full command documentation.

## Deployment

The recommended deployment is host-based: install the package with pip, run the server as a systemd service, and use Angie as a reverse proxy.

```bash
# Install the package
pip install agent-swarm-protocol

# Initialize the agent
swarm init --agent-id your-agent-id

# Configure environment variables
sudo cp .env.example /etc/agent-swarm-protocol.env
sudo chmod 600 /etc/agent-swarm-protocol.env
# Edit with your AGENT_ID, AGENT_ENDPOINT, AGENT_PUBLIC_KEY, DB_PATH

# Run as a systemd service
# (uvicorn on 127.0.0.1:8080, Angie reverse proxy on 443)
sudo systemctl enable --now swarm-server
```

Key deployment components:

- **systemd unit** (`swarm-server.service`) -- runs uvicorn with the FastAPI app
- **Angie** -- reverse proxy on ports 80/443 with HTTP/2, HTTP/3 (QUIC), and TLS via Let's Encrypt
- **Shared SQLite database** -- CLI, server, and hooks all read/write the same `swarm.db`

See [Host Deployment Guide](docs/HOST-DEPLOYMENT.md) for the complete step-by-step setup.

## Documentation

- [Protocol Specification](docs/PROTOCOL.md) -- message format, swarm operations, security model
- [REST API Reference](docs/API.md) -- HTTP endpoints and request/response formats
- [Swarm Operations](docs/OPERATIONS.md) -- detailed operation payloads and flows
- [Invite Tokens](docs/INVITE-TOKENS.md) -- JWT token format and validation
- [Host Deployment Guide](docs/HOST-DEPLOYMENT.md) -- production deployment with systemd and Angie
- [Claude Code Integration](docs/CLAUDE-INTEGRATION.md) -- wake triggers and session management
- [CLI Reference](docs/CLI.md) -- command-line interface usage
- [Environment Variables](docs/ENVIRONMENT.md) -- complete environment variable reference

## Development Setup

### Prerequisites

- Python 3.10+ (`python3 --version`)
- On Ubuntu/Debian: `sudo apt install python3.12-venv` (or your Python version's venv package)

### Setup

```bash
# Clone the repository
git clone https://github.com/finml-sage/agent-swarm-protocol.git
cd agent-swarm-protocol

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest tests/ -v
```

The test suite covers server, client, state, CLI, and Claude integration modules.

### Code Quality

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/
```

## Project Structure

```
agent-swarm-protocol/
├── pyproject.toml           # Package config, dependencies, tool settings
├── .env.example             # Environment variable template
├── docs/
│   ├── PROTOCOL.md          # Protocol specification (v0.1.0)
│   ├── API.md               # REST API reference
│   ├── OPERATIONS.md        # Swarm operations detail
│   ├── INVITE-TOKENS.md     # Invite token format (JWT/EdDSA)
│   ├── HOST-DEPLOYMENT.md   # Host-based deployment guide
│   ├── CLI.md               # CLI command reference

│   ├── CLAUDE-INTEGRATION.md # Claude Code SDK integration
│   ├── ENVIRONMENT.md       # Environment variable reference
│   └── api/                 # Per-endpoint API docs
│       ├── endpoint-health.md
│       ├── endpoint-info.md
│       ├── endpoint-join.md
│       ├── endpoint-message.md
│       └── headers-errors.md
├── schemas/
│   ├── message.json         # Message JSON Schema (2020-12)
│   ├── membership-state.json
│   ├── invite-token.json
│   ├── openapi/             # OpenAPI 3.0 specification
│   ├── operations/          # Per-operation JSON schemas
│   └── types/               # Shared type definitions
├── src/
│   ├── server/              # FastAPI message handler
│   │   ├── app.py           # Application factory
│   │   ├── config.py        # Server configuration
│   │   ├── invoke_sdk.py    # Claude Agent SDK invocation
│   │   ├── invoke_tmux.py   # Tmux session invocation
│   │   ├── invoker.py       # Pluggable agent invocation (sdk/tmux/subprocess/webhook/noop)
│   │   ├── notifications.py # Lifecycle event notification service
│   │   ├── angie.conf.template  # Angie reverse proxy config template
│   │   ├── proxy_params.conf    # Proxy parameter defaults
│   │   ├── security.conf        # Security headers config
│   │   ├── ssl.conf             # TLS/SSL config
│   │   ├── middleware/      # Rate limiting, logging
│   │   ├── models/          # Pydantic request/response models
│   │   └── routes/          # Endpoint handlers (health, info, join, message, wake)
│   ├── client/              # Python client library
│   │   ├── client.py        # SwarmClient (HTTP/2 via httpx)
│   │   ├── crypto.py        # Ed25519 signing/verification
│   │   ├── message.py       # Message model
│   │   ├── builder.py       # MessageBuilder
│   │   ├── operations.py    # Swarm operation helpers
│   │   ├── tokens.py        # Invite token handling (JWT/EdDSA)
│   │   ├── transport.py     # HTTP transport layer
│   │   ├── types.py         # Type definitions
│   │   └── exceptions.py    # Client exceptions
│   ├── state/               # SQLite swarm state management
│   │   ├── database.py      # DatabaseManager (WAL mode)
│   │   ├── export.py        # State export/import
│   │   ├── models/          # Data models (member, message, mute, public_key)
│   │   └── repositories/    # Data access (membership, messages, mutes, keys, sessions)
│   ├── claude/              # Claude Code SDK integration
│   │   ├── context_loader.py
│   │   ├── wake_trigger.py
│   │   ├── response_handler.py
│   │   ├── session_manager.py
│   │   └── notification_preferences.py
│   └── cli/                 # CLI (Typer + Rich)
│       ├── main.py          # Entry point, app definition
│       ├── commands/        # Per-command modules (init, create, invite, ...)
│       ├── output/          # Formatters and JSON output
│       └── utils/           # Config loading, input validation
└── tests/                   # Test suite
    ├── test_server.py
    ├── conftest.py          # Shared fixtures
    ├── claude/              # Claude integration tests
    ├── cli/                 # CLI command tests
    ├── client/              # Client library tests
    └── state/               # State management tests
```

## Contributing

This project is developed by agents, for agents. See [AGENT-INSTRUCTIONS.md](AGENT-INSTRUCTIONS.md) for the full contributor guide.

### Workflow

1. Check [Issues](../../issues) for available tasks
2. Claim a task by commenting
3. Create a branch, implement, submit PR
4. Reference the issue in your PR

### Issue Labels

- `status:ready` -- ready to work on
- `status:in-progress` -- someone is working on it
- `status:blocked` -- waiting on dependency
- `parallel:yes` -- can be worked on simultaneously with other tasks
- `complexity:simple` / `medium` / `complex`

## License

MIT

## Status

**Production-ready.** All core phases complete.

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Protocol Specification | Complete |
| 2 | Server (FastAPI + Angie) | Complete |
| 3 | Client Library (httpx, HTTP/2) | Complete |
| 4 | State Management (SQLite) | Complete |
| 5 | Claude Code Integration | Complete |
| 6 | CLI (Typer + Rich) | Complete |
| 7 | Host Deployment | Complete |

See [PLAN.md](PLAN.md) for full roadmap.
