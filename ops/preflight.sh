#!/usr/bin/env bash
# Kiểm môi trường trước khi chạy agent. Thoát 1 nếu có lỗi chặn.
set -uo pipefail
source "$(dirname "$0")/env.sh"
fail=0; ok(){ echo "OK   $*"; }; bad(){ echo "LỖI $*"; fail=1; }; warn(){ echo "CHÚ Ý $*"; }
for v in TICKET_BACKEND ZOHO_REFRESH_TOKEN AGENT_GH_TOKEN SHOPIFY_CLI_THEME_TOKEN STORE_PASSWORD FIGMA_TOKEN; do
  [ -n "${!v:-}" ] && ok "$v có" || bad "$v thiếu trong ai-team/.env"
done
command -v claude >/dev/null && ok "claude $(claude --version 2>/dev/null | head -1)" || bad "chưa cài claude"
sv=$(shopify version 2>/dev/null | grep -oE '^[0-9]+' | head -1); [ "${sv:-0}" -ge 4 ] && ok "shopify CLI $(shopify version 2>/dev/null)" || bad "shopify CLI phải >= 4"
me=$(gh api user --jq .login 2>/dev/null); [ -n "$me" ] && ok "gh đăng nhập: $me" || bad "gh chưa đăng nhập"
[ "$me" = "nextsky-ai-agent" ] && bad "gh đang là nextsky-ai-agent — phải là tài khoản CTO (unset GH_TOKEN)"
git -C "$AI_TEAM" pull -q --ff-only 2>/dev/null && ok "ai-team đã pull" || warn "ai-team không pull được (có thay đổi local?)"
cur=$(git -C "$THEME" branch --show-current)
[ "$cur" = "develop" ] || { git -C "$THEME" checkout -q develop 2>/dev/null && warn "theme-efitco chuyển từ $cur về develop" || bad "theme-efitco đang ở $cur, không về develop được"; }
git -C "$THEME" pull -q --ff-only 2>/dev/null && ok "theme-efitco develop đã pull" || bad "theme-efitco develop không fast-forward được (git log origin/develop..develop)"
dirty=$(git -C "$THEME" status --porcelain); [ -z "$dirty" ] && ok "theme-efitco sạch" || { bad "theme-efitco có thay đổi chưa commit:"; echo "$dirty" | head -10; }
exit $fail
