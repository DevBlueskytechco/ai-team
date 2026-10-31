#!/usr/bin/env bash
# Chạy 1 ticket ai-draft sẵn sàng (hoặc ticket chỉ định): ops/run_next.sh [ES1-Txx]
# Chạy lâu (3–20 phút): Claude Code nên chạy ở chế độ nền.
set -uo pipefail
source "$(dirname "$0")/env.sh"
"$(dirname "$0")/preflight.sh" || { echo "Dừng: preflight lỗi"; exit 1; }
cd "$AI_TEAM"
ARGS=(--once); [ -n "${1:-}" ] && ARGS+=(--ticket "$1")
python3 orchestrator/orchestrate.py "${ARGS[@]}" 2>&1 | tee /tmp/efitco-run-next.log
last=$(tail -1 evals/raw/_runs.jsonl 2>/dev/null)
[ -n "$last" ] && python3 - "$last" <<'PY'
import json,sys
d=json.loads(sys.argv[1])
print("\n== Kết quả lượt chạy")
for k in ("ticket","agent","is_error","num_turns","cost_usd","branch","pushed","pr"): print(f"  {k}: {d.get(k)}")
print("  tóm tắt agent:\n" + "\n".join("    "+l for l in (d.get("result") or "").splitlines()[:25]))
PY
