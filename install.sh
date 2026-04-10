#!/usr/bin/env bash
# PV-Inverter-Proxy — One-Line Installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/meintechblog/pv-inverter-proxy/main/install.sh | bash
#
# What it does:
#   1. Creates pv-proxy service user
#   2. Installs Python 3 + venv + git
#   3. Clones the repo (or pulls if exists)
#   4. Creates venv and installs package
#   5. Creates default config if missing
#   6. Installs and starts systemd service
#
# Requirements: Debian 12+ / Ubuntu 22.04+, root access
#
set -euo pipefail

REPO="https://github.com/meintechblog/pv-inverter-proxy.git"
INSTALL_DIR="/opt/pv-inverter-proxy"
CONFIG_DIR="/etc/pv-inverter-proxy"
SERVICE_USER="pv-proxy"
SERVICE_NAME="pv-inverter-proxy"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}>>>${NC} $1"; }
ok()    { echo -e "${GREEN} ✓${NC} $1"; }
fail()  { echo -e "${RED} ✗ $1${NC}"; exit 1; }

# --- Pre-flight ---
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  PV-Inverter-Proxy — Installer${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

[ "$(id -u)" -eq 0 ] || fail "Must run as root"
command -v apt-get >/dev/null 2>&1 || fail "apt-get not found — Debian/Ubuntu required"

# Check if port 502 is already in use
if ss -tlnp 2>/dev/null | grep -q ':502 '; then
    echo ""
    echo -e "${BLUE}  Note: Port 502 is currently in use.${NC}"
    ss -tlnp 2>/dev/null | grep ':502 '
    echo ""
    echo -e "  The proxy needs port 502. If this is a previous installation,"
    echo -e "  it will be restarted automatically. Otherwise stop the conflicting service first."
    echo ""
fi

# --- Step 1: System dependencies ---
info "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git >/dev/null 2>&1
ok "Python 3, venv, git installed"

# --- Step 2: Service user ---
if id "$SERVICE_USER" &>/dev/null; then
    ok "User $SERVICE_USER exists"
else
    info "Creating service user..."
    useradd -r -s /usr/sbin/nologin "$SERVICE_USER"
    ok "User $SERVICE_USER created"
fi

# --- Step 3: Clone or update repo ---
# Phase 43+ blue-green layout: $INSTALL_DIR may be a symlink pointing into
# $RELEASES_ROOT/current/. Existing `-d $INSTALL_DIR/.git` works transparently
# because bash's `-d` follows symlinks. Fresh installs create the blue-green
# layout from the start; existing flat installs are migrated in Step 3a below.
RELEASES_ROOT="${INSTALL_DIR}-releases"

if [ -d "$INSTALL_DIR/.git" ]; then
    # Works for both flat and blue-green (symlink resolves transparently)
    info "Updating existing installation..."
    cd "$INSTALL_DIR"
    git fetch origin
    git reset --hard origin/main
    ok "Updated to latest"
elif [ -L "$INSTALL_DIR" ]; then
    fail "install_root $INSTALL_DIR is a symlink but target has no .git (corrupt layout?)"
elif [ ! -e "$INSTALL_DIR" ]; then
    # Fresh install: create blue-green layout from the start (SAFETY-01)
    info "Fresh install — creating blue-green layout..."
    mkdir -p "$RELEASES_ROOT"
    SHORT_SHA=$(git ls-remote "$REPO" HEAD 2>/dev/null | awk '{print substr($1,1,7)}' || echo "bootstrap")
    if [ -z "$SHORT_SHA" ]; then
        SHORT_SHA="bootstrap"
    fi
    RELEASE_NAME="bootstrap-${SHORT_SHA}"
    RELEASE_DIR="${RELEASES_ROOT}/${RELEASE_NAME}"
    git clone "$REPO" "$RELEASE_DIR"
    ln -sfn "$RELEASE_DIR" "${RELEASES_ROOT}/current"
    ln -sfn "${RELEASES_ROOT}/current" "$INSTALL_DIR"
    ok "Fresh blue-green layout at $RELEASE_DIR"
else
    fail "install_root $INSTALL_DIR exists but is not a repo and not a symlink — manual cleanup needed"
fi

# --- Step 3a: Migrate flat layout to blue-green (SAFETY-01, SAFETY-03) ---
# If $INSTALL_DIR is still a real directory (not a symlink) after Step 3,
# we have a pre-Phase-43 flat layout that needs migration. Refuse on a dirty
# tree so the user doesn't silently lose uncommitted local edits.
if [ ! -L "$INSTALL_DIR" ] && [ -d "$INSTALL_DIR/.git" ]; then
    info "Detected flat layout — migrating to blue-green..."
    cd "$INSTALL_DIR"
    DIRTY=$(git status --porcelain 2>/dev/null || echo "")
    if [ -n "$DIRTY" ]; then
        echo ""
        echo -e "${RED}  MIGRATION REFUSED: dirty working tree${NC}"
        echo ""
        echo "  Uncommitted changes in $INSTALL_DIR:"
        git status --short | head -30
        echo ""
        echo "  Resolve manually before re-running install.sh:"
        echo "    ssh root@<lxc>"
        echo "    cd $INSTALL_DIR"
        echo "    git status"
        echo "    # commit/stash/discard as appropriate"
        echo ""
        exit 1
    fi
    VERSION=$(git describe --tags --always 2>/dev/null || echo "0.0")
    SHORT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "nosha")
    # Normalize: strip any leading 'v', then prepend 'v' so we always end up with
    # "v7.0-abc1234" and never "vv7.0-abc1234".
    VERSION="${VERSION#v}"
    RELEASE_NAME="v${VERSION}-${SHORT_SHA}"
    RELEASE_DIR="${RELEASES_ROOT}/${RELEASE_NAME}"

    mkdir -p "$RELEASES_ROOT"
    # Step out of the dir we're about to rename (bash holds no fd here but
    # cwd on $INSTALL_DIR would block the rename on some filesystems).
    cd /
    mv "$INSTALL_DIR" "$RELEASE_DIR"
    ln -sfn "$RELEASE_DIR" "${RELEASES_ROOT}/current"
    ln -sfn "${RELEASES_ROOT}/current" "$INSTALL_DIR"
    ok "Migrated to $RELEASE_DIR"
