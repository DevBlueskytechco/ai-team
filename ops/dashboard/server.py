#!/usr/bin/env python3
"""Dashboard theo dõi agent Efitco — chạy local, chỉ nghe 127.0.0.1.
   cd ai-team && source ops/env.sh && python3 ops/dashboard/server.py   → http://localhost:8787
Nguồn dữ liệu (không lộ bí mật ra trình duyệt):
  - evals/raw/_live.json, evals/raw/live/<key>.jsonl   agent đang chạy (Orchestrator ghi, cập nhật mỗi lượt)   — đọc mỗi 2s
  - evals/raw/_runs.jsonl                               lịch sử lượt chạy, chi phí                               — mỗi 2s
  - Ticket nội bộ (mcp/ticket_local, data/tickets.db)  đọc lại khi dữ liệu đổi (kiểm dấu mỗi 2s)
  - Ghi ticket từ giao diện (menu Ticket): POST /api/ticket/* — chỉ từ localhost, cần header X-Efitco
  - gh CLI (tài khoản CTO)                              PR mở + CI, CI develop                                   — mỗi 60s
Đẩy dữ liệu xuống trình duyệt bằng Server-Sent Events (/events) khi có thay đổi."""
import os, sys, json, time, threading, subprocess, hashlib, datetime, html, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
THEME = os.path.abspath(os.path.join(ROOT, "..", "theme-efitco"))
RAW = os.path.join(ROOT, "evals", "raw")
REPO = os.environ.get("REPO_THEME", "DevBlueskytechco/theme-efitco")
PORT = int(os.environ.get("DASHBOARD_PORT", "8787"))
sys.path.insert(0, os.path.join(ROOT, "mcp"))
os.environ.pop("GH_TOKEN", None)

try:
    import yaml; CFG = yaml.safe_load(open(os.path.join(ROOT, "orchestrator", "config.yaml")))
except Exception:
    CFG = {"budget_usd_month": 2000, "budget_warn_pct": 80}

STATE = {"tickets": [], "prs": [], "merged": [], "ci_develop": [], "tickets_at": None, "gh_at": None, "errors": {}, "backend": None}
UI_USER = os.environ.get("TICKET_UI_USER", "cto")   # người ghi khi thao tác trên dashboard
LOCK = threading.Lock()
VERSION = {"n": 0, "hash": ""}

