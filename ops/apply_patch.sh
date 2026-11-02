#!/usr/bin/env bash
# Áp 1 file patch (từ Claude chat) thành PR và merge: ops/apply_patch.sh <file.patch> <theme|aiteam> "<tiêu đề PR>"
# Patch lên nhánh PR agent đang mở: ops/apply_patch.sh <file.patch> pr:<số PR>
set -uo pipefail
source "$(dirname "$0")/env.sh"
p="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; target="$2"; title="${3:-patch}"
if [[ "$target" == pr:* ]]; then
  n="${target#pr:}"; br=$(gh pr view "$n" -R "$REPO_THEME" --json headRefName --jq .headRefName)
  cd "$THEME" && git fetch -q origin && git checkout -q "$br" && git pull -q --ff-only
  git am -3 < "$p" || { git am --abort; echo "Dừng: patch không áp được"; exit 1; }
  shopify theme check --fail-level error >/dev/null 2>&1 || { echo "Dừng: theme check lỗi"; shopify theme check | tail -20; exit 1; }
  git push -q && echo "Đã đẩy lên $br (PR #$n)"; git checkout -q develop; exit 0
fi
case "$target" in theme) dir="$THEME"; base=develop;; aiteam) dir="$AI_TEAM"; base=main;; *) echo "target phải là theme|aiteam|pr:<n>"; exit 1;; esac
cd "$dir" && git checkout -q "$base" && git pull -q --ff-only || exit 1
b="patch/$(basename "$p" .patch)-$(date +%H%M%S)"; git checkout -q -b "$b"
git am -3 < "$p" || { git am --abort; git checkout -q "$base"; git branch -D "$b"; echo "Dừng: patch không áp được"; exit 1; }
if [ "$target" = theme ]; then shopify theme check --fail-level error >/dev/null 2>&1 || { echo "Dừng: theme check lỗi"; shopify theme check | tail -20; exit 1; }; fi
git push -q -u origin "$b" && url=$(gh pr create -B "$base" -t "$title" -b "Patch từ Claude (CTO áp qua ops/apply_patch.sh)") && echo "$url"
gh pr merge "$url" --squash --delete-branch --admin && git checkout -q "$base" && git pull -q --ff-only && echo "Đã merge vào $base"
