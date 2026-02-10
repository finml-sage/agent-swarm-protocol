#!/usr/bin/env bash
# bootstrap.sh - Interactive onboarding for new Agent Swarm Protocol members
#
# Usage:
#   sudo scripts/bootstrap.sh
#
# This script walks a new agent through the full setup:
#   1. Collect agent identity (name, domain, optional join URL)
#   2. Install system packages (Python, Angie, certbot, ufw)
#   3. Clone or update the ASP repository
#   4. Create Python venv and install the package
#   5. Initialize agent identity (Ed25519 keypair)
#   6. Extract public key from generated keypair
#   7. Write environment file (/etc/agent-swarm-protocol.env)
#   8. Create systemd service unit
#   9. Obtain TLS certificate via certbot
#  10. Configure Angie reverse proxy
#  11. Configure firewall (ufw)
#  12. Start services
#  13. Join swarm (if join URL provided)
#  14. Health check (local + HTTPS)
#
# The script is idempotent: safe to re-run. Each step checks existing state.

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
readonly REPO_URL="https://github.com/finml-sage/agent-swarm-protocol.git"
readonly INSTALL_DIR="/opt/agent-swarm-protocol"
readonly VENV_DIR="${INSTALL_DIR}/venv"
readonly ENV_FILE="/etc/agent-swarm-protocol.env"
readonly SERVICE_FILE="/etc/systemd/system/swarm-server.service"
readonly SWARM_DIR="/root/.swarm"
readonly AGENT_KEY="${SWARM_DIR}/agent.key"
readonly DB_PATH="${SWARM_DIR}/swarm.db"
readonly LOG_FILE="/var/log/asp-bootstrap.log"
readonly UPSTREAM_PORT="8080"

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

_log() {
    local level="$1"; shift
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "${ts} [${level}] $*" >> "$LOG_FILE"
}

info() {
    echo -e "${GREEN}[OK]${NC} $*"
    _log "INFO" "$*"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $*" >&2
    _log "WARN" "$*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
    _log "ERROR" "$*"
    exit 1
}

step() {
    echo ""
    echo -e "${CYAN}${BOLD}--- $* ---${NC}"
    _log "STEP" "$*"
}

# ---------------------------------------------------------------------------
# Error trap
# ---------------------------------------------------------------------------
on_error() {
    local lineno="$1"
    echo ""
    echo -e "${RED}[FATAL]${NC} Script failed at line ${lineno}."
    echo -e "${RED}[FATAL]${NC} Check the log for details: ${LOG_FILE}"
    _log "FATAL" "Script failed at line ${lineno}"
}
trap 'on_error ${LINENO}' ERR

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root."
fi

if ! grep -qiE 'ubuntu|debian' /etc/os-release 2>/dev/null; then
    error "This script requires Ubuntu or Debian. Detected: $(. /etc/os-release && echo "$PRETTY_NAME")"
fi

mkdir -p "$(dirname "$LOG_FILE")"
echo "=== ASP Bootstrap started at $(date) ===" >> "$LOG_FILE"

echo ""
echo -e "${BOLD}Agent Swarm Protocol - Bootstrap Script${NC}"
echo "========================================="
echo ""
echo "This script will set up a new ASP swarm member on this machine."
echo "Log file: ${LOG_FILE}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Interactive prompts
# ---------------------------------------------------------------------------
step "Step 1/14: Collect agent identity"

read -rp "Agent ID (e.g. my-agent): " AGENT_ID
if [[ -z "$AGENT_ID" ]]; then
    error "Agent ID is required."
fi

read -rp "Domain name (e.g. agent.example.com): " DOMAIN
if [[ -z "$DOMAIN" ]]; then
    error "Domain name is required."
fi

read -rp "Swarm join URL (optional, press Enter to skip): " JOIN_URL

read -rp "Tmux session name for wake system [default: same as Agent ID]: " TMUX_TARGET
TMUX_TARGET="${TMUX_TARGET:-$AGENT_ID}"

AGENT_ENDPOINT="https://${DOMAIN}/swarm"

echo ""
echo -e "${BOLD}Configuration summary:${NC}"
echo "  Agent ID:       ${AGENT_ID}"
echo "  Domain:         ${DOMAIN}"
echo "  Endpoint:       ${AGENT_ENDPOINT}"
echo "  Join URL:       ${JOIN_URL:-<none>}"
echo "  Tmux target:    ${TMUX_TARGET}"
echo "  Install dir:    ${INSTALL_DIR}"
echo "  DB path:        ${DB_PATH}"
echo ""
read -rp "Proceed with these settings? [Y/n] " CONFIRM
CONFIRM="${CONFIRM:-Y}"
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 2: System packages
# ---------------------------------------------------------------------------
step "Step 2/14: Install system packages"

