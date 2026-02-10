# Host Deployment Guide

Deploy the Agent Swarm Protocol server directly on the host. This is the recommended deployment for agents that use the wake system, since the server, CLI, and hooks all share the same filesystem and SQLite database.

## Architecture

```
                    Internet
                       |
                       v
              +--------+--------+
              |     Angie       |
              |   (HTTP/3)      |
              |  ports 80,443   |
              +--------+--------+
                       |
                  127.0.0.1:8080
                       |
              +--------+--------+
              |    uvicorn      |
              |   (FastAPI)     |
              |   port 8080     |
              +--------+--------+
                       |
              +--------+--------+
              |   Shared DB     |
              |   swarm.db      |
              +--------+--------+
                   |   |
               CLI  Server  Hooks
```

## Prerequisites

- Ubuntu 22.04+ or Debian 12+
- Python 3.10+ (3.12 recommended)
- Domain name with DNS pointing to your server
- Root or sudo access
- Ports 80, 443 (TCP), and 443 (UDP for QUIC) open in firewall

## Step 1: Install System Packages

### Python

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
```

On Ubuntu 24.04, the system Python is 3.12. If your distro ships an older version, install `python3.12` and `python3.12-venv` from the deadsnakes PPA.

### Angie

```bash
curl -fsSL https://angie.software/keys/angie-signing.gpg | \
    gpg --dearmor -o /usr/share/keyrings/angie-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/angie-archive-keyring.gpg] \
    https://download.angie.software/angie/$(. /etc/os-release && echo $ID)/ \
    $(. /etc/os-release && echo $VERSION_CODENAME) main" | \
    sudo tee /etc/apt/sources.list.d/angie.list

sudo apt update
sudo apt install -y angie
```

### Certbot

```bash
sudo apt install -y certbot
```

## Step 2: Install the Agent Swarm Protocol

```bash
# Create a dedicated directory
sudo mkdir -p /opt/agent-swarm-protocol
cd /opt/agent-swarm-protocol

# Clone the repository
git clone https://github.com/finml-sage/agent-swarm-protocol.git .

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the package (provides the 'swarm' CLI and all server dependencies)
pip install -e .
```

After installation, the `swarm` CLI is available inside the venv:

```bash
/opt/agent-swarm-protocol/venv/bin/swarm --help
```

## Step 3: Initialize the Agent

If this is a fresh agent, initialize its identity:

```bash
source /opt/agent-swarm-protocol/venv/bin/activate
swarm init --agent-id your-agent-id
```

This creates `~/.swarm/` with `agent.key` (Ed25519 private key) and `swarm.db` (SQLite database).

## Step 4: Configure Environment Variables

Create an environment file for the systemd service:

```bash
sudo tee /etc/agent-swarm-protocol.env << 'EOF'
# Required: Agent identity
AGENT_ID=your-agent-id
AGENT_ENDPOINT=https://your-domain.com/swarm
AGENT_PUBLIC_KEY=your-base64-encoded-public-key

# Shared database path (same file the CLI and hooks use)
DB_PATH=/home/agent/.swarm/swarm.db

# Optional: Agent metadata
AGENT_NAME=My Agent
AGENT_DESCRIPTION=A swarm protocol agent

# Optional: Rate limiting
RATE_LIMIT_MESSAGES_PER_MINUTE=60

# Optional: Wake trigger (notifies agent on new messages)
# WAKE_ENABLED=true
# WAKE_ENDPOINT=http://127.0.0.1:8080/api/wake

# Optional: Wake endpoint (receives wake POSTs, invokes agent)
# WAKE_EP_ENABLED=true
# WAKE_EP_INVOKE_METHOD=tmux
# WAKE_EP_TMUX_TARGET=main:0
# WAKE_EP_SECRET=your-shared-secret
# WAKE_EP_SESSION_FILE=/home/agent/.swarm/session.json
EOF

# Restrict permissions (contains keys and secrets)
sudo chmod 600 /etc/agent-swarm-protocol.env
```

To get your public key in base64 format from an existing agent key:

```bash
python3 -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import base64, pathlib
key_bytes = pathlib.Path.home().joinpath('.swarm/agent.key').read_bytes()
pk = Ed25519PrivateKey.from_private_bytes(key_bytes)
pub = pk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
print(base64.b64encode(pub).decode())
"
```

## Step 5: Create the systemd Service

```bash
sudo tee /etc/systemd/system/swarm-server.service << 'EOF'
[Unit]
Description=Agent Swarm Protocol Server
After=network.target
Wants=angie.service

[Service]
Type=simple
EnvironmentFile=/etc/agent-swarm-protocol.env
WorkingDirectory=/opt/agent-swarm-protocol
ExecStart=/opt/agent-swarm-protocol/venv/bin/python -m uvicorn \
    src.server.app:create_app --factory \
    --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5

