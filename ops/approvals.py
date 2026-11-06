#!/usr/bin/env python3
"""Sổ duyệt của CTO — việc CTO đã chốt thì Claude Code chạy luôn, không hỏi Yes/No lại.

Ghi sổ (chỉ 2 đường, đều do người làm):
  - Dashboard → Việc chờ tôi → "Chốt merge" (POST /api/approve, máy CTO, localhost)
  - CTO gõ /merge-pr hoặc /apply-patch trong Claude Code → hook UserPromptExpansion (ops/hooks/cto_command.py)
Claude không ghi sổ: CLI này không có lệnh ghi; hook PreToolUse (ops/hooks/guard_bash.py) chặn lệnh đụng sổ.

Đọc / dùng:
  python3 ops/approvals.py list                         việc đã chốt chưa chạy
  python3 ops/approvals.py require merge <PR> [--after <iso>]   in JSON lần chốt còn hiệu lực, không có → mã 1
  python3 ops/approvals.py done merge <PR> [kết quả]    đánh dấu đã chạy (merge_pr.sh / apply_patch.sh gọi)
  python3 ops/approvals.py policy <base> <head> <story>  (danh sách file từ stdin)  in JSON quyền merge chung nếu PR thuộc phạm vi, không → mã 1
Sổ: data/approvals.jsonl (data/ không commit). Hiệu lực: merge 72 giờ, patch 24 giờ."""
import os, sys, json, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "data", "approvals.jsonl")
TTL_H = {"merge": 72, "patch": 24, "merge-policy": 14 * 24}
KIND = {"merge": "merge PR", "patch": "áp patch", "merge-policy": "quyền merge chung"}
# Quyền merge chung (CTO gõ /merge-pr auto <tên> "<lý do>", hết hạn 14 ngày; /merge-pr auto-off <tên> để thu hồi).
# Không áp cho: nhánh đích khác develop, nhánh không phải ticket agent, story ngoài mục tiêu, file đổi cổng kiểm tra.
POLICY_BASE = "develop"
POLICY_HEAD = "feature/ai-ES1-T"
POLICY_DENY_STORY = {"TE-6", "TE-8", "TE-9"}
POLICY_DENY_PATH = (".github/", ".claude/", "scripts/", "playwright.config", "lighthouserc", "package.json", "package-lock.json")


def now(): return datetime.datetime.now().astimezone()

def _t(s):
    try: return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone()
    except Exception: return None

def _rows():
    if not os.path.exists(LEDGER): return []
    out = []
    for l in open(LEDGER, encoding="utf-8"):
        try: out.append(json.loads(l))
        except Exception: pass
    return out

def _append(rec):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as fh: fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def record(kind, ref, by="cto", via="dashboard", **fields):
    """Chỉ dashboard (server.py) và hook cto_command.py gọi."""
    rec = {"at": now().isoformat(timespec="seconds"), "kind": kind, "ref": str(ref), "by": by, "via": via,
           **{k: v for k, v in fields.items() if v not in (None, "")}}
    _append(rec); return rec

def cancel(kind, ref, by="cto", via="dashboard"):
    _append({"at": now().isoformat(timespec="seconds"), "kind": kind, "ref": str(ref), "by": by, "via": via, "state": "cancel"})

def done(kind, ref, result="ok"):
    _append({"at": now().isoformat(timespec="seconds"), "kind": kind, "ref": str(ref), "state": "done", "result": str(result)[:300]})


def pending():
    """Lần chốt mới nhất của mỗi (kind, ref) chưa chạy / chưa huỷ / còn hạn."""
    last = {}
    for r in _rows(): last[(r.get("kind"), r.get("ref"))] = r
    out = []
    for (k, ref), r in last.items():
        if r.get("state"): continue          # done / cancel sau lần chốt
        t = _t(r.get("at"))
        if not t or now() - t > datetime.timedelta(hours=TTL_H.get(k, 24)): continue
        out.append(r)
    return sorted(out, key=lambda r: r["at"])

def find(kind, ref):
    return next((r for r in reversed(pending()) if r["kind"] == kind and r["ref"] == str(ref)), None)


def policy_check(base, head, story, files):
    """Lý do PR nằm ngoài quyền merge chung; None nếu trong phạm vi."""
    if base != POLICY_BASE: return f"nhánh đích {base}, chỉ {POLICY_BASE}"
    if not head.startswith(POLICY_HEAD): return f"nhánh {head} không phải ticket agent"
    if story in POLICY_DENY_STORY or not story: return f"story {story or '(trống)'} ngoài phạm vi"
    bad = [f for f in files if f.startswith(POLICY_DENY_PATH)]
    if bad: return "đổi file cổng kiểm tra: " + ", ".join(bad[:5])
    return None


def main(a):
    if not a or a[0] in ("-h", "--help"): print(__doc__); return 0
    if a[0] == "policy" and len(a) >= 4:
        act = [r for r in pending() if r["kind"] == "merge-policy"]
        if not act:
            print("Không có quyền merge chung còn hiệu lực.", file=sys.stderr); return 1
        why = policy_check(a[1], a[2], a[3], [l.strip() for l in sys.stdin if l.strip()])
        if why:
            print(f"PR ngoài quyền merge chung: {why}. CTO chốt riêng ở Việc chờ tôi hoặc /merge-pr.", file=sys.stderr); return 1
        print(json.dumps(act[-1], ensure_ascii=False)); return 0
    if a[0] == "list":
        P = pending()
        if "--json" in a: print(json.dumps(P, ensure_ascii=False)); return 0
        if not P: print("Không có việc CTO đã chốt đang chờ chạy."); return 0
        for r in P:
            extra = " · ".join(f"{k}={r[k]}" for k in ("label", "scores", "reason", "target", "key") if r.get(k))
            print(f"{KIND.get(r['kind'], r['kind'])} {r['ref']} — chốt {r['at'][:16].replace('T', ' ')} qua {r.get('via')}{' · ' + extra if extra else ''}")
            if r["kind"] == "merge": print(f"  → ops/merge_pr.sh {r['ref']}")
        return 0
    if a[0] == "require" and len(a) >= 3:
        r = find(a[1], a[2])
        if not r:
            print(f"Chưa có CTO chốt {KIND.get(a[1], a[1])} {a[2]} (hoặc đã quá hạn {TTL_H.get(a[1], 24)} giờ). "
                  "CTO chốt ở dashboard → Việc chờ tôi, hoặc gõ /merge-pr, /apply-patch. Không hỏi lại — để việc này ở Việc chờ tôi, làm việc khác.", file=sys.stderr)
            return 1
        if "--after" in a:   # commit cuối của PR mới hơn lần chốt → CTO chốt bản cũ, phải chốt lại
            last = _t(a[a.index("--after") + 1]) if a.index("--after") + 1 < len(a) else None
            if last and last > _t(r["at"]):
                print(f"PR có commit mới ({last:%d/%m %H:%M}) sau khi CTO chốt ({r['at'][:16].replace('T', ' ')}) — CTO cần chốt lại ở Việc chờ tôi.", file=sys.stderr)
                return 1
        print(json.dumps(r, ensure_ascii=False)); return 0
    if a[0] == "done" and len(a) >= 3:
        done(a[1], a[2], " ".join(a[3:]) or "ok"); return 0
    print(__doc__, file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