export DEBIAN_FRONTEND=noninteractive

info "Updating apt cache..."
apt-get update -qq >> "$LOG_FILE" 2>&1

# Python
if command -v python3 &>/dev/null; then
    PY_VERSION="$(python3 --version 2>&1 | grep -oP '\d+\.\d+')"
    info "Python ${PY_VERSION} already installed."
else
    info "Installing Python 3..."
    apt-get install -y -qq python3 python3-pip python3-venv >> "$LOG_FILE" 2>&1
fi

# Ensure pip and venv are available (sometimes separate packages on Ubuntu)
apt-get install -y -qq python3-pip python3-venv >> "$LOG_FILE" 2>&1

# Git
if command -v git &>/dev/null; then
    info "git already installed."
else
    info "Installing git..."
    apt-get install -y -qq git >> "$LOG_FILE" 2>&1
fi

# Angie
if command -v angie &>/dev/null; then
    info "Angie already installed."
else
    info "Installing Angie..."
    # Determine OS info for repo URL
    OS_ID="$(. /etc/os-release && echo "$ID")"
    OS_VERSION="$(. /etc/os-release && echo "$VERSION_ID")"
    OS_CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"

    curl -fsSL -o /etc/apt/trusted.gpg.d/angie-signing.gpg \
        https://angie.software/keys/angie-signing.gpg >> "$LOG_FILE" 2>&1

    echo "deb https://download.angie.software/angie/${OS_ID}/${OS_VERSION} ${OS_CODENAME} main" \
        > /etc/apt/sources.list.d/angie.list

    apt-get update -qq >> "$LOG_FILE" 2>&1
    apt-get install -y -qq angie >> "$LOG_FILE" 2>&1
    info "Angie installed."
fi

# Certbot
if command -v certbot &>/dev/null; then
    info "certbot already installed."
else
    info "Installing certbot..."
    apt-get install -y -qq certbot >> "$LOG_FILE" 2>&1
fi

# ufw
if command -v ufw &>/dev/null; then
    info "ufw already installed."
else
    info "Installing ufw..."
    apt-get install -y -qq ufw >> "$LOG_FILE" 2>&1
fi

# tmux (needed for wake system)
if command -v tmux &>/dev/null; then
    info "tmux already installed."
else
    info "Installing tmux..."
    apt-get install -y -qq tmux >> "$LOG_FILE" 2>&1
fi

# curl (needed for health checks)
if command -v curl &>/dev/null; then
    info "curl already installed."
else
    info "Installing curl..."
    apt-get install -y -qq curl >> "$LOG_FILE" 2>&1
fi

# ---------------------------------------------------------------------------
# Step 3: Clone repository
# ---------------------------------------------------------------------------
step "Step 3/14: Clone repository"

if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Repository already exists at ${INSTALL_DIR}. Pulling latest..."
    git -C "$INSTALL_DIR" pull origin main >> "$LOG_FILE" 2>&1
else
    if [[ -d "$INSTALL_DIR" ]]; then
        warn "${INSTALL_DIR} exists but is not a git repo."
        read -rp "Remove and re-clone? [Y/n] " RECLONE
        RECLONE="${RECLONE:-Y}"
        if [[ "$RECLONE" =~ ^[Yy]$ ]]; then
            rm -rf "$INSTALL_DIR"
        else
            error "Cannot proceed without a valid repository at ${INSTALL_DIR}."
        fi
    fi
    info "Cloning ${REPO_URL} into ${INSTALL_DIR}..."
    git clone "$REPO_URL" "$INSTALL_DIR" >> "$LOG_FILE" 2>&1
fi
info "Repository ready at ${INSTALL_DIR}."

# ---------------------------------------------------------------------------
# Step 4: Python venv setup
# ---------------------------------------------------------------------------
step "Step 4/14: Python virtual environment"

if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    info "Virtual environment already exists at ${VENV_DIR}."
else
    info "Creating virtual environment..."
    python3 -m venv "$VENV_DIR" >> "$LOG_FILE" 2>&1
fi

info "Installing package (pip install -e .)..."
"${VENV_DIR}/bin/pip" install -q -e "${INSTALL_DIR}" >> "$LOG_FILE" 2>&1
info "Package installed. CLI available at: ${VENV_DIR}/bin/swarm"