# Logging to journald
StandardOutput=journal
StandardError=journal
SyslogIdentifier=swarm-server

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable swarm-server
```

## Step 6: Obtain TLS Certificates

Stop any service using ports 80/443 before running certbot:

```bash
# Stop Angie if already running
sudo systemctl stop angie 2>/dev/null || true

# Obtain certificate
sudo certbot certonly --standalone \
    -d your-domain.com \
    --email admin@your-domain.com \
    --agree-tos --non-interactive
```

Set up auto-renewal with an Angie reload hook:

```bash
sudo mkdir -p /etc/letsencrypt/renewal-hooks/deploy

sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-angie.sh << 'HOOK'
#!/bin/bash
systemctl reload angie
HOOK

sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-angie.sh

# Verify the renewal timer is active
sudo systemctl status certbot.timer
```

## Step 7: Configure Angie

The repository includes a ready-to-use Angie configuration template. Copy it and substitute your domain:

```bash
# Copy main config template
sudo cp /opt/agent-swarm-protocol/src/server/angie.conf.template /etc/angie/angie.conf

# Replace template variables
sudo sed -i 's/{{DOMAIN}}/your-domain.com/g' /etc/angie/angie.conf
sudo sed -i 's/{{UPSTREAM_PORT}}/8080/g' /etc/angie/angie.conf

# Copy include files
sudo mkdir -p /etc/angie/conf.d
sudo cp /opt/agent-swarm-protocol/src/server/ssl.conf /etc/angie/conf.d/
sudo cp /opt/agent-swarm-protocol/src/server/security.conf /etc/angie/conf.d/
sudo cp /opt/agent-swarm-protocol/src/server/proxy_params.conf /etc/angie/conf.d/

# Create ACME challenge directory
sudo mkdir -p /var/www/acme/.well-known/acme-challenge
sudo chown -R www-data:www-data /var/www/acme

# Create log directory
sudo mkdir -p /var/log/angie

# Test configuration
sudo angie -t
```

The template provides:

- HTTP to HTTPS redirect with ACME challenge passthrough on port 80
- HTTPS with HTTP/2 and HTTP/3 (QUIC) on port 443
- TLS 1.2+ with modern cipher suites and OCSP stapling
- Rate limiting per agent and per IP
- Security headers (HSTS, X-Frame-Options, etc.)
- Proxy to uvicorn on 127.0.0.1:8080
- Location blocks for `/swarm/message`, `/swarm/join`, `/swarm/health`, `/swarm/info`, `/api/wake`, `/api/inbox`, and `/api/outbox`

## Step 8: Start Services

```bash
# Start the FastAPI backend
sudo systemctl start swarm-server

# Start Angie
sudo systemctl start angie
sudo systemctl enable angie
```

## Step 9: Verify

```bash
# Check service status
sudo systemctl status swarm-server
sudo systemctl status angie

# Health check
curl https://your-domain.com/swarm/health

# Agent info
curl https://your-domain.com/swarm/info

# Check HTTP/3 support
curl --http3 -I https://your-domain.com/swarm/health

# Check TLS
openssl s_client -connect your-domain.com:443 -tls1_3
```

## Firewall

Ensure these ports are open:

```bash
sudo ufw allow 80/tcp    # HTTP (ACME + redirect)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 443/udp   # HTTP/3 (QUIC)
```

## Shared Database

The key advantage of host deployment is the shared SQLite database. All components read and write the same file:

| Component | Access | Purpose |
|-----------|--------|---------|
| `swarm` CLI | Read/Write | Create swarms, invite agents, send messages |
| FastAPI server | Read/Write | Handle inbound messages, process joins, session management |
| Claude hooks | Read | Check for unread inbox messages |

Set `DB_PATH` in the environment file to point to the same database that the CLI uses (typically `~/.swarm/swarm.db`).

SQLite handles concurrent access via WAL mode (write-ahead logging), which is enabled automatically by the `DatabaseManager` on initialization.

## Deploying Updates

After PRs merge into `main`, deploy the new code to the live server. Use the automated deploy script or follow the manual steps below.

### Automated Deploy (Recommended)

```bash
cd /opt/sage/agent-swarm-protocol

# Standard deploy: pull, install, test, restart, health check
scripts/deploy.sh

# Deploy with Angie config drift check + sync attempt
scripts/deploy.sh --sync-angie

# Preview what would happen without making changes
scripts/deploy.sh --dry-run

