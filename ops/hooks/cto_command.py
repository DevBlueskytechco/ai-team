#!/usr/bin/env python3
"""Hook UserPromptExpansion: CTO tự gõ /merge-pr hoặc /apply-patch = CTO đã chốt → ghi sổ duyệt (ops/approvals.py),
để ops/merge_pr.sh, ops/apply_patch.sh chạy luôn, không bấm Yes/No lần nữa.
Sự kiện này chỉ chạy khi NGƯỜI gõ lệnh (Claude tự gọi skill không qua đây), nên Claude không tự ghi sổ được."""
import os, sys, json, shlex
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import approvals as AP


def main():
    try: ev = json.load(sys.stdin)
    except Exception: return 0
    if ev.get("hook_event_name") != "UserPromptExpansion" or ev.get("expansion_type") != "slash_command": return 0
    name = str(ev.get("command_name") or "").split(":")[-1]
    try: a = shlex.split(ev.get("command_args") or "")
    except ValueError: a = (ev.get("command_args") or "").split()
    if name == "merge-pr" and a and a[0].lstrip("#").isdigit():
        r = AP.record("merge", a[0].lstrip("#"), via="/merge-pr", label=a[1] if len(a) > 1 else None,
                      scores=a[2] if len(a) > 2 else None, reason=" ".join(a[3:]) or None)
        print(f"CTO đã chốt merge PR #{r['ref']} (ghi sổ duyệt {r['at'][11:16]}). Chạy ops/merge_pr.sh {r['ref']} — không hỏi lại.")
    elif name == "apply-patch" and len(a) >= 2:
        r = AP.record("patch", os.path.basename(a[0]), via="/apply-patch", target=a[1], title=" ".join(a[2:]) or None)
        print(f"CTO đã chốt áp patch {r['ref']} vào {a[1]} (ghi sổ duyệt). Chạy ops/apply_patch.sh — không hỏi lại.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
