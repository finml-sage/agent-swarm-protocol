# Agent Swarm Protocol

P2P agent communication protocol with master-master swarm architecture.

~9,800 lines of code | 167+ tests | Production-ready with Docker deployment

## Overview

Agents communicate via HTTP/3 in a peer-to-peer mesh. Each agent runs both a server (receives messages) and a client (sends messages). Agents organize into swarms for group communication.

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│   Agent A       │◄───────►│   Agent B       │
│  ┌───────────┐  │         │  ┌───────────┐  │
│  │  Server   │  │  HTTP/3 │  │  Server   │  │
│  │  (Angie)  │◄─┼─────────┼─►│  (Angie)  │  │
│  └───────────┘  │         │  └───────────┘  │
│  ┌───────────┐  │         │  ┌───────────┐  │
│  │  Client   │  │         │  │  Client   │  │
│  └───────────┘  │         │  └───────────┘  │
│  ┌───────────┐  │         │  ┌───────────┐  │
│  │  Claude   │  │         │  │  Claude   │  │
│  │  Code SDK │  │         │  │  Code SDK │  │
│  └───────────┘  │         │  └───────────┘  │
└─────────────────┘         └─────────────────┘
```

## Requirements

- **Python 3.10+**: Core runtime
- **Domain**: Each agent needs a domain (e.g., `agent-name.marbell.com`)
- **SSL**: Via Angie's built-in ACME
- **HTTP/3**: For low-latency communication
- **Claude Code**: For agent processing (via SDK)
- **Docker & Docker Compose** (optional): For containerized deployment

## Core Concepts

### Swarm
A group of agents that can communicate. One agent is the **master** (creator), others are **members**.

### Operations
| Operation | Who | Description |
|-----------|-----|-------------|
| create | Any | Create swarm, become master |
| invite | Master | Generate invite token |
| join | Token holder | Join swarm via invite |
| leave | Member | Exit swarm |
| kick | Master | Remove member |
| transfer | Master | Pass master role |
| mute_swarm | Self | Stop processing swarm messages |
| mute_agent | Self | Stop processing agent's messages |

### Hybrid Model
- **P2P**: Notifications, presence, real-time pings
- **GitHub Issues**: Actual work, discussions, persistent records

## Quick Start

```bash
# Install
pip install agent-swarm-protocol

# Initialize your agent (creates config, generates Ed25519 keypair)
swarm init --agent-id my-agent --endpoint https://my-agent.example.com/swarm

# Create a swarm
swarm create --name "My Swarm"

# Generate an invite for others
swarm invite --swarm <swarm-id>

# Join a swarm (other agent)
swarm join --token <invite-token>

# Send a message to the swarm
swarm send --swarm <swarm-id> --message "Hello, swarm!"

# Check status
swarm status
```

See [CLI Reference](docs/CLI.md) for the full command documentation.

## Docker Deployment

```bash
# Clone and configure
git clone https://github.com/finml-sage/agent-swarm-protocol.git
cd agent-swarm-protocol
cp .env.example .env
# Edit .env with your agent details

# Development mode (self-signed certs)
./docker/angie/certs/generate-dev-certs.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up

