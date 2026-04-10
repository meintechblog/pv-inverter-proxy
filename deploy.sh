#!/usr/bin/env bash
# Deploy pv-inverter-proxy to LXC container (192.168.3.191)
# Usage: ./deploy.sh [--first-time]
set -euo pipefail

# NOTE (Phase 43+): After install.sh runs the blue-green migration,
# /opt/pv-inverter-proxy is a symlink pointing to
# /opt/pv-inverter-proxy-releases/current -> /opt/pv-inverter-proxy-releases/<release>/.
# rsync follows the destination symlink and writes into the real release
# directory, so this script continues to work unchanged on migrated hosts.
#
# For a FIRST-TIME bootstrap on a new LXC, run install.sh on the LXC
# instead of --first-time here. --first-time is kept for backwards compat
# but no longer creates /opt/pv-inverter-proxy as a plain directory.

LXC_HOST="root@192.168.3.191"
REMOTE_DIR="/opt/pv-inverter-proxy"
SERVICE="pv-inverter-proxy"

echo "=== Deploying pv-inverter-proxy to $LXC_HOST ==="

# First-time setup (creates user, venv, apt deps — NOT the install dir)
if [[ "${1:-}" == "--first-time" ]]; then
    echo ">>> First-time setup..."
    echo "    NOTE (Phase 43+): Consider running install.sh on the LXC instead"
    echo "    for a clean blue-green bootstrap:"
    echo "      ssh $LXC_HOST 'curl -fsSL https://raw.githubusercontent.com/meintechblog/pv-inverter-proxy/main/install.sh | bash'"
    echo ""

    ssh "$LXC_HOST" bash -s <<'SETUP'
set -euo pipefail

# Create service user (no login)
id pv-proxy &>/dev/null || useradd -r -s /usr/sbin/nologin pv-proxy

# Create config dir only — do NOT mkdir /opt/pv-inverter-proxy, which would
# interfere with the Phase 43+ blue-green layout (where install_dir is a
# symlink managed by install.sh).
mkdir -p /etc/pv-inverter-proxy

# Install Python + venv + rsync
apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip git rsync

chown -R pv-proxy:pv-proxy /etc/pv-inverter-proxy

echo ">>> First-time prereqs done."
echo ">>> Run install.sh next to create the blue-green layout, then re-run deploy.sh without --first-time."
SETUP
    echo ""
    echo "First-time prereqs installed on $LXC_HOST."
    echo "Next step: ssh $LXC_HOST and run install.sh, then re-run ./deploy.sh (no flags)."
    exit 0
fi

# Sync source code (exclude dev files, .planning, tests, .git*)
# NOTE: We exclude both `.git/` (directory in main checkouts) and `.git`
# (file pointer in git worktrees). Without the file exclude, a deploy from
# a worktree would ship the dangling gitdir pointer to the LXC, breaking
# install.sh migration's `git describe` call with a nosha/v0.0 fallback name.
echo ">>> Syncing source code..."
rsync -avz --delete \
    --exclude '.git/' \
    --exclude '.git' \
    --exclude '.gitignore' \
    --exclude '.planning/' \
    --exclude '.claude/' \
    --exclude 'tests/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.venv/' \
    --exclude 'node_modules/' \
    --exclude '.pytest_cache/' \
    ./ "$LXC_HOST:$REMOTE_DIR/"

# Install package + copy service files
echo ">>> Installing package..."
ssh "$LXC_HOST" bash -s <<'INSTALL'
set -euo pipefail
cd /opt/pv-inverter-proxy
.venv/bin/pip install -e . --quiet

# Update systemd units (main + recovery, Phase 43+).
# The recovery unit is copied even if this is pre-migration — the file is
# harmless until install.sh enables it, and having it in place means the
# next install.sh run has no unit-file copy work left to do.
cp config/pv-inverter-proxy.service /etc/systemd/system/
if [ -f config/pv-inverter-proxy-recovery.service ]; then
    cp config/pv-inverter-proxy-recovery.service /etc/systemd/system/
fi
systemctl daemon-reload
# Enable recovery unit if present (idempotent; safe on pre-migration hosts).
if [ -f /etc/systemd/system/pv-inverter-proxy-recovery.service ]; then
    systemctl enable pv-inverter-proxy-recovery.service 2>/dev/null || true
fi
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