def sh(*a, timeout=60):
    """Chạy lệnh, lỗi thì raise để dashboard báo (vd gh chưa đăng nhập)."""
    r = subprocess.run(a, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError(f"{' '.join(a[:3])}: {(r.stderr or r.stdout).strip()[:160]}")
    return r.stdout

# ---------- nguồn chậm ----------
import ticket_server as T
TICKET_FIELDS = ("key", "id", "status", "type", "agent", "task_type", "side", "points", "labels", "parent", "blocked_by", "created_at",
                 "output_link", "priority", "sprint", "due_date", "updated_at", "closed_at", "created_by", "comments_n", "r_codes")

def load_tickets():
    rows = []
    for t in T.all():
        rows.append({k: t.get(k) for k in TICKET_FIELDS} |
                    {"title": html.unescape(t.get("title") or ""), "review": {k: (t.get("review") or {}).get(k) for k in ("severity", "scores", "by", "at", "reason")}})
    with LOCK: STATE["tickets"] = rows; STATE["tickets_at"] = now(); STATE["backend"] = T.BACKEND; STATE["errors"].pop("ticket", None)

def poll_tickets():
    """Đọc lại ngay khi dữ liệu đổi (kiểm dấu mỗi 2s), tối thiểu 60s đọc đủ 1 lần."""
    import ticket_local as L
    last, last_full = None, 0
    while True:
        try:
            v = L.version()
            if v != last or time.time() - last_full > 60: load_tickets(); last, last_full = v, time.time()
        except Exception as e:
            with LOCK: STATE["errors"]["ticket"] = str(e)[:300]; STATE["backend"] = T.BACKEND
        time.sleep(2)

def backup_daily():
    """Ticket nội bộ: sao lưu 1 bản/ngày vào data/backup/ (giữ 30 bản)."""
    while True:
        try:
            import ticket_local as L
            d = os.path.join(os.path.dirname(L.DB), "backup", f"tickets-{datetime.date.today().isoformat()}.db")
            if os.path.exists(L.DB) and not os.path.exists(d): L.backup()
        except Exception as e:
            with LOCK: STATE["errors"]["backup"] = str(e)[:200]
        time.sleep(3600)

def required_checks():
    try:
        m = re.search(r"^required_checks:\s*\[(.*?)\]", open(os.path.join(ROOT, "orchestrator", "config.yaml"), encoding="utf-8").read(), re.M)
        if m: return [x.strip() for x in m.group(1).split(",") if x.strip()]
    except OSError: pass
    return ["theme-check", "preview", "e2e"]

JOBS = {}   # run id → {job: kết luận}; run đã xong thì giữ, không gọi lại
def run_jobs(r):
    rid = r.get("databaseId")
    if rid in JOBS: return JOBS[rid]
    jobs = {j["name"]: (j.get("conclusion") or j.get("status") or "").lower()
            for j in json.loads(sh("gh", "run", "view", str(rid), "-R", REPO, "--json", "jobs") or "{}").get("jobs", [])}
    if r.get("status") == "completed": JOBS[rid] = jobs
    return jobs

PENDING = ("queued", "in_progress", "pending", "waiting", "requested", "expected", "")
def poll_gh():
    while True:
        busy = False
        try:
            prs = json.loads(sh("gh", "pr", "list", "-R", REPO, "--json", "number,title,author,headRefName,createdAt,statusCheckRollup,url") or "[]")
            out = []
            for p in prs:
                checks = {}
                for c in p.get("statusCheckRollup") or []:
                    n = c.get("name") or c.get("context")
                    checks[n] = (c.get("conclusion") or c.get("state") or c.get("status") or "").lower()
                out.append({"number": p["number"], "title": p["title"], "author": p["author"]["login"], "branch": p["headRefName"],
                            "created": p["createdAt"], "url": p["url"], "checks": checks})
            runs = json.loads(sh("gh", "run", "list", "-R", REPO, "-b", "develop", "-w", "CI", "-e", "push", "-L", "5", "--json",
                                 "databaseId,status,conclusion,displayTitle,createdAt,url,workflowName,headSha,event") or "[]")
            for r in runs[:3]:
                try: r["jobs"] = run_jobs(r)
                except Exception: r["jobs"] = {}
            busy = any(v in PENDING for p in out for v in p["checks"].values()) or any(r.get("status") != "completed" for r in runs[:1])
            merged = json.loads(sh("gh", "pr", "list", "-R", REPO, "--state", "merged", "-L", "100", "--json",
                                   "number,title,headRefName,createdAt,mergedAt,url") or "[]")
            merged = [{"number": p["number"], "title": p["title"], "branch": p["headRefName"], "createdAt": p["createdAt"],
                       "mergedAt": p["mergedAt"], "url": p["url"]} for p in sorted(merged, key=lambda p: p.get("mergedAt") or "", reverse=True)]
            with LOCK: STATE["prs"] = out; STATE["merged"] = merged; STATE["ci_develop"] = runs; STATE["gh_at"] = now(); STATE["errors"].pop("gh", None)
        except Exception as e:
            with LOCK: STATE["errors"]["gh"] = str(e)[:200]
        time.sleep(20 if busy else 60)   # CI đang chạy thì cập nhật nhanh hơn

# ---------- nguồn nhanh (file local) ----------
def read_runs():
    p = os.path.join(RAW, "_runs.jsonl"); out = []
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            try: r = json.loads(l)
            except Exception: continue
            out.append({k: r.get(k) for k in ("agent", "ticket", "started_at", "ended_at", "duration_s", "num_turns", "is_error", "pr", "branch", "model")})
    return sorted(out, key=lambda r: r.get("started_at") or "")

def _etime(v):
    """ps etime [[dd-]hh:]mm:ss → giây."""
    d, _, rest = v.strip().rpartition("-"); parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3: parts.insert(0, 0)
    return (int(d) if d else 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]

def ps_agent():
    """Tìm tiến trình `claude -p --agent X ... Ticket ES1-Txx` đang chạy — không phụ thuộc Orchestrator có ghi _live.json hay không."""
    try: out = subprocess.run(["ps", "-axww", "-o", "pid=,etime=,command="], capture_output=True, text=True, timeout=10).stdout
    except Exception: return None
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)", line)
        if not m: continue
        cmd = m.group(3)
        if " -p " not in cmd or "--agent " not in cmd or "claude" not in cmd.split(" --agent")[0]: continue
        a = re.search(r"--agent\s+(\S+)", cmd); k = re.search(r"Ticket\s+([A-Z0-9]+-T?\d+)", cmd)
        if a and k: return {"pid": int(m.group(1)), "agent": a.group(1), "ticket": k.group(1), "elapsed_s": _etime(m.group(2))}
    return None

