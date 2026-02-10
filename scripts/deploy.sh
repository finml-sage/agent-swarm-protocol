#!/usr/bin/env bash
# deploy.sh - Automated deployment for Agent Swarm Protocol
#
# Usage:
#   scripts/deploy.sh              # Full deploy (pull, install, test, restart, health check)
#   scripts/deploy.sh --sync-angie # Also sync Angie config and reload
#   scripts/deploy.sh --skip-tests # Skip pytest (use with caution)
#   scripts/deploy.sh --dry-run    # Show what would happen, change nothing
#
# This script is idempotent and safe to run repeatedly.

set -euo pipefail

# --- Configuration (override via environment) ---
REPO_DIR="${REPO_DIR:-/opt/agent-swarm-protocol}"
VENV_DIR="${REPO_DIR}/venv"
TEMPLATE="${REPO_DIR}/src/server/angie.conf.template"
LIVE_CONF="${LIVE_CONF:-/etc/angie/angie.conf}"
SERVICE_NAME="${SERVICE_NAME:-swarm-server}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/swarm/health}"
HEALTH_RETRIES="${HEALTH_RETRIES:-5}"
HEALTH_DELAY="${HEALTH_DELAY:-2}"

# --- Parse flags ---
SYNC_ANGIE=false
SKIP_TESTS=false
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --sync-angie) SYNC_ANGIE=true ;;
        --skip-tests) SKIP_TESTS=true ;;
        --dry-run)    DRY_RUN=true ;;
        --help|-h)
            head -12 "$0" | tail -8
            exit 0
            ;;
        *)
            echo "ERROR: Unknown flag: $arg"
            echo "Usage: scripts/deploy.sh [--sync-angie] [--skip-tests] [--dry-run]"
            exit 1
            ;;
    esac
done

# --- Helpers ---
info()  { echo "[deploy] $*"; }
warn()  { echo "[deploy] WARNING: $*" >&2; }
error() { echo "[deploy] ERROR: $*" >&2; exit 1; }

run() {
    if $DRY_RUN; then
        info "(dry-run) $*"
    else
        "$@"
    fi
}

# --- Preflight checks ---
[ -d "$REPO_DIR" ]    || error "Repo directory not found: $REPO_DIR"
[ -d "$VENV_DIR" ]    || error "Virtual environment not found: $VENV_DIR"
[ -f "$TEMPLATE" ]    || error "Angie config template not found: $TEMPLATE"

cd "$REPO_DIR"

# --- Step 1: Pull latest code ---
info "Step 1/7: Pulling latest code..."
run git pull origin main

# --- Step 2: Install dependencies ---
info "Step 2/7: Installing dependencies..."
run "$VENV_DIR/bin/pip" install -q -e ".[dev,wake]"

# --- Step 3: Run tests ---
if $SKIP_TESTS; then
    warn "Skipping tests (--skip-tests flag set)"
else
    info "Step 3/7: Running tests..."
    if $DRY_RUN; then
        info "(dry-run) $VENV_DIR/bin/pytest"
    else
        if ! "$VENV_DIR/bin/pytest" -x -q; then
            error "Tests failed. Aborting deploy."
        fi
    fi
fi

# --- Step 4: Check Angie config drift ---
info "Step 4/7: Checking Angie config drift..."

# Extract URL paths from location directives for comparison.
# The template is a full standalone config; the live config is a server-block include.
# We compare the proxied URL paths, not the full location directives, because:
#   - The template uses exact matches: location = /swarm/message { ... }
#   - The live config may use prefix matches: location /swarm/ { ... }
# A prefix match like "location /swarm/" covers /swarm/message, /swarm/join, etc.
extract_paths() {
    # Extract URL paths from location directives, ignoring modifiers (=, ~, etc.)
    grep -E '^\s*location\s' "$1" 2>/dev/null \
        | sed 's/^[[:space:]]*location[[:space:]]*=[[:space:]]*//' \
        | sed 's/^[[:space:]]*location[[:space:]]*//' \
        | sed 's/[[:space:]]*{.*//' \
        | sort -u
}

# Check if a path is covered by any live config location (exact or prefix match)
path_is_covered() {
    local path="$1"
    local live_paths="$2"
    while IFS= read -r live_path; do
        [ -z "$live_path" ] && continue
        # Exact match
        if [ "$path" = "$live_path" ]; then
            return 0
        fi
        # Prefix match: live has "/swarm/" which covers "/swarm/message"
        if [[ "$live_path" == */ ]] && [[ "$path" == ${live_path}* ]]; then
            return 0
        fi
    done <<< "$live_paths"
    return 1
}

DRIFT_DETECTED=false
MISSING_LOCATIONS=""