# ---------------------------------------------------------------------------
# Step 5: Agent identity
# ---------------------------------------------------------------------------
step "Step 5/14: Initialize agent identity"

if [[ -f "$AGENT_KEY" ]]; then
    info "Agent key already exists at ${AGENT_KEY}."
    read -rp "Re-initialize identity? This will overwrite the existing key. [y/N] " REINIT
    REINIT="${REINIT:-N}"
    if [[ "$REINIT" =~ ^[Yy]$ ]]; then
        "${VENV_DIR}/bin/swarm" init \
            --agent-id "$AGENT_ID" \
            --endpoint "$AGENT_ENDPOINT" >> "$LOG_FILE" 2>&1
        info "Agent identity re-initialized."
    else
        info "Keeping existing agent key."
    fi
else
    "${VENV_DIR}/bin/swarm" init \
        --agent-id "$AGENT_ID" \
        --endpoint "$AGENT_ENDPOINT" >> "$LOG_FILE" 2>&1
    info "Agent identity initialized for ${AGENT_ID}."
fi

# ---------------------------------------------------------------------------
# Step 6: Extract public key
# ---------------------------------------------------------------------------
step "Step 6/14: Extract public key"

if [[ ! -f "$AGENT_KEY" ]]; then
    error "Agent key not found at ${AGENT_KEY}. Step 5 may have failed."
fi

# Ed25519 private key is 64 bytes: first 32 = private seed, last 32 = public key
PUBLIC_KEY_B64="$(python3 -c "
import base64
raw = open('${AGENT_KEY}', 'rb').read()
print(base64.b64encode(raw[32:]).decode())
")"

if [[ -z "$PUBLIC_KEY_B64" ]]; then
    error "Failed to extract public key from ${AGENT_KEY}."
fi

info "Public key (base64): ${PUBLIC_KEY_B64}"

# ---------------------------------------------------------------------------
# Step 7: Environment file
# ---------------------------------------------------------------------------
step "Step 7/14: Create environment file"

if [[ -f "$ENV_FILE" ]]; then
    warn "Environment file already exists at ${ENV_FILE}."
    read -rp "Overwrite? [y/N] " OVERWRITE_ENV
    OVERWRITE_ENV="${OVERWRITE_ENV:-N}"
    if [[ ! "$OVERWRITE_ENV" =~ ^[Yy]$ ]]; then
        info "Keeping existing environment file."
    else
        _write_env=true
    fi
else
    _write_env=true
fi

if [[ "${_write_env:-false}" == "true" ]]; then
    cat > "$ENV_FILE" << ENVEOF
AGENT_ID=${AGENT_ID}
AGENT_ENDPOINT=${AGENT_ENDPOINT}
AGENT_PUBLIC_KEY=${PUBLIC_KEY_B64}
DB_PATH=${DB_PATH}
WAKE_ENABLED=true
WAKE_ENDPOINT=http://localhost:${UPSTREAM_PORT}/api/wake
WAKE_EP_ENABLED=true
WAKE_EP_INVOKE_METHOD=tmux
WAKE_EP_TMUX_TARGET=${TMUX_TARGET}
ENVEOF
    chmod 600 "$ENV_FILE"
    info "Environment file written to ${ENV_FILE} (chmod 600)."
fi

# ---------------------------------------------------------------------------
# Step 8: Systemd service unit
# ---------------------------------------------------------------------------
step "Step 8/14: Create systemd service"

if [[ -f "$SERVICE_FILE" ]]; then
    warn "Service file already exists at ${SERVICE_FILE}."
    read -rp "Overwrite? [y/N] " OVERWRITE_SVC
    OVERWRITE_SVC="${OVERWRITE_SVC:-N}"
    if [[ ! "$OVERWRITE_SVC" =~ ^[Yy]$ ]]; then
        info "Keeping existing service file."
    else
        _write_svc=true
    fi
else
    _write_svc=true
fi

if [[ "${_write_svc:-false}" == "true" ]]; then
    cat > "$SERVICE_FILE" << 'SVCEOF'
[Unit]
Description=Agent Swarm Protocol Server
After=network.target
Wants=angie.service

[Service]
Type=simple
EnvironmentFile=/etc/agent-swarm-protocol.env
WorkingDirectory=/opt/agent-swarm-protocol
ExecStart=/opt/agent-swarm-protocol/venv/bin/python -m uvicorn src.server.app:create_app --factory --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=swarm-server