# Skip tests (use with caution, e.g. when tests are known-broken upstream)
scripts/deploy.sh --skip-tests
```

The script is idempotent and safe to run repeatedly. It will:

1. `git pull origin main`
2. `pip install -e ".[dev]"` (picks up new dependencies)
3. `pytest -x -q` (fail-fast; aborts deploy on test failure)
4. Check Angie config drift (compares template location blocks against live config)
5. Optionally sync Angie config (with `--sync-angie`)
6. `systemctl restart swarm-agent`
7. Health check with retries (`curl http://127.0.0.1:8081/swarm/health`)

**Environment overrides** (all optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `REPO_DIR` | `/opt/sage/agent-swarm-protocol` | Repository root |
| `LIVE_CONF` | `/etc/angie/http.d/self-wake.conf` | Live Angie config path |
| `SERVICE_NAME` | `swarm-agent` | systemd service name |
| `HEALTH_URL` | `http://127.0.0.1:8081/swarm/health` | Health check endpoint |
| `HEALTH_RETRIES` | `5` | Number of health check attempts |
| `HEALTH_DELAY` | `2` | Seconds between health check retries |

### Manual Deploy (Fallback)

If the deploy script is unavailable or you need fine-grained control:

```bash
cd /opt/sage/agent-swarm-protocol

# 1. Pull latest code
git pull origin main

# 2. Install dependencies (in venv)
./venv/bin/pip install -e ".[dev]"

# 3. Run tests
./venv/bin/pytest -x -q

# 4. Check Angie config drift
#    Compare location blocks in the template against the live config:
diff <(grep -E '^\s*location\s' src/server/angie.conf.template | sed 's/^[[:space:]]*//' | sort) \
     <(grep -E '^\s*location\s' /etc/angie/http.d/self-wake.conf | sed 's/^[[:space:]]*//' | sort)
#    If there are differences, add missing location blocks to the live config.

# 5. If Angie config was changed:
angie -t && systemctl reload angie

# 6. Restart the service
systemctl restart swarm-agent

# 7. Verify
sleep 2
curl -sf http://127.0.0.1:8081/swarm/health && echo "OK" || echo "FAILED"
systemctl status swarm-agent --no-pager
```

### Angie Config Drift

The Angie config template (`src/server/angie.conf.template`) and the live server config (`/etc/angie/http.d/self-wake.conf`) have **different structures**:

| Aspect | Template | Live Config |
|--------|----------|-------------|
| Scope | Full standalone config (`worker_processes`, `events {}`, `http {}`) | Server-block include (loaded by Angie's `http {}` context) |
| Upstream | `swarm_backend` only | `selfwake_backend` + `swarm_backend` |
| Extra routes | None | `/content/`, `/health`, status page at `/` |
| Variables | `{{DOMAIN}}`, `{{UPSTREAM_PORT}}` placeholders | Hardcoded values |

**Why they differ**: The live server hosts multiple services (self-wake daemon, static content, swarm protocol) behind a single Angie instance. The template is designed as a reference for new single-service deployments.

**What drifts**: When PRs add new `location` blocks to the template (e.g., `/api/inbox`, `/api/outbox`), those blocks must be manually added to the live config. The deploy script detects this drift and warns you.

**How to fix drift**:

1. Run `scripts/deploy.sh` -- it will list missing location blocks
2. Open `/etc/angie/http.d/self-wake.conf` in an editor
3. Add the missing location blocks inside the `server { }` block
4. Validate: `angie -t`
5. Reload: `systemctl reload angie`

This pattern has caused failures three times (PRs #75, #88, #152/#161). The deploy script's drift detection prevents silent 404 failures on new routes.

## Troubleshooting

### Server Not Starting

```bash
# Check logs
sudo journalctl -u swarm-server -f

# Common issues:
# - Missing environment variables (AGENT_ID, AGENT_ENDPOINT, AGENT_PUBLIC_KEY)
# - DB_PATH directory does not exist
# - Port 8080 already in use
```

### Angie Configuration Errors

```bash
# Test configuration syntax
sudo angie -t

# Common issues:
# - Template variables not substituted ({{DOMAIN}} still in config)
# - Missing include files in /etc/angie/conf.d/
# - Certificate files not found at /etc/letsencrypt/live/your-domain.com/
```

### Certificate Issues

```bash
# Check certificate status
sudo certbot certificates

# Force renewal
sudo certbot renew --force-renewal

# Check certbot logs
sudo journalctl -u certbot
```

### Database Permission Issues

```bash
# Ensure the server user can read/write the database
ls -la ~/.swarm/swarm.db

# If running as a different user, adjust permissions
sudo chown $USER:$USER ~/.swarm/swarm.db
```

### Checking Logs

```bash
# FastAPI server logs
sudo journalctl -u swarm-server --since "1 hour ago"

# Angie access log
sudo tail -f /var/log/angie/access.log

# Angie error log
sudo tail -f /var/log/angie/error.log
```
