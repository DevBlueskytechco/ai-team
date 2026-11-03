"""Ticket nội bộ (SQLite) — nguồn ticket duy nhất của dự án, không phụ thuộc API ngoài.
Giao diện: get, list, create, set_label, comment, set_review, set_task_type, set_status, is_done, update, all.

- File dữ liệu: ai-team/data/tickets.db (không commit). Sao lưu: ops/ticket.py backup | export.
- id ticket = key (ES1-T50). Ticket cũ (trước 03/11/2026) giữ id cũ ở legacy_id; get() nhận cả key lẫn id cũ.
- Nhiều tiến trình dùng chung (Orchestrator, MCP của agent, dashboard, ops/): SQLite WAL + BEGIN IMMEDIATE khi ghi.
- Mọi thay đổi ghi vào bảng activity (ai, lúc nào, trường nào, cũ → mới).
Khôi phục: chép bản mới nhất trong data/backup/ về data/tickets.db. Bắt đầu rỗng: python3 ops/ticket.py init.
"""
import os, json, sqlite3, datetime, re, builtins

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DB = os.environ.get("TICKET_DB") or os.path.join(ROOT, "data", "tickets.db")
PREFIX = "ES1-T"
STATUSES = ("Open", "Closed")
PRIORITIES = ("none", "low", "medium", "high")
JSON_COLS = ("blocked_by", "labels", "r_codes", "review")
FIELDS = ("title", "body", "type", "status", "agent", "task_type", "side", "points", "parent", "priority", "sprint", "due_date",
          "blocked_by", "labels", "r_codes", "output_link", "review")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets(
  id TEXT PRIMARY KEY, seq INTEGER UNIQUE NOT NULL, legacy_id TEXT,
  title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'task', status TEXT NOT NULL DEFAULT 'Open',
  agent TEXT, task_type TEXT, side TEXT, points INTEGER, parent TEXT, priority TEXT NOT NULL DEFAULT 'none', sprint TEXT, due_date TEXT,
  blocked_by TEXT NOT NULL DEFAULT '[]', labels TEXT NOT NULL DEFAULT '[]', r_codes TEXT NOT NULL DEFAULT '[]',
  output_link TEXT, review TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, created_by TEXT, updated_at TEXT NOT NULL, closed_at TEXT);
CREATE INDEX IF NOT EXISTS ix_tickets_legacy ON tickets(legacy_id);
CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, by TEXT, at TEXT NOT NULL, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_comments_t ON comments(ticket_id);
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, by TEXT, at TEXT NOT NULL,
  field TEXT NOT NULL, old TEXT, new TEXT);
CREATE INDEX IF NOT EXISTS ix_activity_t ON activity(ticket_id);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def actor(): return os.environ.get("AI_AGENT") or os.environ.get("TICKET_USER") or "cto"


def connect(create=False):
    if not create and not os.path.exists(DB):
        raise RuntimeError(f"Chưa có dữ liệu ticket nội bộ ({DB}). Khôi phục từ data/backup/ "
                           "hoặc python3 ops/ticket.py init (bắt đầu rỗng).")
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=15000"); c.execute("PRAGMA foreign_keys=ON")
    if create: c.executescript(SCHEMA)
    return c


class _tx:
    """BEGIN IMMEDIATE … COMMIT: khoá ghi giữa các tiến trình, tránh 2 bên cấp trùng số ticket."""
    def __enter__(self):
        self.c = connect(); self.c.execute("BEGIN IMMEDIATE"); return self.c
    def __exit__(self, et, e, tb):
        self.c.execute("ROLLBACK" if et else "COMMIT"); self.c.close()


def _row(r, comments=None, activity=None):
    d = {k: r[k] for k in r.keys()}
    for k in JSON_COLS: d[k] = json.loads(d[k] or ("{}" if k == "review" else "[]"))
    d["key"] = d["id"]
    d["comments"] = comments if comments is not None else []
    if activity is not None: d["activity"] = activity
    return d


def _resolve(c, id):
    id = str(id or "").strip()
    r = c.execute("SELECT * FROM tickets WHERE id=? OR legacy_id=?", (id, id)).fetchone()
    if not r and re.fullmatch(r"\d+", id): r = c.execute("SELECT * FROM tickets WHERE seq=?", (int(id),)).fetchone()
    if not r: raise KeyError(f"không có ticket {id}")
    return r


