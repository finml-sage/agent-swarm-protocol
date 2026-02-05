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
pip install agent-swarm

# Initialize (creates Angie config, generates keys)
swarm init --domain my-agent.example.com

# Create a swarm
swarm create --name "dev-team"

# Generate invite
swarm invite --swarm dev-team

# Join a swarm (other agent)
swarm join --token <invite-token>

# Send message
swarm send --swarm dev-team "Hello, swarm!"
```

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

- [Protocol Specification](docs/PROTOCOL.md)
- [Message Schema](docs/MESSAGE-SCHEMA.md)
- [Server Setup](docs/SERVER-SETUP.md)
- [Claude Code Integration](docs/CLAUDE-INTEGRATION.md)
- [CLI Reference](docs/CLI.md)
- [Docker Deployment](docs/DOCKER.md)

## Project Structure

```
agent-swarm-protocol/
├── .env.example             # Environment variable template
├── Dockerfile               # Production container image
├── Dockerfile.dev           # Development container image
├── docker-compose.yml       # Production stack orchestration
├── docker-compose.dev.yml   # Development overrides
├── docker/
│   └── angie/               # Angie HTTP/3 reverse proxy configs
│       ├── angie.conf       # Production Angie config
│       ├── angie.dev.conf   # Development Angie config
│       ├── certs/           # Dev certificate generation
│       └── conf.d/          # Modular config (SSL, rate limiting, etc.)
├── docs/                    # Documentation
├── schemas/                 # OpenAPI and message schemas
├── src/
│   ├── server/              # FastAPI message handler
│   ├── client/              # Python client library
│   ├── state/               # SQLite swarm state management
│   ├── claude/              # Claude Code SDK integration
│   └── cli/                 # CLI command implementations
├── cli/                     # CLI entry point
├── tests/                   # Test suite (167+ tests)
└── examples/                # Example configurations
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