[Install]
WantedBy=multi-user.target
SVCEOF
    info "Service file written to ${SERVICE_FILE}."
fi

systemctl daemon-reload
systemctl enable swarm-server >> "$LOG_FILE" 2>&1
info "swarm-server service enabled."

# ---------------------------------------------------------------------------
# Step 9: SSL certificate
# ---------------------------------------------------------------------------
step "Step 9/14: Obtain TLS certificate"

CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"

if [[ -f "${CERT_DIR}/fullchain.pem" ]]; then
    info "TLS certificate already exists for ${DOMAIN}."
else
    info "Obtaining TLS certificate for ${DOMAIN}..."

    # Stop Angie if it is running on port 80
    if systemctl is-active --quiet angie 2>/dev/null; then
        warn "Stopping Angie to free port 80 for certbot..."
        systemctl stop angie
    fi

    certbot certonly --standalone \
        -d "$DOMAIN" \
        --non-interactive \
        --agree-tos \
        --email "${AGENT_ID}@swarm.local" >> "$LOG_FILE" 2>&1

    info "TLS certificate obtained for ${DOMAIN}."
fi

# Certbot renewal hook for Angie
HOOK_DIR="/etc/letsencrypt/renewal-hooks/deploy"
HOOK_FILE="${HOOK_DIR}/reload-angie.sh"

if [[ -f "$HOOK_FILE" ]]; then
    info "Certbot renewal hook already exists."
else
    mkdir -p "$HOOK_DIR"
    cat > "$HOOK_FILE" << 'HOOKEOF'
#!/bin/bash
systemctl reload angie
HOOKEOF
    chmod +x "$HOOK_FILE"
    info "Certbot renewal hook created at ${HOOK_FILE}."
fi

# ---------------------------------------------------------------------------
# Step 10: Angie configuration
# ---------------------------------------------------------------------------
step "Step 10/14: Configure Angie"

ANGIE_CONF="/etc/angie/angie.conf"
TEMPLATE="${INSTALL_DIR}/src/server/angie.conf.template"

if [[ ! -f "$TEMPLATE" ]]; then
    error "Angie config template not found at ${TEMPLATE}."
fi

if [[ -f "$ANGIE_CONF" ]] && grep -q "$DOMAIN" "$ANGIE_CONF" 2>/dev/null; then
    info "Angie config already contains ${DOMAIN}. Skipping overwrite."
else
    if [[ -f "$ANGIE_CONF" ]]; then
        BACKUP="${ANGIE_CONF}.bak.$(date +%Y%m%d%H%M%S)"
        cp "$ANGIE_CONF" "$BACKUP"
        info "Backed up existing Angie config to ${BACKUP}."
    fi

    cp "$TEMPLATE" "$ANGIE_CONF"
    sed -i "s/{{DOMAIN}}/${DOMAIN}/g" "$ANGIE_CONF"
    sed -i "s/{{UPSTREAM_PORT}}/${UPSTREAM_PORT}/g" "$ANGIE_CONF"
    info "Angie main config written to ${ANGIE_CONF}."
fi

# Copy include files
mkdir -p /etc/angie/conf.d

for conf_file in ssl.conf security.conf proxy_params.conf; do
    SRC="${INSTALL_DIR}/src/server/${conf_file}"
    DST="/etc/angie/conf.d/${conf_file}"
    if [[ -f "$SRC" ]]; then
        cp "$SRC" "$DST"
        info "Copied ${conf_file} to /etc/angie/conf.d/"
    else
        warn "Include file not found: ${SRC}"
    fi
done

# Create required directories
mkdir -p /var/www/acme/.well-known/acme-challenge
mkdir -p /var/log/angie

# Validate config
if angie -t >> "$LOG_FILE" 2>&1; then
    info "Angie configuration is valid."
else
    error "Angie configuration test failed. Check ${LOG_FILE} for details."
fi

# ---------------------------------------------------------------------------
# Step 11: Firewall
# ---------------------------------------------------------------------------
step "Step 11/14: Configure firewall"

ufw allow 22/tcp >> "$LOG_FILE" 2>&1 || true
ufw allow 80/tcp >> "$LOG_FILE" 2>&1 || true
ufw allow 443/tcp >> "$LOG_FILE" 2>&1 || true
ufw allow 443/udp >> "$LOG_FILE" 2>&1 || true

if ufw status | grep -q "Status: active"; then
    info "ufw is already active."
else
    ufw --force enable >> "$LOG_FILE" 2>&1
    info "ufw enabled."
