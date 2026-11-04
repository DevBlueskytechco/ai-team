#!/usr/bin/env bash
# Đẩy HEAD lên nhánh làm việc (không bao giờ develop/main, không force) — Claude dùng thay cho lệnh git push ghép nhiều bước có biến,
# để auto mode chạy luôn không hỏi Yes/No.
# ops/push_branch.sh [-C <thư mục repo>] [nhánh đích]   (mặc định: ../theme-efitco, nhánh hiện tại)
set -uo pipefail
source "$(dirname "$0")/env.sh" >/dev/null 2>&1 || true
dir="${THEME:-$(cd "$(dirname "$0")/../../theme-efitco" 2>/dev/null && pwd)}"
if [ "${1:-}" = "-C" ]; then dir="$2"; shift 2; fi
cd "$dir" || { echo "Dừng: không vào được $dir"; exit 1; }
br="${1:-$(git rev-parse --abbrev-ref HEAD)}"; br="${br#refs/heads/}"
case "$br" in
  develop|main|master|HEAD|"") echo "Dừng: không push thẳng '$br' — đẩy lên nhánh feature/ai-*, fix/*, patch/* rồi mở PR."; exit 1;;
  feature/*|fix/*|patch/*|test/*|qa/*|docs/*|chore/*|ci/*|wip/*) ;;
  *) echo "Dừng: nhánh '$br' không theo quy ước (feature/ai-*, fix/*, patch/*, test/*, qa/*, docs/*, chore/*, ci/*)."; exit 1;;
esac
[ -z "$(git status --porcelain --untracked-files=no)" ] || echo "Lưu ý: còn thay đổi chưa commit — chỉ đẩy commit đã có."
git push -q -u origin "HEAD:refs/heads/$br" && echo "Đã đẩy $(git rev-parse --short HEAD) lên origin/$br ($(basename "$dir"))"
