#!/usr/bin/env bash
# Duyệt + merge PR agent, chấm điểm, đóng ticket. CHỈ chạy khi CTO đã chốt trong sổ duyệt (ops/approvals.py):
# dashboard → Việc chờ tôi → "Chốt merge", hoặc CTO gõ /merge-pr. Có sổ thì chạy luôn, không hỏi Yes/No.
# ops/merge_pr.sh <số PR> [<dat|sua_nhe|sua_nang|loai> "<scores k=v,...>" "<lý do>"]   — nhãn/điểm/lý do lấy theo sổ khi CTO đã ghi
set -uo pipefail
source "$(dirname "$0")/env.sh"
n="${1#\#}"; R="$REPO_THEME"
last=$(gh api "repos/$R/pulls/$n/commits" --jq '.[-1].commit.committer.date' 2>/dev/null)
appr=$(python3 "$AI_TEAM/ops/approvals.py" require merge "$n" ${last:+--after "$last"}) || exit 1
jf() { python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get(sys.argv[2]) or "")' "$appr" "$1"; }
label=$(jf label); scores=$(jf scores); reason=$(jf reason)
label="${label:-${2:-}}"; scores="${scores:-${3:-}}"; reason="${reason:-${4:-}}"
[ -n "$label" ] && [ -n "$scores" ] || { echo "Dừng: sổ duyệt PR #$n thiếu nhãn/điểm — CTO chốt lại ở Việc chờ tôi"; exit 1; }
echo "CTO đã chốt PR #$n: $label · $scores · $reason ($(jf via) $(jf at))"
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
  if ! gh pr merge "$n" -R "$R" --squash --delete-branch; then
    # Ruleset require_last_push_approval: CTO push commit cuối (author commit theo git user local khác login gh)
    # → approve của CTO không tính. Check đã pass + sổ duyệt đã có → bypass admin.
    rd=$(gh pr view "$n" -R "$R" --json reviewDecision --jq .reviewDecision)
    [ "$rd" = "REVIEW_REQUIRED" ] || exit 1
    echo "Approve CTO không tính (push cuối từ tài khoản CTO) → merge bằng bypass admin"
    gh pr comment "$n" -R "$R" -b "CTO review: $label — $reason (push cuối từ tài khoản CTO nên merge bằng --admin)"
    gh pr merge "$n" -R "$R" --squash --delete-branch --admin || exit 1
  fi
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
python3 "$AI_TEAM/ops/approvals.py" done merge "$n" "merged $label"
git -C "$THEME" checkout -q develop && git -C "$THEME" pull -q --ff-only && echo "develop đã cập nhật"