def transcript_for(since_epoch):
    """Transcript Claude Code của lượt agent (ghi liên tục vào ~/.claude/projects/<thư mục theme>/<session>.jsonl)."""
    import glob
    base = os.path.expanduser("~/.claude/projects")
    slug = re.sub(r"[^A-Za-z0-9]", "-", THEME)
    dirs = [os.path.join(base, slug)] + [d for d in glob.glob(os.path.join(base, "*theme-efitco")) if not d.endswith(slug)]
    files = [f for d in dirs for f in glob.glob(os.path.join(d, "*.jsonl")) if os.path.getmtime(f) >= since_epoch - 30]
    return max(files, key=os.path.getmtime) if files else None

def _count(path):
    """Đếm lượt/tool + hành động gần nhất từ file sự kiện (stream-json hoặc transcript)."""
    turns, tools, last = set(), 0, ""
    for line in open(path, encoding="utf-8").readlines()[-2000:]:
        try: e = json.loads(line)
        except Exception: continue
        if e.get("type") != "assistant": continue
        msg = e.get("message") or {}; turns.add(msg.get("id") or e.get("uuid") or len(turns))
        for c in msg.get("content") or []:
            if c.get("type") == "tool_use":
                tools += 1; i = c.get("input") or {}
                last = f"{c.get('name')} " + str(i.get("command") or i.get("file_path") or i.get("pattern") or "")[:140]
            elif c.get("type") == "text" and c.get("text", "").strip():
                last = c["text"].strip().replace("\n", " ")[:160]
    return len(turns), tools, last

LIVE_SRC = {}   # ticket → file sự kiện đang dùng cho /api/live

def read_live():
    """Agent đang chạy. Ưu tiên _live.json (Orchestrator mới); nếu thiếu/cũ thì dò tiến trình + transcript."""
    p = os.path.join(RAW, "_live.json")
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            os.kill(int(d.get("pid") or 0), 0)          # còn sống?
            st = datetime.datetime.fromisoformat(d["started_at"]); d["elapsed_s"] = int((datetime.datetime.now() - st).total_seconds())
            d.update(alive=True, source="stream"); LIVE_SRC[d["ticket"]] = os.path.join(ROOT, d.get("log") or "")
            return d
        except Exception:
            pass                                         # file sót lại sau khi Orchestrator bị kill → bỏ qua
    a = ps_agent()
    if not a: return None
    with LOCK: t = next((x for x in STATE["tickets"] if x.get("key") == a["ticket"]), {})
    d = a | {"title": t.get("title", ""), "alive": True, "source": "ps", "turns": 0, "tools": 0, "last": "",
             "started_at": (datetime.datetime.now() - datetime.timedelta(seconds=a["elapsed_s"])).isoformat(timespec="seconds")}
    tr = transcript_for(time.time() - a["elapsed_s"])
    if tr:
        LIVE_SRC[a["ticket"]] = tr
        d["turns"], d["tools"], d["last"] = _count(tr)
    return d

