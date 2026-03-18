#!/usr/bin/env bash
# Deploy venus-os-fronius-proxy to LXC container (192.168.3.191)
# Usage: ./deploy.sh [--first-time]
set -euo pipefail

LXC_HOST="root@192.168.3.191"
REMOTE_DIR="/opt/venus-os-fronius-proxy"
SERVICE="venus-os-fronius-proxy"

echo "=== Deploying venus-os-fronius-proxy to $LXC_HOST ==="

# First-time setup (creates user, dirs, venv, service)
if [[ "${1:-}" == "--first-time" ]]; then
    echo ">>> First-time setup..."

    ssh "$LXC_HOST" bash -s <<'SETUP'
set -euo pipefail

# Create service user (no login)
id fronius-proxy &>/dev/null || useradd -r -s /usr/sbin/nologin fronius-proxy

# Create directories
mkdir -p /opt/venus-os-fronius-proxy
mkdir -p /etc/venus-os-fronius-proxy

# Install Python + venv
apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip git

# Create venv
python3 -m venv /opt/venus-os-fronius-proxy/.venv

# Set ownership
chown -R fronius-proxy:fronius-proxy /opt/venus-os-fronius-proxy
chown -R fronius-proxy:fronius-proxy /etc/venus-os-fronius-proxy

echo ">>> First-time setup done."
SETUP
fi

# Sync source code (exclude dev files, .planning, tests, .git)
echo ">>> Syncing source code..."
rsync -avz --delete \
    --exclude '.git/' \
    --exclude '.planning/' \
    --exclude '.claude/' \
    --exclude 'tests/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.venv/' \
    --exclude 'node_modules/' \
    --exclude '.pytest_cache/' \
    ./ "$LXC_HOST:$REMOTE_DIR/"

# Install package + copy service file
echo ">>> Installing package..."
ssh "$LXC_HOST" bash -s <<'INSTALL'
set -euo pipefail
cd /opt/venus-os-fronius-proxy
.venv/bin/pip install -e . --quiet

# Update systemd service
cp config/venus-os-fronius-proxy.service /etc/systemd/system/
systemctl daemon-reload
INSTALL

# Restart service
echo ">>> Restarting service..."
ssh "$LXC_HOST" "systemctl restart $SERVICE"

# Wait and check status
sleep 2
echo ">>> Service status:"
ssh "$LXC_HOST" "systemctl status $SERVICE --no-pager -l" || true

echo ""
echo "=== Deploy complete ==="
echo "Dashboard: http://192.168.3.191"
echo "Logs:      ssh $LXC_HOST journalctl -u $SERVICE -f"