elif [ -L "$INSTALL_DIR" ]; then
    ok "Blue-green layout already in place ($(readlink -f "$INSTALL_DIR"))"
fi

# --- Step 4: Python venv + install ---
info "Setting up Python environment..."
cd "$INSTALL_DIR"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .
ok "Package installed in venv"

# --- Step 5: Config ---
mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    info "Creating default config..."
    cat > "$CONFIG_DIR/config.yaml" << 'YAML'
# PV-Inverter-Proxy Configuration
# Docs: https://github.com/meintechblog/pv-inverter-proxy

# SolarEdge inverter connection
inverter:
  host: "192.168.3.18"    # Your SolarEdge inverter IP
  port: 1502              # Modbus TCP port
  unit_id: 1              # Modbus unit/slave ID

# Modbus proxy server (Venus OS connects here)
proxy:
  port: 502

# Venus OS MQTT (optional — leave host empty to disable)
venus:
  host: ""                # Venus OS / Cerbo GX IP address
  port: 1883              # MQTT port (default 1883)
  portal_id: ""           # Leave empty for auto-discovery

# Web dashboard
webapp:
  port: 80

# Logging
log_level: INFO
YAML
    ok "Default config created at $CONFIG_DIR/config.yaml"
    echo ""
    echo -e "${BLUE}  Edit the config to match your setup:${NC}"
    echo -e "  nano $CONFIG_DIR/config.yaml"
    echo ""
else
    if grep -q '^solaredge:' "$CONFIG_DIR/config.yaml" 2>/dev/null; then
        echo ""
        echo -e "${RED}  WARNING: Your config uses the old 'solaredge:' key.${NC}"
        echo -e "  The proxy now expects 'inverter:' instead."
        echo -e "  Please update your config:"
        echo -e "    nano $CONFIG_DIR/config.yaml"
        echo -e "  Change 'solaredge:' to 'inverter:' and add a 'venus:' section."
        echo -e "  Reference: $INSTALL_DIR/config/config.example.yaml"
        echo ""
    fi
    ok "Config exists at $CONFIG_DIR/config.yaml"
fi

# --- Step 6: Permissions ---
# Follow symlink to the real release directory so chown -R reaches every file
# in the (possibly deeply nested) release dir. On a flat layout readlink -f
# returns $INSTALL_DIR unchanged, so this is a no-op there.
REAL_INSTALL=$(readlink -f "$INSTALL_DIR")
chown -R "$SERVICE_USER:$SERVICE_USER" "$REAL_INSTALL"
chown -R "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR"
# Cosmetic: set symlink link ownership (does not affect access, symlinks
# themselves ignore owner). -h prevents dereferencing the link.
if [ -L "$INSTALL_DIR" ]; then
    chown -h "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" 2>/dev/null || true
fi
if [ -L "${RELEASES_ROOT}/current" ]; then
    chown -h "$SERVICE_USER:$SERVICE_USER" "${RELEASES_ROOT}/current" 2>/dev/null || true
fi
ok "Permissions set"

# --- Step 6a: State + backups dirs (SAFETY-07) ---
# /var/lib/pv-inverter-proxy/ holds the PENDING marker and last-boot-success
# marker (Phase 43+). /var/lib/pv-inverter-proxy/backups/ will hold venv
# tarballs written by the Phase 45 privileged updater.
#
# Mode 2775 = rwx for root owner, rwx for pv-proxy group, r-x for other,
# plus the setgid bit so new files inherit the pv-proxy group. This lets
# BOTH root (updater) and pv-proxy (main service) write into these dirs.
info "Creating state and backup directories..."
install -d -o root -g "$SERVICE_USER" -m 2775 /var/lib/pv-inverter-proxy
install -d -o root -g "$SERVICE_USER" -m 2775 /var/lib/pv-inverter-proxy/backups
ok "State dir /var/lib/pv-inverter-proxy/ ready"

# --- Step 7: Systemd services (main + recovery) ---
info "Installing systemd services..."
cp "$INSTALL_DIR/config/pv-inverter-proxy.service" /etc/systemd/system/
cp "$INSTALL_DIR/config/pv-inverter-proxy-recovery.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl enable pv-inverter-proxy-recovery.service
ok "Services installed and enabled (main + recovery)"

# --- Step 8: Start ---
info "Starting service..."
systemctl restart "$SERVICE_NAME"
sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Service is running"
else
    echo ""
    echo -e "${RED}  Service failed to start. Check logs:${NC}"
    echo "  journalctl -u $SERVICE_NAME -n 20 --no-pager"
    echo ""
    exit 1
fi

# --- Done ---
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
echo "  Dashboard:  http://$(hostname -I | awk '{print $1}')"
echo "  Config:     $CONFIG_DIR/config.yaml"
echo "  Logs:       journalctl -u $SERVICE_NAME -f"
echo "  Status:     systemctl status $SERVICE_NAME"
echo ""
echo "  To update later:"
echo "    curl -fsSL https://raw.githubusercontent.com/meintechblog/pv-inverter-proxy/main/install.sh | bash"
echo ""
