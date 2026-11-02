#!/usr/bin/env bash
# Chờ CI của PR xong rồi in báo cáo: ops/ci_watch.sh <số PR>
set -uo pipefail
source "$(dirname "$0")/env.sh"
sleep 20; gh pr checks "$1" -R "$REPO_THEME" --watch --interval 20 >/dev/null 2>&1
"$(dirname "$0")/pr_report.sh" "$1"