def live_events(key, limit=60):
    """Rút gọn stream-json của 1 ticket thành dòng sự kiện đọc được."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key or ""): return []
    p = LIVE_SRC.get(key) or os.path.join(RAW, "live", f"{key}.jsonl")
    if not os.path.exists(p): return []
    ev = []
    for line in open(p, encoding="utf-8").readlines()[-400:]:
        try: e = json.loads(line)
        except Exception: continue
        t = e.get("type")
        if t == "assistant":
            for c in (e.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use":
                    i = c.get("input") or {}
                    ev.append({"kind": "tool", "name": c.get("name"), "text": str(i.get("command") or i.get("file_path") or i.get("pattern") or i.get("description") or "")[:200]})
                elif c.get("type") == "text" and c.get("text", "").strip():
                    ev.append({"kind": "say", "text": c["text"].strip()[:400]})
        elif t == "user":
            for c in (e.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                    txt = c.get("content"); txt = txt if isinstance(txt, str) else json.dumps(txt)[:200]
                    ev.append({"kind": "error", "text": str(txt)[:200]})
        elif t == "result":
            ev.append({"kind": "done", "text": f"xong · {e.get('num_turns')} turn · {round((e.get('duration_ms') or 0) / 60000, 1)} phút · lỗi={e.get('is_error')}"})
    return ev[-limit:]

def now(): return datetime.datetime.now().astimezone().isoformat(timespec="seconds")   # kèm múi giờ để trình duyệt tính "x phút trước" đúng

def evals_count():
    """Số bản ghi eval (evals/raw/<agent>/<ticket>.json, không tính .run.json) — mục tiêu charter ≥ 300."""
    n = 0
    for a in os.listdir(RAW) if os.path.isdir(RAW) else []:
        d = os.path.join(RAW, a)
        if os.path.isdir(d) and a != "live": n += sum(1 for f in os.listdir(d) if f.endswith(".json") and not f.endswith(".run.json"))
    return n

def read_rubrics():
    """rubrics/<agent>.yaml → {agent: {pass_threshold, criteria: [{id, text}]}} (đọc bằng regex, không cần pyyaml)."""
    out = {}
    d = os.path.join(ROOT, "rubrics")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith(".yaml"): continue
        txt = open(os.path.join(d, f), encoding="utf-8").read()
        m = re.search(r"^pass_threshold:\s*([0-9.]+)", txt, re.M)
        crit = [{"id": i, "text": t} for i, t in re.findall(r'^\s*-\s*id:\s*(\S+)\s*\n\s*text:\s*"?(.*?)"?\s*$', txt, re.M)]
        out[f[:-5]] = {"pass_threshold": float(m.group(1)) if m else 0.8, "criteria": crit}
    return out

def roles_merged():
    """Bảng Vai trò = project.json (mặc định) đè bởi giá trị CTO sửa trên dashboard (data/tickets.db meta roles)."""
    import ticket_local as L
    pj = json.load(open(os.path.join(HERE, "project.json"), encoding="utf-8"))
    rows = next(p for p in pj["pages"] if p["id"] == "roles")["rows"]
    try: ov = L.get_roles()
    except Exception: ov = {}
    out = []
    for r in rows:
        role, owner, day, agent, note = (list(r) + [""] * 5)[:5]
        o = ov.get(role, {})
        out.append({"role": role, "owner": o.get("owner", owner), "day": o.get("day", day), "agent": agent if agent not in ("", "—") else None,
                    "note": note, "default_owner": owner, "default_day": day, "edited_by": o.get("by"), "edited_at": o.get("at")})
    return {"rows": out, "days": list(L.DAYS)}

def snapshot():
    runs = read_runs()
    with LOCK:
        s = {k: STATE[k] for k in ("tickets", "prs", "merged", "ci_develop", "tickets_at", "gh_at", "backend")} | {"errors": dict(STATE["errors"])}
    s.update({"live": read_live(), "runs": runs[-500:], "server_time": now(), "evals_n": evals_count(), "required_checks": required_checks()})
    return s

def ticker():
    while True:
        s = snapshot(); s.pop("server_time")
        h = hashlib.sha1(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()
        if h != VERSION["hash"]: VERSION["hash"] = h; VERSION["n"] += 1
        time.sleep(2)

TICKET_EDITABLE = ("title", "body", "type", "agent", "task_type", "side", "points", "parent", "priority", "sprint", "due_date",
                   "blocked_by", "labels", "r_codes", "output_link")

def ticket_write(action, d):
    """Thao tác ticket từ giao diện. Trả ticket sau khi ghi."""
    import ticket_local as L
    tid = str(d.get("id") or "")
    if action == "create":
        f = {k: d.get(k) for k in TICKET_EDITABLE if k in d and k != "output_link"}
        return L.create(by=UI_USER, **f)
    if action == "update":
        return L.update(tid, by=UI_USER, **{k: d[k] for k in TICKET_EDITABLE if k in d})
    if action == "status":
        return L.set_status(tid, bool(d.get("closed")), (d.get("note") or "").strip() or None, by=UI_USER)
    if action == "comment":
        L.comment(tid, d.get("text") or "", by=UI_USER); return L.get(tid)
    if action == "label":
        return L.set_label(tid, str(d.get("label") or ""), note=(d.get("note") or "").strip() or None, by=UI_USER)
    raise ValueError("thao tác không hỗ trợ")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _local_ok(self):
        """Chống web khác gọi vào localhost: Host phải là localhost/127.0.0.1, có header X-Efitco (form/ảnh từ site lạ không đặt được)."""
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("localhost", "127.0.0.1") and self.headers.get("X-Efitco") == "1"
    def do_POST(self):
        u = urlparse(self.path)
        if u.path not in ("/api/roles/update",) and not u.path.startswith("/api/ticket/"): return self._send(404, '{"error":"not found"}')
        if not self._local_ok(): return self._send(403, json.dumps({"error": "chỉ nhận từ dashboard trên localhost"}))
        if u.path == "/api/roles/update":
            try:
                import ticket_local as L
                n = int(self.headers.get("Content-Length") or 0)
                if n > 50_000: return self._send(413, '{"error":"quá lớn"}')
                d = json.loads(self.rfile.read(n) or b"{}"); known = {r["role"] for r in roles_merged()["rows"]}
                bad = [c.get("role") for c in d.get("changes", []) if c.get("role") not in known]
                if bad: return self._send(400, json.dumps({"error": f"không có vai trò {', '.join(map(str, bad))}"}, ensure_ascii=False))
                L.set_roles(d.get("changes", []), by=UI_USER); VERSION["n"] += 1
                return self._send(200, json.dumps(roles_merged(), ensure_ascii=False))
            except (ValueError, TypeError) as e:
                return self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000: return self._send(413, '{"error":"quá lớn"}')
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
            t = ticket_write(u.path.rsplit("/", 1)[-1], d)
            load_tickets(); VERSION["n"] += 1
            return self._send(200, json.dumps(t, ensure_ascii=False, default=str))
        except (ValueError, KeyError, TypeError) as e:
            return self._send(400, json.dumps({"error": str(e).strip("'")}, ensure_ascii=False))
        except Exception as e:
            return self._send(500, json.dumps({"error": str(e)[:300]}, ensure_ascii=False))
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8")
        if u.path.startswith("/static/"):   # logo, favicon NextSky
            name = u.path[len("/static/"):]
            fp = os.path.join(HERE, "static", name)
            if re.fullmatch(r"[a-z0-9][a-z0-9._-]*\.(png|svg|ico)", name) and os.path.isfile(fp):
                ctype = {"png": "image/png", "svg": "image/svg+xml", "ico": "image/x-icon"}[name.rsplit(".", 1)[1]]
                return self._send(200, open(fp, "rb").read(), ctype)
            return self._send(404, '{"error":"not found"}')
        if u.path == "/api/project":   # trang thông tin (chuyển từ Efitco-thong-tin-du-an.xlsx), đọc lại mỗi lần để sửa file là thấy
            try: return self._send(200, open(os.path.join(HERE, "project.json"), "rb").read())
            except Exception as e: return self._send(500, json.dumps({"error": str(e)}))
        if u.path == "/api/roles":
            try: return self._send(200, json.dumps(roles_merged(), ensure_ascii=False))
            except Exception as e: return self._send(500, json.dumps({"error": str(e)[:300]}, ensure_ascii=False))
        if u.path == "/api/rubrics":
            return self._send(200, json.dumps(read_rubrics(), ensure_ascii=False))
        if u.path == "/api/raci":   # agent → loại việc được nhận (orchestrator/raci.yaml)
            out = {}
            for l in open(os.path.join(ROOT, "orchestrator", "raci.yaml"), encoding="utf-8"):
                m = re.match(r"^([a-z-]+):\s*\[(.*)\]", l)
                if m: out[m.group(1)] = [x.strip() for x in m.group(2).split(",") if x.strip()]
            return self._send(200, json.dumps(out))
        if u.path == "/api/ticket":
            try: return self._send(200, json.dumps(T.get((parse_qs(u.query).get("id") or [""])[0]), ensure_ascii=False, default=str))
            except Exception as e: return self._send(404, json.dumps({"error": str(e).strip("'")}, ensure_ascii=False))
        if u.path == "/api/snapshot":
            return self._send(200, json.dumps(snapshot(), ensure_ascii=False, default=str))
        if u.path == "/api/live":
            key = (parse_qs(u.query).get("key") or [""])[0]
            return self._send(200, json.dumps(live_events(key), ensure_ascii=False))
        if u.path == "/events":
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive"); self.end_headers()
            seen = -1
            try:
                while True:
                    if VERSION["n"] != seen:
                        seen = VERSION["n"]
                        self.wfile.write(f"data: {json.dumps(snapshot(), ensure_ascii=False, default=str)}\n\n".encode()); self.wfile.flush()
                    else:
                        self.wfile.write(b": ping\n\n"); self.wfile.flush()
                    time.sleep(2)
            except (BrokenPipeError, ConnectionResetError):
                return
        return self._send(404, '{"error":"not found"}')

if __name__ == "__main__":
    for f in (poll_tickets, poll_gh, ticker, backup_daily): threading.Thread(target=f, daemon=True).start()
    print(f"Dashboard Efitco: http://localhost:{PORT}  (Ctrl+C để dừng)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
