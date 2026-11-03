#!/usr/bin/env python3
"""Chuyển toàn bộ ticket + comment từ Zoho Projects sang ticket nội bộ (data/tickets.db). Chạy 1 lần.
   python3 ops/ticket_migrate_zoho.py            # tạo mới; dừng nếu đã có dữ liệu
   python3 ops/ticket_migrate_zoho.py --refresh  # cập nhật lại các ticket gốc Zoho (giữ ticket tạo nội bộ), dùng khi lỡ ghi vào Zoho sau khi chuyển
Gọi Zoho khoảng 1 + số ticket lần (comment từng ticket), nghỉ 0,4s giữa các lần, tự chờ khi bị 429.
Không xoá, không sửa gì trên Zoho (chỉ đọc). Zoho giữ làm bản lưu trữ."""
import os, sys, json, re, time, argparse, datetime, html
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "mcp"))
_envp = os.path.join(ROOT, ".env")
if os.path.exists(_envp):
    for _l in open(_envp):
        if "=" in _l and not _l.strip().startswith("#"): k, v = _l.strip().split("=", 1); os.environ.setdefault(k, v)
import ticket_zoho as Z
import ticket_local as L

ap = argparse.ArgumentParser(); ap.add_argument("--refresh", action="store_true"); a = ap.parse_args()


def call(method, path, params=None):
    for i in range(6):
        try: return Z._req(method, path, params=params)
        except RuntimeError as e:
            if " 429 " in str(e) or "rate" in str(e).lower(): w = 30 * (i + 1); print(f"  Zoho giới hạn, chờ {w}s…"); time.sleep(w); continue
            raise
    raise RuntimeError("Zoho vẫn giới hạn sau 6 lần thử — chạy lại sau")


def local(ts):
    """ISO UTC của Zoho → giờ máy (không kèm múi giờ), giống định dạng ticket nội bộ."""
    if not ts: return None
    try: return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError: return ts[:19]


def who(text, default="cto"):
    m = re.match(r"\[([a-z][\w-]+)\]\s*", text or "")
    return (m.group(1), text[m.end():]) if m else (default, text)


print("Đọc danh sách task Zoho…")
raw, page = [], 1
while True:
    r = call("GET", "/tasks", {"page": page, "per_page": 100}); raw += r.get("tasks", [])
    if not (r.get("page_info") or {}).get("has_next_page"): break
    page += 1; time.sleep(0.4)
print(f"  {len(raw)} task")

exists = os.path.exists(L.DB)
L.init()
c = L.connect()
have = c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
if have and not a.refresh:
    sys.exit(f"Dừng: {L.DB} đã có {have} ticket. Muốn cập nhật lại từ Zoho thì thêm --refresh.")
if exists: print("  sao lưu trước khi ghi:", L.backup())

idmap = {str(z["id"]): z.get("prefix") for z in raw}
n_t = n_c = 0
for z in sorted(raw, key=lambda z: int(re.sub(r"\D", "", (z.get("prefix") or "0").split("-T")[-1]) or 0)):
    key = z.get("prefix")
    if not key or not re.fullmatch(r"[A-Z0-9]+-T\d+", key): print("  bỏ qua task không có key:", z.get("id")); continue
    meta, body = Z._split(z.get("description"))
    closed = bool((z.get("status") or {}).get("is_closed_type"))
    blocked = [idmap.get(str(b), str(b)) for b in meta.get("blocked_by") or []]
    prio = (z.get("priority") or "none").lower(); prio = prio if prio in L.PRIORITIES else "none"
    row = {"id": key, "seq": int(key.split("-T")[-1]), "legacy_id": str(z["id"]), "title": html.unescape(z.get("name") or ""), "body": body,
           "type": meta.get("type") or "task", "status": "Closed" if closed else "Open", "agent": meta.get("agent"),
           "task_type": meta.get("task_type"), "side": meta.get("side"), "points": meta.get("points"),
           "parent": idmap.get(str(meta.get("parent")), meta.get("parent")),
           "priority": prio, "sprint": None, "due_date": (z.get("end_date") or None) and str(z["end_date"])[:10],
           "blocked_by": json.dumps(blocked), "labels": json.dumps(meta.get("labels") or [], ensure_ascii=False),
           "r_codes": json.dumps(meta.get("r_codes") or []), "output_link": meta.get("output_link"),
           "review": json.dumps(meta.get("review") or {}, ensure_ascii=False),
           "created_at": local(z.get("created_time")) or L.now(), "created_by": "zoho", "updated_at": local(z.get("last_modified_time")) or L.now(),
           "closed_at": local(z.get("completed_on")) if closed else None}
    time.sleep(0.4)
    coms = call("GET", f"/tasks/{z['id']}/comments").get("comments", [])
    c.execute("BEGIN IMMEDIATE")
    old = c.execute("SELECT created_by FROM tickets WHERE id=?", (key,)).fetchone()
    if old and old[0] != "zoho":
        c.execute("ROLLBACK"); print(f"  giữ {key}: ticket tạo nội bộ, không ghi đè"); continue
    c.execute("DELETE FROM comments WHERE ticket_id=?", (key,)); c.execute("DELETE FROM activity WHERE ticket_id=? AND field='migrated'", (key,))
    c.execute(f"INSERT OR REPLACE INTO tickets({','.join(row)}) VALUES({','.join('?' * len(row))})", tuple(row.values()))
    for x in sorted(coms, key=lambda x: x.get("created_time") or ""):
        txt = html.unescape(re.sub(r"<br\s*/?>|</p>", "\n", x.get("comment") or x.get("content") or "")); txt = re.sub(r"<[^>]+>", "", txt).strip()
        by, txt = who(txt)
        if txt: c.execute("INSERT INTO comments(ticket_id,by,at,text) VALUES(?,?,?,?)", (key, by, local(x.get("created_time")) or L.now(), txt)); n_c += 1
    c.execute("INSERT INTO activity(ticket_id,by,at,field,old,new) VALUES(?,?,?,?,?,?)",
              (key, "migrate", L.now(), "migrated", None, f"từ Zoho task {z['id']}"))
    c.execute("COMMIT"); n_t += 1
    print(f"  {key:9} {row['status']:6} {len(coms):2} comment  {row['title'][:70]}")

c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('migrated_from_zoho_at',?)", (L.now(),))
tot = c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]; c.close()
print(f"\nXong: {n_t} ticket, {n_c} comment chuyển từ Zoho. Tổng trong {L.DB}: {tot} ticket.")
print("Kiểm: python3 ops/ticket.py show ES1-T1   ·   Dashboard menu Ticket")
