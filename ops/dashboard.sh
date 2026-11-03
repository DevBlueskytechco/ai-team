#!/usr/bin/env bash
# Mở dashboard theo dõi agent: ops/dashboard.sh  → http://localhost:8787 (Ctrl+C để dừng)
set -uo pipefail
source "$(dirname "$0")/env.sh"
PORT="${DASHBOARD_PORT:-8787}"
( sleep 2; command -v open >/dev/null && open "http://localhost:$PORT" ) &
exec python3 "$AI_TEAM/ops/dashboard/server.py"
