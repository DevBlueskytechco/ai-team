#!/usr/bin/env python3
"""Thao tác ticket nội bộ (data/tickets.db) theo KEY (ES1-T23):
  ticket.py show ES1-T23              in đầy đủ (kèm comment, lịch sử)
  ticket.py close ES1-T23 "ghi chú"   đóng + comment
  ticket.py reopen ES1-T23 "ghi chú"  mở lại
  ticket.py label ES1-T23 ai-draft    đổi nhãn ai-* (vd đưa ticket sửa nặng về chạy lại)
  ticket.py comment ES1-T23 "nội dung"
  ticket.py children TE-2             liệt kê ticket con của story
  ticket.py init                      tạo data/tickets.db rỗng
  ticket.py backup                    sao lưu data/backup/tickets-YYYY-MM-DD.db (giữ 30 bản)
  ticket.py export [file.json]        xuất toàn bộ ticket + comment + lịch sử ra JSON"""
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp")); import ticket_server as T
cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
arg = sys.argv[2] if len(sys.argv) > 2 else ""
extra = sys.argv[3] if len(sys.argv) > 3 else None

if cmd in ("init", "backup", "export"):
    import ticket_local as L
    if cmd == "init": print("đã tạo", L.init()); sys.exit()
    if cmd == "backup": print("đã sao lưu", L.backup()); sys.exit()
    out = arg or os.path.join(ROOT, "data", "tickets-export.json")
    json.dump(L.export(), open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print("đã xuất", out); sys.exit()
if cmd == "help" or not arg: sys.exit(__doc__)

alls = T.all(); bykey = {t.get("key"): t for t in alls}
if cmd == "children":
    for t in alls:
        if t.get("parent") == arg: print(t.get("key"), t.get("status"), t.get("side"), t.get("points"), t.get("task_type"), (t.get("title") or "")[:110])
    sys.exit()
t = bykey.get(arg) or sys.exit(f"không thấy {arg}")
if cmd == "show":
    f = T.get(t["id"])
    for k in ("key", "status", "agent", "task_type", "side", "points", "priority", "labels", "blocked_by", "parent", "output_link", "title"): print(f"{k}: {f.get(k)}")
    print("body:", f.get("body"))
    for c in f.get("comments", []): print(f"comment {c.get('at', '')} {c.get('by', '')}: {c['text'][:400]}")
    for a in f.get("activity", [])[-15:]: print(f"lịch sử {a['at']} {a['by']}: {a['field']} {a['old'] or ''} → {a['new'] or ''}"[:300])
elif cmd == "close": T.set_status(t["id"], True, extra); print("đã đóng", arg)
elif cmd == "reopen": T.set_status(t["id"], False, extra); print("đã mở lại", arg)
elif cmd == "label": T.set_label(t["id"], extra, note=sys.argv[4] if len(sys.argv) > 4 else None); print("đã gắn", extra, "cho", arg)
elif cmd == "comment": T.comment(t["id"], extra); print("ok")
else: sys.exit(__doc__)