def _keys(c, ids):
    """Chuẩn hoá danh sách ticket chặn về key (nhận key hoặc id cũ)."""
    out = []
    for b in ids or []:
        try: out.append(_resolve(c, b)["id"])
        except KeyError: out.append(str(b))
    return builtins.list(dict.fromkeys(out))


def _log(c, tid, field, old, new, by=None, at=None):
    enc = lambda v: v if isinstance(v, str) or v is None else json.dumps(v, ensure_ascii=False)
    c.execute("INSERT INTO activity(ticket_id,by,at,field,old,new) VALUES(?,?,?,?,?,?)", (tid, by or actor(), at or now(), field, enc(old), enc(new)))


def _validate(f):
    if "title" in f and not (f["title"] or "").strip(): raise ValueError("tên ticket không được rỗng")
    if "title" in f and len(f["title"]) > 300: raise ValueError("tên ticket tối đa 300 ký tự")
    if f.get("status") is not None and f["status"] not in STATUSES: raise ValueError(f"trạng thái phải là {STATUSES}")
    if f.get("priority") is not None and f["priority"] not in PRIORITIES: raise ValueError(f"độ ưu tiên phải là {PRIORITIES}")
    if f.get("side") not in (None, "", "fe", "be"): raise ValueError("phía phải là fe hoặc be")
    if f.get("points") not in (None, ""):
        try: p = int(f["points"])
        except (TypeError, ValueError): raise ValueError("point phải là số nguyên")
        if not 0 <= p <= 100: raise ValueError("point 0–100")
        f["points"] = p
    if f.get("points") == "": f["points"] = None
    if f.get("parent") not in (None, "") and not re.fullmatch(r"[A-Za-z0-9-]{1,40}", str(f["parent"])): raise ValueError("story/ticket cha không hợp lệ (vd TE-3)")
    if f.get("due_date") not in (None, ""): datetime.date.fromisoformat(f["due_date"])
    for k in ("blocked_by", "labels", "r_codes"):
        if k in f and f[k] is not None and not isinstance(f[k], builtins.list): raise ValueError(f"{k} phải là danh sách")
    if "review" in f and f["review"] is not None and not isinstance(f["review"], dict): raise ValueError("review phải là object")


def _apply(c, r, changes, by=None):
    """Ghi các trường thay đổi + activity. changes đã qua _validate."""
    sets, vals = [], []
    for k, v in changes.items():
        if k not in FIELDS: continue
        old = json.loads(r[k] or ("{}" if k == "review" else "[]")) if k in JSON_COLS else r[k]
        if k == "blocked_by": v = _keys(c, v)
        if v == old or (v in (None, "") and old in (None, "")): continue
        sets.append(f"{k}=?"); vals.append(json.dumps(v, ensure_ascii=False) if k in JSON_COLS else v)
        _log(c, r["id"], k, old if k != "body" else f"{len(old or '')} ký tự", v if k != "body" else f"{len(v or '')} ký tự", by)
        if k == "status":
            sets.append("closed_at=?"); vals.append(now() if v == "Closed" else None)
    if sets:
        sets.append("updated_at=?"); vals.append(now())
        c.execute(f"UPDATE tickets SET {', '.join(sets)} WHERE id=?", (*vals, r["id"]))


# ---------------- giao diện chung (dùng bởi ticket_server, Orchestrator, ops/) ----------------
def get(id):
    c = connect()
    try:
        r = _resolve(c, id)
        com = [dict(x) for x in c.execute("SELECT by, at, text FROM comments WHERE ticket_id=? ORDER BY at, id", (r["id"],))]
        act = [dict(x) for x in c.execute("SELECT by, at, field, old, new FROM activity WHERE ticket_id=? ORDER BY at, id", (r["id"],))]
        return _row(r, com, act)
    finally: c.close()


def all():
    c = connect()
    try:
        n = {x["ticket_id"]: x["n"] for x in c.execute("SELECT ticket_id, COUNT(*) n FROM comments GROUP BY ticket_id")}
        out = []
        for r in c.execute("SELECT * FROM tickets ORDER BY seq"):
            d = _row(r); d["comments_n"] = n.get(r["id"], 0); out.append(d)
        return out
    finally: c.close()


