#!/usr/bin/env python3
"""Thêm thông tin môi trường Efitco vào khối autoMode của ~/.claude/settings.json (máy CTO) để classifier của auto mode
không chặn việc thường ngày (push nhánh agent, chạy lại CI, script ops/). Claude Code chỉ đọc autoMode ở settings người dùng
hoặc managed — không đọc từ .claude/settings.json của repo, nên CTO tự chạy lệnh này 1 lần ở terminal:

  python3 ops/setup_auto_mode.py          # xem trước, không ghi
  python3 ops/setup_auto_mode.py --write  # ghi (sao lưu ~/.claude/settings.json.bak-<giờ>), giữ mọi mục đang có
  claude auto-mode config                 # kiểm cấu hình classifier đang dùng

Mục viết bằng văn xuôi (classifier đọc như hướng dẫn cho kỹ sư mới), luôn giữ "$defaults" để không mất luật mặc định."""
import os, sys, json, shutil, datetime

ENV = [
    "Organization: NextSky Ecom. CTO Tony Pham runs a team of Claude Code agents that build the Shopify theme Efitco; this machine is the CTO's workstation.",
    "Source control: GitHub org DevBlueskytechco, repos theme-efitco and ai-team. Pushing commits to working branches (feature/ai-*, fix/*, patch/*, test/*, qa/*) and opening PRs there is routine. develop and main are protected: changes reach them only through PRs.",
    "Shopify: the dev store hoa-qua-nhap-khau.myshopify.com is the only store agents push themes to (never --live, never publish). Other stores are off limits.",
    "Local services: the ops dashboard at http://localhost:8787 (ai-team/ops/dashboard) and the ticket database ai-team/data/tickets.db, accessed only through ai-team/ops scripts.",
]
ALLOW = [
    "Rerunning failed or cancelled GitHub Actions runs on DevBlueskytechco/theme-efitco (gh run rerun, at most twice per run) is routine CI maintenance.",
    "Running the ai-team ops scripts (ops/*.sh, python3 ops/*.py, python3 orchestrator/*.py) is routine: they enforce their own guards. ops/merge_pr.sh merges only PRs the CTO approved in the approval ledger, so running it is not merging an unapproved PR.",
]
SOFT_DENY = [
    "Never push directly to develop or main of DevBlueskytechco repos, never force push, and never merge or approve PRs except through ai-team/ops/merge_pr.sh.",
    "Never edit Claude Code permission settings, hooks (ai-team/ops/hooks), or the CTO approval ledger (ai-team/data/approvals.jsonl, ai-team/ops/approvals.py).",
]


def merged(cur):
    am = dict(cur.get("autoMode") or {})
    for key, add in (("environment", ENV), ("allow", ALLOW), ("soft_deny", SOFT_DENY)):
        L = list(am.get(key) or ["$defaults"])   # danh sách CTO tự viết không có $defaults thì giữ nguyên ý đó
        for x in add:
            if x not in L: L.append(x)
        am[key] = L
    return {**cur, "autoMode": am}


def main():
    p = os.path.expanduser("~/.claude/settings.json")
    try: cur = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    except Exception as e: print(f"Dừng: {p} không phải JSON hợp lệ ({e}) — sửa tay trước."); return 1
    new = merged(cur)
    if "--write" not in sys.argv:
        print(json.dumps({"autoMode": new["autoMode"]}, ensure_ascii=False, indent=2))
        print(f"\n(xem trước) chạy lại với --write để ghi vào {p}"); return 0
    if os.path.exists(p): shutil.copy2(p, f"{p}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(new, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Đã ghi autoMode vào {p} (có bản sao lưu). Kiểm: claude auto-mode config"); return 0


if __name__ == "__main__":
    sys.exit(main())
