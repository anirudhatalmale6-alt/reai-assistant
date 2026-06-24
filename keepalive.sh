#!/bin/bash
# REAI keepalive script - keeps server and cloudflare quick tunnel running
# Checks every 5 min via cron. Verifies tunnel URL actually works, not just process alive.

PROJECT_DIR="/var/lib/freelancer/projects/40367525/reai"
PORTAL_DIR="/var/lib/freelancer/projects/40367525/reai-portal"
SERVER_PORT=8081
LOG_DIR="/tmp"

check_server() {
    curl -s -o /dev/null -w "%{http_code}" "http://localhost:${SERVER_PORT}/api/health" 2>/dev/null
}

start_server() {
    cd "$PROJECT_DIR"
    # Load env vars from .env file
    set -a
    source "$PROJECT_DIR/.env"
    set +a
    python3 -c "import uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=${SERVER_PORT})" >> "$LOG_DIR/reai_server.log" 2>&1 &
    echo $! > "$LOG_DIR/reai_server.pid"
}

restart_tunnel() {
    OLD_PID=$(cat "$LOG_DIR/reai_cloudflared.pid" 2>/dev/null)
    [ -n "$OLD_PID" ] && kill "$OLD_PID" 2>/dev/null
    sleep 2
    cloudflared tunnel --config "$PROJECT_DIR/cloudflared.yml" --no-autoupdate > "$LOG_DIR/reai_cloudflared.log" 2>&1 &
    echo $! > "$LOG_DIR/reai_cloudflared.pid"
    sleep 8
    NEW_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_DIR/reai_cloudflared.log" | tail -1)
    if [ -n "$NEW_URL" ]; then
        echo "{\"url\": \"$NEW_URL\", \"updated\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$PORTAL_DIR/tunnel.json"
        cd "$PORTAL_DIR" && git add tunnel.json && git commit -m "Auto-update tunnel URL" && git push origin main 2>/dev/null
        echo "[$(date)] Tunnel restarted. New URL: $NEW_URL"
    else
        echo "[$(date)] ERROR: Tunnel restarted but could not extract URL"
    fi
}

# Main
echo "[$(date)] REAI keepalive check"

# 1. Check server
STATUS=$(check_server)
if [ "$STATUS" != "200" ]; then
    echo "[$(date)] Server down (status: $STATUS), restarting..."
    OLD_PID=$(cat "$LOG_DIR/reai_server.pid" 2>/dev/null)
    [ -n "$OLD_PID" ] && kill "$OLD_PID" 2>/dev/null
    lsof -ti:${SERVER_PORT} | xargs kill -9 2>/dev/null
    sleep 1
    start_server
    sleep 3
fi

# 2. Check tunnel URL actually works
TUNNEL_PID=$(cat "$LOG_DIR/reai_cloudflared.pid" 2>/dev/null)
TUNNEL_ALIVE=false
if [ -n "$TUNNEL_PID" ] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    CURRENT_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_DIR/reai_cloudflared.log" | tail -1)
    if [ -n "$CURRENT_URL" ]; then
        TUNNEL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$CURRENT_URL/api/health" 2>/dev/null)
        if [ "$TUNNEL_STATUS" = "200" ]; then
            TUNNEL_ALIVE=true
        else
            echo "[$(date)] Tunnel URL dead (status: $TUNNEL_STATUS). Restarting..."
        fi
    fi
fi

if [ "$TUNNEL_ALIVE" = false ]; then
    echo "[$(date)] Tunnel needs restart"
    restart_tunnel
fi