fi

info "Firewall rules: 22/tcp, 80/tcp, 443/tcp, 443/udp"

# ---------------------------------------------------------------------------
# Step 12: Start services
# ---------------------------------------------------------------------------
step "Step 12/14: Start services"

systemctl start swarm-server >> "$LOG_FILE" 2>&1
sleep 2
if systemctl is-active --quiet swarm-server; then
    info "swarm-server is running."
else
    warn "swarm-server may not have started. Check: journalctl -u swarm-server"
fi

systemctl start angie >> "$LOG_FILE" 2>&1
systemctl enable angie >> "$LOG_FILE" 2>&1
if systemctl is-active --quiet angie; then
    info "Angie is running."
else
    warn "Angie may not have started. Check: journalctl -u angie"
fi

# ---------------------------------------------------------------------------
# Step 13: Join swarm
# ---------------------------------------------------------------------------
step "Step 13/14: Join swarm"

if [[ -n "$JOIN_URL" ]]; then
    info "Joining swarm with provided token..."
    if "${VENV_DIR}/bin/swarm" join --token "$JOIN_URL" >> "$LOG_FILE" 2>&1; then
        info "Successfully joined swarm."
    else
        warn "Join failed. You can retry manually:"
        warn "  ${VENV_DIR}/bin/swarm join --token \"${JOIN_URL}\""
    fi
else
    info "No join URL provided. Skipping swarm join."
    info "To join a swarm later, run:"
    info "  ${VENV_DIR}/bin/swarm join --token \"swarm://<master>/join?token=<JWT>\""
fi

# ---------------------------------------------------------------------------
# Step 14: Health check
# ---------------------------------------------------------------------------
step "Step 14/14: Health check"

LOCAL_HEALTH="http://127.0.0.1:${UPSTREAM_PORT}/swarm/health"
HTTPS_HEALTH="https://${DOMAIN}/swarm/health"

# Local health check (FastAPI directly)
RETRIES=5
DELAY=2
ATTEMPT=0
LOCAL_OK=false

while [[ $ATTEMPT -lt $RETRIES ]]; do
    ATTEMPT=$((ATTEMPT + 1))
    if curl -sf "$LOCAL_HEALTH" > /dev/null 2>&1; then
        LOCAL_OK=true
        break
    fi
    if [[ $ATTEMPT -lt $RETRIES ]]; then
        sleep "$DELAY"
    fi
done

if $LOCAL_OK; then
    info "Local health check passed: ${LOCAL_HEALTH}"
else
    warn "Local health check failed after ${RETRIES} attempts: ${LOCAL_HEALTH}"
    warn "Check: journalctl -u swarm-server --since '5 min ago'"
fi

# HTTPS health check (through Angie)
if curl -sf "$HTTPS_HEALTH" > /dev/null 2>&1; then
    info "HTTPS health check passed: ${HTTPS_HEALTH}"
else
    warn "HTTPS health check failed: ${HTTPS_HEALTH}"
    warn "This may be expected if DNS has not propagated yet."
    warn "Try: curl -sf ${HTTPS_HEALTH}"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}=========================================${NC}"
echo -e "${GREEN}${BOLD}  Bootstrap complete!${NC}"
echo -e "${GREEN}${BOLD}=========================================${NC}"
echo ""
echo "  Agent ID:       ${AGENT_ID}"
echo "  Domain:         ${DOMAIN}"
echo "  Endpoint:       ${AGENT_ENDPOINT}"
echo "  Public key:     ${PUBLIC_KEY_B64}"
echo "  Install dir:    ${INSTALL_DIR}"
echo "  Env file:       ${ENV_FILE}"
echo "  Service:        swarm-server.service"
echo "  DB path:        ${DB_PATH}"
echo "  Log file:       ${LOG_FILE}"
echo ""
echo "Useful commands:"
echo "  systemctl status swarm-server     # Check server status"
echo "  systemctl status angie            # Check reverse proxy"
echo "  journalctl -u swarm-server -f     # Follow server logs"
echo "  ${VENV_DIR}/bin/swarm --help      # CLI help"
echo ""
if [[ -z "$JOIN_URL" ]]; then
    echo "Next step: Ask the swarm master for an invite token, then run:"
    echo "  ${VENV_DIR}/bin/swarm join --token \"<invite-url>\""
    echo ""
fi

_log "INFO" "Bootstrap completed successfully for agent ${AGENT_ID} on ${DOMAIN}"
