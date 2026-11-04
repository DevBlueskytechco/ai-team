#!/usr/bin/env python3
"""Bảng trạng thái sprint: ticket đang mở (sẵn sàng/bị chặn/chờ duyệt), PR mở + CI, CI develop gần nhất, hạn mức gói Claude.
Chạy: source ops/env.sh && python3 ops/status.py"""
import os, sys, json, subprocess, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp")); import ticket_server as T
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))
os.environ.pop("GH_TOKEN", None)

def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True); return r.stdout.strip() if r.returncode == 0 else ""

rows = [t for t in T.all() if (t.get("status") or "").lower() != "closed"]
key = lambda t: int("".join(c for c in (t.get("key") or "0").split("-T")[-1] if c.isdigit()) or 0)
ids = {t["id"]: t for t in T.all()}
print(f"== Ticket đang mở ({T.BACKEND})")
for t in sorted(rows, key=key):
    labels = ",".join(t.get("labels") or []) or "-"
    bl = [ids.get(b, {}).get("key", b) for b in (t.get("blocked_by") or [])
          if (ids.get(b, {}).get("status") or "").lower() != "closed"]
    title = t.get("title") or ""
    if bl: state = "CHỜ " + ",".join(bl)
    elif (t.get("type") == "question" or title.startswith("[Q]") or re.search(r"(^|\s)hỏi[\s:(]", title.lower()[:40])) and not (
            t.get("agent") and (t.get("task_type") or (t.get("agent") in ("dev-fe", "dev-be") and t.get("side"))) and not title.startswith("[Q]")):
        state = "CÂU HỎI cho CTO"   # cùng quy tắc với dashboard: câu hỏi agent làm được (có task_type) thì theo nhãn ai-*
    elif not t.get("labels"): state = "CHƯA NHÃN"
    elif "ai-review" in t["labels"]: state = "CHỜ CTO chấm"
    elif "ai-draft" in t["labels"] and t.get("agent"): state = "SẴN SÀNG"
    else: state = ""
    print(f"  {t.get('key'):8} {labels:12} {t.get('agent') or '-':10} {t.get('task_type') or '-':20} {state:18} {(t.get('title') or '')[:70]}")
print("\n== PR đang mở (theme-efitco)")
prs = sh("gh", "pr", "list", "-R", "DevBlueskytechco/theme-efitco", "--json", "number,title,author,headRefName,statusCheckRollup")
for p in json.loads(prs or "[]"):
    checks = {c.get("name"): (c.get("conclusion") or c.get("status") or "").lower() for c in p.get("statusCheckRollup") or []}
    cs = " ".join(f"{n}={v}" for n, v in sorted(checks.items()))
    print(f"  #{p['number']} {p['author']['login']:18} {p['headRefName']:24} {cs}")
print("\n== CI develop gần nhất")
print("  " + (sh("gh", "run", "list", "-R", "DevBlueskytechco/theme-efitco", "-b", "develop", "-L", "1",
                 "--json", "databaseId,conclusion,status,displayTitle", "--jq",
                 '.[0] | "\\(.databaseId) \\(.status)/\\(.conclusion) \\(.displayTitle)"') or "(không lấy được)"))
print("\n== Gói Claude (hạn mức agent dùng chung với CTO)")
try:
    import yaml, plan_usage as PU
    cfg = yaml.safe_load(open(os.path.join(ROOT, "orchestrator", "config.yaml"), encoding="utf-8")) or {}
    stop, warns, line = PU.check(cfg)   # số đọc gần nhất (dashboard / Orchestrator đọc định kỳ); đọc ngay: python3 orchestrator/plan_usage.py --refresh
    print(f"  {line}"); [print(f"  CẢNH BÁO: {w}") for w in warns]
    if stop: print(f"  DỪNG: {stop}")
except Exception as e: print(f"  (không đọc được: {e})")
