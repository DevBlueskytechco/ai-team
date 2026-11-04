#!/usr/bin/env bash
# Gom mọi thứ cần để review 1 PR: ops/pr_report.sh <số PR>
# In: tác giả, người push cuối, CI từng job, bảng điểm Lighthouse + A11Y FAIL, test fail, run.json agent; lưu diff vào /tmp/pr-<n>.diff
set -uo pipefail
source "$(dirname "$0")/env.sh"
n="$1"; R="$REPO_THEME"
gh pr view "$n" -R "$R" --json number,title,author,headRefName,baseRefName,additions,deletions,changedFiles \
  --jq '"PR #\(.number) \(.title)\n  tác giả: \(.author.login)  nhánh: \(.headRefName) -> \(.baseRefName)  +\(.additions) -\(.deletions) / \(.changedFiles) file"'
lp=$(gh api "repos/$R/pulls/$n/commits" --jq '.[-1].author.login // .[-1].commit.author.name' 2>/dev/null)
echo "  push cuối: $lp  (CTO = $(gh api user --jq .login))"
echo "== CI"; gh pr checks "$n" -R "$R" 2>/dev/null | sed 's/^/  /'
run=$(gh pr view "$n" -R "$R" --json statusCheckRollup --jq '[.statusCheckRollup[].detailsUrl] | map(select(test("runs/"))) | .[0]' | grep -oE 'runs/[0-9]+' | cut -d/ -f2)
if [ -n "$run" ]; then
  echo "== Lighthouse / e2e (run $run)"
  gh run view "$run" -R "$R" --log 2>/dev/null | grep -E "perf=|A11Y FAIL|axe serious|console errors|[0-9]+ (passed|failed|skipped)|Error: " | sed -E 's/^[^\t]*\t[^\t]*\t[0-9TZ:.-]+ //' | sort -u | head -40 | sed 's/^/  /'
fi
gh pr diff "$n" -R "$R" > "/tmp/pr-$n.diff" && echo "== Diff: /tmp/pr-$n.diff ($(wc -l < /tmp/pr-$n.diff) dòng)"
br=$(gh pr view "$n" -R "$R" --json headRefName --jq .headRefName); key="${br#feature/ai-}"
for f in "$AI_TEAM"/evals/raw/*/"$key".run.json; do
  [ -f "$f" ] && python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print('== Agent',d['agent'],d['ticket'],'turns',d.get('num_turns'),'token',d.get('tokens')));print(d.get('result','')[:2500])" "$f"
done
