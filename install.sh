#!/usr/bin/env bash
# Venus OS Fronius Proxy — One-Line Installer
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/meintechblog/venus-os-fronius-proxy/main/install.sh | bash
#
# What it does:
#   1. Creates fronius-proxy service user
#   2. Installs Python 3 + venv + git
#   3. Clones the repo (or pulls if exists)
#   4. Creates venv and installs package
#   5. Creates default config if missing
#   6. Installs and starts systemd service
#
# Requirements: Debian 12+ / Ubuntu 22.04+, root access
#
set -euo pipefail

REPO="https://github.com/meintechblog/venus-os-fronius-proxy.git"
INSTALL_DIR="/opt/venus-os-fronius-proxy"
CONFIG_DIR="/etc/venus-os-fronius-proxy"
SERVICE_USER="fronius-proxy"
SERVICE_NAME="venus-os-fronius-proxy"

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
echo -e "${BLUE}  Venus OS Fronius Proxy — Installer${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

[ "$(id -u)" -eq 0 ] || fail "Must run as root"
command -v apt-get >/dev/null 2>&1 || fail "apt-get not found — Debian/Ubuntu required"

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
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    cd "$INSTALL_DIR"
    git fetch origin
    git reset --hard origin/main
    ok "Updated to latest"
else
    info "Cloning repository..."
    git clone "$REPO" "$INSTALL_DIR"
    ok "Cloned to $INSTALL_DIR"
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
# Venus OS Fronius Proxy Configuration
#
# SolarEdge inverter connection
solaredge:
  host: "192.168.3.18"
  port: 1502
  unit_id: 1

# Modbus proxy server (Venus OS connects here)
proxy:
  port: 502

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
    ok "Config exists at $CONFIG_DIR/config.yaml"
fi

# --- Step 6: Permissions ---
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR"
ok "Permissions set"

# --- Step 7: Systemd service ---
info "Installing systemd service..."
cp "$INSTALL_DIR/config/venus-os-fronius-proxy.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
ok "Service installed and enabled"

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
echo "    curl -sSL https://raw.githubusercontent.com/meintechblog/venus-os-fronius-proxy/main/install.sh | bash"
echo ""
