#!/usr/bin/env bash
# Duyệt + merge PR agent, chấm điểm, đóng ticket. CHỈ chạy sau khi CTO đồng ý.
# ops/merge_pr.sh <số PR> <dat|sua_nhe|sua_nang|loai> "<scores k=v,...>" "<lý do>"
set -uo pipefail
source "$(dirname "$0")/env.sh"
n="$1"; label="$2"; scores="$3"; reason="${4:-}"; R="$REPO_THEME"
for c in theme-check preview e2e lighthouse; do
  st=$(gh pr checks "$n" -R "$R" --json name,bucket --jq ".[] | select(.name==\"$c\") | .bucket" 2>/dev/null | head -1)
  [ "$st" = "pass" ] || { echo "Dừng: check $c = ${st:-không có} (cần pass)"; exit 1; }
done
me=$(gh api user --jq .login); lp=$(gh api "repos/$R/pulls/$n/commits" --jq '.[-1].author.login // ""')
br=$(gh pr view "$n" -R "$R" --json headRefName --jq .headRefName); key="${br#feature/ai-}"
if [ "$lp" = "$me" ]; then
  echo "Push cuối là $me (CTO) → không tự duyệt được, merge bằng bypass admin"
  gh pr comment "$n" -R "$R" -b "CTO review: $label — $reason (CTO push commit cuối nên merge bằng --admin)"
  gh pr merge "$n" -R "$R" --squash --delete-branch --admin || exit 1
else
  gh pr review "$n" -R "$R" --approve -b "CTO review: $label — $reason" || exit 1
  gh pr merge "$n" -R "$R" --squash --delete-branch || exit 1
fi
tid=$(python3 - "$key" <<'PY'
import os,sys
sys.path.insert(0, os.path.join(os.environ["AI_TEAM"], "mcp")); import ticket_server as T
print(next((t["id"] for t in T.all() if t.get("key")==sys.argv[1]), ""))
PY
)
if [ -n "$tid" ]; then
  python3 "$AI_TEAM/orchestrator/review.py" "$tid" "$label" --scores "$scores" --by cto --reason "$reason"
  python3 "$AI_TEAM/ops/ticket.py" close "$key" "[cto] PR #$n merge. Review $label. $reason"
fi
git -C "$THEME" checkout -q develop && git -C "$THEME" pull -q --ff-only && echo "develop đã cập nhật"