def list(label=None, agent=None, status=None, type=None, sprint=None):
    rows = [t for t in all() if (not label or label in t["labels"]) and (not agent or t["agent"] == agent)
            and (not status or t["status"] == status) and (not type or t["type"] == type) and (not sprint or str(t.get("sprint")) == str(sprint))]
    return [{k: t.get(k) for k in ("id", "key", "title", "type", "agent", "side", "status", "labels", "points", "sprint", "priority")} for t in rows]


def create(title, type="task", agent=None, side=None, points=None, body="", parent=None, blocked_by=None, labels=None, r_codes=None,
           task_type=None, priority="none", sprint=None, due_date=None, by=None):
    f = {"title": (title or "").strip(), "type": type or "task", "agent": agent or None, "side": side or None, "points": points,
         "body": body or "", "parent": parent or None, "blocked_by": blocked_by or [], "labels": labels or [], "r_codes": r_codes or [],
         "task_type": task_type or None, "priority": priority or "none", "sprint": sprint or None, "due_date": due_date or None}
    _validate(f)
    with _tx() as c:
        seq = (c.execute("SELECT COALESCE(MAX(seq),0) FROM tickets").fetchone()[0] or 0) + 1
        prefix = (c.execute("SELECT v FROM meta WHERE k='prefix'").fetchone() or [PREFIX])[0]
        tid, t = f"{prefix}{seq}", now()
        f["blocked_by"] = _keys(c, f["blocked_by"])
        c.execute("""INSERT INTO tickets(id,seq,title,body,type,status,agent,task_type,side,points,parent,priority,sprint,due_date,
                     blocked_by,labels,r_codes,review,created_at,created_by,updated_at) VALUES(?,?,?,?,?,'Open',?,?,?,?,?,?,?,?,?,?,?,'{}',?,?,?)""",
                  (tid, seq, f["title"], f["body"], f["type"], f["agent"], f["task_type"], f["side"], f["points"], f["parent"], f["priority"],
                   f["sprint"], f["due_date"], json.dumps(f["blocked_by"]), json.dumps(f["labels"], ensure_ascii=False),
                   json.dumps(f["r_codes"]), t, by or actor(), t))
        _log(c, tid, "created", None, f["title"], by, t)
    return get(tid)


def update(id, title=None, body=None, by=None, **changes):
    """Sửa tên, body và các trường khác (agent, task_type, side, points, parent, priority, sprint, due_date, blocked_by, labels, r_codes, output_link, status)."""
    f = {k: v for k, v in changes.items() if k in FIELDS}
    if title is not None: f["title"] = title.strip()
    if body is not None: f["body"] = body
    _validate(f)
    with _tx() as c:
        r = _resolve(c, id); _apply(c, r, f, by); tid = r["id"]
    return get(tid)


def set_label(id, label, remove=None, link=None, note=None, by=None):
    with _tx() as c:
        r = _resolve(c, id); old = json.loads(r["labels"])
        labels = [l for l in old if l != remove and l != label and not (label.startswith("ai-") and l.startswith("ai-"))] + [label]
        ch = {"labels": labels}
        if link: ch["output_link"] = link
        _apply(c, r, ch, by)
        if note: c.execute("INSERT INTO comments(ticket_id,by,at,text) VALUES(?,?,?,?)", (r["id"], by or actor(), now(), note))
        tid = r["id"]
    return get(tid)


def comment(id, text, by=None):
    if not (text or "").strip(): raise ValueError("comment rỗng")
    with _tx() as c:
        r = _resolve(c, id)
        c.execute("INSERT INTO comments(ticket_id,by,at,text) VALUES(?,?,?,?)", (r["id"], by or actor(), now(), text.strip()))
        c.execute("UPDATE tickets SET updated_at=? WHERE id=?", (now(), r["id"]))
    return {"ok": True}


def set_review(id, review, label, by=None):
    with _tx() as c:
        r = _resolve(c, id)
        labels = [l for l in json.loads(r["labels"]) if not l.startswith("ai-")] + [label]
        _apply(c, r, {"review": review, "labels": labels}, by); tid = r["id"]
    return get(tid)