if [ -f "$LIVE_CONF" ]; then
    TEMPLATE_PATHS=$(extract_paths "$TEMPLATE")
    LIVE_PATHS=$(extract_paths "$LIVE_CONF")

    # Find paths in the template that are not covered by the live config
    while IFS= read -r tpath; do
        [ -z "$tpath" ] && continue
        # Skip non-proxied paths (ACME challenge, catch-all)
        case "$tpath" in
            /.well-known/*|/) continue ;;
        esac
        if ! path_is_covered "$tpath" "$LIVE_PATHS"; then
            DRIFT_DETECTED=true
            MISSING_LOCATIONS="${MISSING_LOCATIONS}  - ${tpath}\n"
        fi
    done <<< "$TEMPLATE_PATHS"

    if $DRIFT_DETECTED; then
        warn "Angie config drift detected!"
        warn "The following paths from the template are NOT covered by the live config:"
        echo -e "$MISSING_LOCATIONS" >&2
        warn ""
        warn "Template: $TEMPLATE"
        warn "Live:     $LIVE_CONF"
        warn ""
        warn "The template is a full standalone config, while the live config is a"
        warn "server-block include that may contain additional location blocks."
        warn "Do NOT blindly copy the template over the live config."
        warn ""
        warn "To sync manually:"
        warn "  1. Add the missing location blocks to $LIVE_CONF"
        warn "  2. Run: angie -t"
        warn "  3. Run: systemctl reload angie"
        warn ""
        warn "Or re-run with --sync-angie to auto-add missing location blocks."
    else
        info "Angie config location blocks are in sync."
    fi
else
    warn "Live Angie config not found at $LIVE_CONF"
    warn "Skipping drift check."
fi

# --- Step 5: Sync Angie config (optional) ---
if $SYNC_ANGIE; then
    info "Step 5/7: Syncing Angie config..."

    if [ ! -f "$LIVE_CONF" ]; then
        error "Cannot sync: live Angie config not found at $LIVE_CONF"
    fi

    # Backup current live config
    BACKUP="${LIVE_CONF}.bak.$(date +%Y%m%d%H%M%S)"
    info "Backing up $LIVE_CONF to $BACKUP"
    run cp "$LIVE_CONF" "$BACKUP"

    # NOTE: We do NOT copy the template over the live config because they have
    # different structures. The template is a full standalone config (with
    # worker_processes, events{}, http{} blocks). The live config is a
    # server-block include that shares Angie with other services.
    #
    # Instead, we identify missing location blocks from the template and
    # instruct the operator to add them manually, or we attempt to patch
    # them into the live config in a safe location.

    if ${DRIFT_DETECTED:-false}; then
        warn "Auto-sync of location blocks is not supported because the template"
        warn "and live config have different structures (standalone vs include)."
        warn ""
        warn "Please add the missing location blocks manually to: $LIVE_CONF"
        warn "A backup was saved to: $BACKUP"
        warn ""
        warn "After editing, validate and reload:"
        warn "  angie -t && systemctl reload angie"
    else
        info "No missing location blocks. Angie config is already in sync."
    fi

    # Always validate the current config
    if ! $DRY_RUN; then
        info "Validating Angie config..."
        if angie -t 2>&1; then
            info "Angie config valid."
        else
            error "Angie config validation failed! Check the config and restore from backup: $BACKUP"
        fi
    fi
else
    info "Step 5/7: Skipping Angie sync (use --sync-angie to enable)"
fi

# --- Step 6: Restart service ---
info "Step 6/7: Restarting $SERVICE_NAME..."
run systemctl restart "$SERVICE_NAME"

if ! $DRY_RUN; then
    # Brief pause for service to initialize
    sleep 1
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        info "$SERVICE_NAME is running."
    else
        error "$SERVICE_NAME failed to start. Check: journalctl -u $SERVICE_NAME --since '1 min ago'"
    fi
fi

# --- Step 7: Health check ---
info "Step 7/7: Running health check..."

if $DRY_RUN; then
    info "(dry-run) curl -sf $HEALTH_URL"
else
    attempt=0
    while [ $attempt -lt "$HEALTH_RETRIES" ]; do
        attempt=$((attempt + 1))
        if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
            info "Health check passed (attempt $attempt/$HEALTH_RETRIES)."
            break
        fi
        if [ $attempt -lt "$HEALTH_RETRIES" ]; then
            info "Health check attempt $attempt/$HEALTH_RETRIES failed, retrying in ${HEALTH_DELAY}s..."
            sleep "$HEALTH_DELAY"
        else
            error "Health check failed after $HEALTH_RETRIES attempts. URL: $HEALTH_URL"
        fi
    done
fi

info ""
info "Deploy complete."