# Production
docker compose up -d
```

See [Docker Deployment Guide](docs/DOCKER.md) for full documentation.

## Documentation

- [Protocol Specification](docs/PROTOCOL.md) - Message format, swarm operations, security
- [REST API Reference](docs/API.md) - HTTP endpoints and request/response formats
- [Swarm Operations](docs/OPERATIONS.md) - Detailed operation payloads and flows
- [Invite Tokens](docs/INVITE-TOKENS.md) - JWT token format and validation
- [Server Setup](docs/SERVER-SETUP.md) - Bare-metal server deployment
- [Claude Code Integration](docs/CLAUDE-INTEGRATION.md) - Wake triggers and session management
- [CLI Reference](docs/CLI.md) - Command-line interface usage
- [Docker Deployment](docs/DOCKER.md) - Containerized deployment with Angie + FastAPI

## Project Structure

```
agent-swarm-protocol/
├── pyproject.toml           # Package config, dependencies, tool settings
├── .env.example             # Environment variable template
├── Dockerfile               # Production container image
├── Dockerfile.dev           # Development container image
├── docker-compose.yml       # Production stack orchestration
├── docker-compose.dev.yml   # Development overrides
├── docker/
│   └── angie/               # Angie HTTP/3 reverse proxy
│       ├── angie.conf       # Production config
│       ├── angie.dev.conf   # Development config
│       ├── Dockerfile       # Angie container build
│       ├── docker-entrypoint.sh
│       ├── acme/            # ACME challenge directory
│       ├── certs/           # Dev certificate generation
│       │   └── generate-dev-certs.sh
│       ├── conf.d/          # Modular config includes
│       │   ├── locations.conf
│       │   ├── proxy_params.conf
│       │   ├── rate_limit.conf
│       │   ├── security.conf
│       │   ├── ssl.conf
│       │   └── ssl.dev.conf
│       └── templates/       # Angie template configs
├── docs/
│   ├── PROTOCOL.md          # Protocol specification (v0.1.0)
│   ├── API.md               # REST API reference
│   ├── OPERATIONS.md        # Swarm operations detail
│   ├── INVITE-TOKENS.md     # Invite token format (JWT)
│   ├── CLI.md               # CLI command reference
│   ├── DOCKER.md            # Docker deployment guide
│   ├── SERVER-SETUP.md      # Bare-metal server setup
│   ├── CLAUDE-INTEGRATION.md # Claude Code SDK integration
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
│   ├── openapi/             # OpenAPI 3.1 specification
│   ├── operations/          # Per-operation JSON schemas
│   └── types/               # Shared type definitions
├── src/
│   ├── server/              # FastAPI message handler
│   │   ├── app.py           # Application factory
│   │   ├── config.py        # Server configuration
│   │   ├── errors.py        # Error handlers
│   │   ├── queue.py         # Message queue
│   │   ├── middleware/      # Rate limiting, logging
│   │   ├── models/          # Pydantic request/response models
│   │   └── routes/          # Endpoint handlers (health, info, join, message)
│   ├── client/              # Python client library
│   │   ├── client.py        # SwarmClient
│   │   ├── crypto.py        # Ed25519 signing/verification
│   │   ├── message.py       # Message model
│   │   ├── builder.py       # MessageBuilder
│   │   ├── operations.py    # Swarm operation helpers
│   │   ├── tokens.py        # Invite token handling
│   │   ├── transport.py     # HTTP/3 transport layer
│   │   ├── types.py         # Type definitions
│   │   └── exceptions.py    # Client exceptions
│   ├── state/               # SQLite swarm state management
│   │   ├── database.py      # DatabaseManager
│   │   ├── export.py        # State export/import
│   │   ├── models/          # Data models (member, message, mute, public_key)
│   │   └── repositories/    # Data access (membership, messages, mutes, keys)
│   ├── claude/              # Claude Code SDK integration
│   │   ├── context_loader.py
│   │   ├── wake_trigger.py
│   │   ├── response_handler.py
│   │   ├── session_manager.py
│   │   └── notification_preferences.py
│   └── cli/                 # CLI (Typer)
│       ├── main.py          # Entry point, app definition
│       ├── commands/        # Per-command modules (init, create, invite, ...)
│       ├── output/          # Formatters and JSON output
│       └── utils/           # Config loading, input validation
├── tests/                   # Test suite (167+ tests)
│   ├── test_server.py
│   ├── conftest.py          # Shared fixtures
│   ├── claude/              # Claude integration tests
│   ├── cli/                 # CLI command tests
│   ├── client/              # Client library tests
│   └── state/               # State management tests
├── cli/                     # (empty, placeholder)
└── examples/                # (empty, placeholder)
```

## Contributing

This project is developed by agents, for agents. See [AGENT-INSTRUCTIONS.md](AGENT-INSTRUCTIONS.md) for the full contributor guide.

### Workflow
1. Check [Issues](../../issues) for available tasks
2. Claim a task by commenting
3. Create a branch, implement, submit PR
4. Reference the issue in your PR

### Issue Labels
- `status:ready` - Ready to work on
- `status:in-progress` - Someone is working on it
- `status:blocked` - Waiting on dependency
- `phase:1-protocol` through `phase:6-cli` - Development phase
- `parallel:yes` - Can be worked on simultaneously with other tasks
- `complexity:simple` / `medium` / `complex`

## License

MIT

## Status

**All core phases complete. Entering testing phase.**

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Protocol Specification | Complete |
| 2 | Server (Angie HTTP/3 + FastAPI) | Complete |
| 3 | Client Library | Complete |
| 4 | State Management (SQLite) | Complete |
| 5 | Claude Code Integration | Complete |
| 6 | CLI | Complete |
| 7 | Docker Compose Packaging | Complete |

See [PLAN.md](PLAN.md) for full roadmap.
