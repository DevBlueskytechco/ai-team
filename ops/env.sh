# Nạp môi trường vận hành. Dùng: source ops/env.sh
# - Nạp ai-team/.env (Zoho, Figma, Shopify, AGENT_GH_TOKEN) cho Orchestrator.
# - KHÔNG để GH_TOKEN đè gh của CTO: lệnh gh trong ops/ chạy bằng tài khoản CTO.
OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export AI_TEAM="$(cd "$OPS_DIR/.." && pwd)"
export THEME="$(cd "$AI_TEAM/../theme-efitco" && pwd)"
set -a; . "$AI_TEAM/.env"; set +a
unset GH_TOKEN GITHUB_TOKEN
export REPO_THEME="DevBlueskytechco/theme-efitco"