def set_task_type(id, task_type, by=None):
    return update(id, task_type=task_type, by=by)


def set_status(id, closed=True, note=None, by=None):
    with _tx() as c:
        r = _resolve(c, id); _apply(c, r, {"status": "Closed" if closed else "Open"}, by)
        if note: c.execute("INSERT INTO comments(ticket_id,by,at,text) VALUES(?,?,?,?)", (r["id"], by or actor(), now(), note))
        tid = r["id"]
    return get(tid)


def is_done(id):
    t = get(id)
    return t["status"] == "Closed" or "ai-dat" in t["labels"]


# ---------------- tiện ích vận hành ----------------
def init(prefix=PREFIX):
    c = connect(create=True)
    c.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('prefix',?)", (prefix,))
    c.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('created_at',?)", (now(),)); c.close()
    return DB


def backup(dest_dir=None, keep=30):
    """Sao lưu nhất quán bằng sqlite backup API → data/backup/tickets-YYYY-MM-DD.db, giữ `keep` bản mới nhất."""
    dest_dir = dest_dir or os.path.join(os.path.dirname(DB), "backup"); os.makedirs(dest_dir, exist_ok=True)
    dst = os.path.join(dest_dir, f"tickets-{datetime.date.today().isoformat()}.db")
    src = connect(); out = sqlite3.connect(dst); src.backup(out); out.close(); src.close()
    olds = sorted(f for f in os.listdir(dest_dir) if f.startswith("tickets-") and f.endswith(".db"))
    for f in olds[:-keep]: os.remove(os.path.join(dest_dir, f))
    return dst


def export():
    c = connect()
    try:
        return {"exported_at": now(), "tickets": [_row(r) for r in c.execute("SELECT * FROM tickets ORDER BY seq")],
                "comments": [dict(x) for x in c.execute("SELECT * FROM comments ORDER BY id")],
                "activity": [dict(x) for x in c.execute("SELECT * FROM activity ORDER BY id")]}
    finally: c.close()


DAYS = ("Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật")

def get_roles():
    """Role owner và ngày duyệt cố định CTO đã sửa trên dashboard: {vai trò: {owner, day, by, at}}."""
    c = connect()
    try:
        r = c.execute("SELECT v FROM meta WHERE k='roles'").fetchone()
        return json.loads(r[0]) if r else {}
    finally: c.close()

def set_roles(changes, by=None):
    """changes: [{role, owner, day}]. Ghi đè từng vai, giữ 200 thay đổi gần nhất ở meta roles_log."""
    with _tx() as c:
        cur = json.loads((c.execute("SELECT v FROM meta WHERE k='roles'").fetchone() or ["{}"])[0])
        log = json.loads((c.execute("SELECT v FROM meta WHERE k='roles_log'").fetchone() or ["[]"])[0])
        for ch in changes or []:
            role, owner, day = str(ch.get("role") or "").strip(), str(ch.get("owner") or "").strip(), str(ch.get("day") or "").strip()
            if not role or len(role) > 60: raise ValueError("vai trò không hợp lệ")
            if len(owner) > 60: raise ValueError("role owner tối đa 60 ký tự")
            if day and day not in DAYS: raise ValueError(f"ngày duyệt phải là một trong {', '.join(DAYS)}")
            new = {"owner": owner, "day": day, "by": by or actor(), "at": now()}
            log.append({"role": role, "old": cur.get(role), "new": new}); cur[role] = new
        c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('roles',?)", (json.dumps(cur, ensure_ascii=False),))
        c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('roles_log',?)", (json.dumps(log[-200:], ensure_ascii=False),))
    return get_roles()

def version():
    """Dấu thay đổi rẻ để dashboard biết khi nào cần đọc lại."""
    c = connect()
    try:
        a = c.execute("SELECT COUNT(*), COALESCE(MAX(updated_at),'') FROM tickets").fetchone()
        b = c.execute("SELECT (SELECT COALESCE(MAX(id),0) FROM comments), (SELECT COALESCE(MAX(id),0) FROM activity)").fetchone()
        return f"{a[0]}|{a[1]}|{b[0]}|{b[1]}"
    finally: c.close()
