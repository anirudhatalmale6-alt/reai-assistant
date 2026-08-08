#!/usr/bin/env bash
# REAI one-shot deploy for a fresh Ubuntu 22.04/24.04 server (run as root).
#
#   sudo bash deploy.sh <domain>
#
# <domain> is the hostname pointed at this server (A record -> this IP), e.g.
# reai.example.com. Caddy will fetch a free HTTPS certificate for it automatically.
# Omit it to serve plain HTTP on port 80 (no cert) for a first smoke test.
#
# The app's secrets live in /opt/reai/.env which is copied to the server
# separately (it is NOT in the git repo). This script assumes it is already
# present at /opt/reai/.env, OR it will pause and wait for you to place it.
set -euo pipefail

DOMAIN="${1:-}"
REPO="https://github.com/anirudhatalmale6-alt/reai-real-estate-assistant.git"
APP_DIR="/opt/reai"

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git curl debian-keyring debian-archive-keyring apt-transport-https

echo "==> Creating service user 'reai'"
id -u reai >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/reai --shell /usr/sbin/nologin reai

echo "==> Fetching application code -> $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull --ff-only
else
    # Preserve an already-uploaded .env / data if the dir exists
    mkdir -p "$APP_DIR"
    git clone "$REPO" /tmp/reai-src
    cp -rn /tmp/reai-src/. "$APP_DIR"/
    rm -rf /tmp/reai-src
fi

if [ ! -f "$APP_DIR/.env" ]; then
    echo "!! $APP_DIR/.env is missing. Upload it now (scp) then re-run this script."
    exit 1
fi

echo "==> Python virtualenv + dependencies"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Permissions"
chown -R reai:reai "$APP_DIR"

echo "==> systemd service (always-on, auto-restart, starts on boot)"
cp "$APP_DIR/deploy/reai.service" /etc/systemd/system/reai.service
systemctl daemon-reload
systemctl enable reai
systemctl restart reai
sleep 3
systemctl --no-pager --full status reai | head -12 || true

echo "==> Reverse proxy + HTTPS (Caddy)"
if ! command -v caddy >/dev/null 2>&1; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
fi

if [ -n "$DOMAIN" ]; then
    cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
    reverse_proxy 127.0.0.1:8081
}
EOF
else
    cat > /etc/caddy/Caddyfile <<EOF
:80 {
    reverse_proxy 127.0.0.1:8081
}
EOF
fi
systemctl restart caddy

echo "==> Done."
if [ -n "$DOMAIN" ]; then
    echo "    REAI should be live at: https://$DOMAIN"
else
    echo "    REAI should be live (HTTP only) at this server's IP."
fi
echo "    Health check: curl -s http://127.0.0.1:8081/api/health"
