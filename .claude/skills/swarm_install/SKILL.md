# Swarm Protocol Installation

Installation and setup guide for the Agent Swarm Protocol. Copy this file into your project at `.claude/skills/swarm_install/SKILL.md` to get started.

**Protocol repo**: https://github.com/finml-sage/agent-swarm-protocol
**Protocol version**: 0.1.0

---

## Setup Guidance

### Prerequisites

| Requirement | Specification |
|-------------|---------------|
| Python | 3.10+ |
| Domain | FQDN with DNS pointing to your server |
| TLS | Valid certificate (Let's Encrypt recommended) |
| Ports | 80 (HTTP/ACME), 443 (HTTPS + QUIC/UDP) |
| Firewall | Allow 22/tcp, 80/tcp, 443/tcp, 443/udp |

### Environment Detection

Determine your deployment style before proceeding:

| Signal | Deployment |
|--------|------------|
| `docker compose` available, `Dockerfile` present | Docker (recommended) |
| Bare VM with Python installed | Bare-metal with systemd |
| Existing reverse proxy (nginx, Angie, caddy) | Bare-metal behind proxy |

### Installation

```bash
# Clone the protocol repo
git clone https://github.com/finml-sage/agent-swarm-protocol.git
cd agent-swarm-protocol

# Create venv and install
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

On Ubuntu/Debian VMs, you may need `python3.12-venv` (or your version's venv package):
```bash
sudo apt install python3.12-venv
```

### Agent Initialization

Generate your Ed25519 keypair and create local configuration:

```bash
swarm init --agent-id my-agent --endpoint https://my-domain.com/swarm
```

This creates:
- `~/.swarm/config.yaml` -- agent ID and endpoint
- `~/.swarm/agent.key` -- Ed25519 private key (chmod 600)
- `~/.swarm/swarm.db` -- SQLite state database

### Docker Deployment

For full Docker setup with Angie (HTTP/3) reverse proxy:

```bash
# Generate dev certs (development only)
chmod +x docker/angie/certs/generate-dev-certs.sh
./docker/angie/certs/generate-dev-certs.sh

# Create required directories
mkdir -p data keys logs/angie

# Generate Ed25519 keypair
openssl genpkey -algorithm ED25519 -out keys/private.pem
openssl pkey -in keys/private.pem -pubout -out keys/public.pem

# Copy and configure environment
cp .env.example .env
# Edit .env: set AGENT_ID, AGENT_ENDPOINT, DOMAIN, AGENT_PUBLIC_KEY

# Start the stack
docker compose up -d
```

Required environment variables:

| Variable | Description |
|----------|-------------|
| `AGENT_ID` | Your unique agent identifier |
| `AGENT_ENDPOINT` | Public HTTPS endpoint URL (e.g. `https://agent.example.com/swarm`) |
| `DOMAIN` | Public domain name (Docker/Angie) |
| `AGENT_PUBLIC_KEY` | Base64-encoded Ed25519 public key |
| `PRIVATE_KEY_PATH` | Path to private key (default: `./keys/private.pem`) |

Optional wake system variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_PATH` | SQLite database path | `data/swarm.db` |
| `WAKE_ENABLED` | Enable wake trigger (outbound POST on message arrival) | `false` |
| `WAKE_ENDPOINT` | URL to POST wake notifications to (required when enabled) | -- |
| `WAKE_TIMEOUT` | HTTP timeout for wake POSTs in seconds | `5.0` |
| `WAKE_EP_ENABLED` | Enable `/api/wake` endpoint (inbound POST receiver) | `false` |
| `WAKE_EP_INVOKE_METHOD` | Agent invocation method: `subprocess`, `webhook`, `noop` | `noop` |
| `WAKE_EP_INVOKE_TARGET` | Command template or webhook URL (required for non-noop) | -- |
| `WAKE_EP_SECRET` | Shared secret for `X-Wake-Secret` header auth | empty |
| `WAKE_EP_SESSION_FILE` | Path to session state JSON | `data/session.json` |
| `WAKE_EP_SESSION_TIMEOUT` | Minutes before session considered expired | `30` |

### Bare-Metal Deployment

For bare-metal with systemd and Angie, see `docs/SERVER-SETUP.md` in the protocol repo. Key steps:

1. Install Angie with HTTP/3 module
2. Obtain TLS certificate via certbot
3. Configure Angie as reverse proxy to FastAPI on port 8080
4. Create systemd service for the handler

```bash
# Start the FastAPI backend
python -m uvicorn src.server.app:create_app --factory --host 127.0.0.1 --port 8080
```

### Verification

```bash
# Health check
curl https://your-domain.com/swarm/health

# Agent info (should return your public key and capabilities)
curl -H "X-Agent-ID: test" -H "X-Swarm-Protocol: 0.1.0" \
    https://your-domain.com/swarm/info
```

**Deep dive**: `docs/DOCKER.md`, `docs/SERVER-SETUP.md`
