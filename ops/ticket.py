#!/usr/bin/env python3
"""Thao tác ticket Zoho theo KEY (ES1-T23):
  ticket.py show ES1-T23            in đầy đủ
  ticket.py close ES1-T23 "ghi chú" đóng + comment
  ticket.py comment ES1-T23 "nội dung"
  ticket.py children TE-2           liệt kê ticket con của story"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp")); import ticket_server as T
cmd, arg = sys.argv[1], sys.argv[2]
alls = T.all(); bykey = {t.get("key"): t for t in alls}
if cmd == "children":
    for t in alls:
        if t.get("parent") == arg: print(t.get("key"), t.get("status"), t.get("side"), t.get("points"), t.get("task_type"), (t.get("title") or "")[:110])
    sys.exit()
t = bykey.get(arg) or sys.exit(f"không thấy {arg}")
if cmd == "show":
    f = T.get(t["id"]); [print(f"{k}: {f.get(k)}") for k in ("key","status","agent","task_type","side","points","labels","blocked_by","parent","output_link","title")]
    print("body:", f.get("body")); [print("comment:", c["text"][:400]) for c in f.get("comments", [])]
elif cmd == "close": T.set_status(t["id"], True, sys.argv[3] if len(sys.argv) > 3 else None); print("đã đóng", arg)
elif cmd == "comment": T.comment(t["id"], sys.argv[3]); print("ok")
