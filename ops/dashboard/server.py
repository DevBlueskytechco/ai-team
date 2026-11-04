#!/usr/bin/env python3
"""Dashboard theo dõi agent Efitco — chạy local, chỉ nghe 127.0.0.1.
   cd ai-team && source ops/env.sh && python3 ops/dashboard/server.py   → http://localhost:8787
Nguồn dữ liệu (không lộ bí mật ra trình duyệt):
  - evals/raw/_live.json, evals/raw/live/<key>.jsonl   agent đang chạy (Orchestrator ghi, cập nhật mỗi lượt)   — đọc mỗi 2s
  - evals/raw/_runs.jsonl                               lịch sử lượt chạy, chi phí                               — mỗi 2s
  - Ticket nội bộ (mcp/ticket_local, data/tickets.db)  đọc lại khi dữ liệu đổi (kiểm dấu mỗi 2s)
  - Ghi ticket từ giao diện (menu Ticket): POST /api/ticket/* — chỉ từ localhost, cần header X-Efitco
  - gh CLI (tài khoản CTO)                              PR mở + CI, CI develop                                   — mỗi 60s
  - Kiểm môi trường (biến .env có/không, claude, shopify CLI, gh, theme sạch)  trang Việc chờ tôi           — mỗi 10 phút
  - Yêu cầu dự án: ai-team/requirements (CTO nạp, POST /api/req/*), đề xuất từ drafts/<agent>/<key>/impact.md của ticket phân tích
  - Kiến thức agent: ai-team/knowledge (CTO nạp, ghi qua POST /api/knowledge/*) + theme-efitco/.claude (định nghĩa, skill, quy tắc, agent-memory) — đọc khi mở trang
  - Tổng quan dự án: tài liệu PO/BA/Tech Lead/QA của theme-efitco (docs/, tests/e2e, drafts/techlead) đọc bằng git ở origin/develop — cache theo sha
Đẩy dữ liệu xuống trình duyệt bằng Server-Sent Events (/events) khi có thay đổi."""
import os, sys, json, time, threading, subprocess, hashlib, datetime, html, re, shutil
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
THEME = os.path.abspath(os.path.join(ROOT, "..", "theme-efitco"))
RAW = os.path.join(ROOT, "evals", "raw")
REPO = os.environ.get("REPO_THEME", "DevBlueskytechco/theme-efitco")
PORT = int(os.environ.get("DASHBOARD_PORT", "8787"))
sys.path.insert(0, os.path.join(ROOT, "mcp"))
sys.path.insert(0, os.path.join(ROOT, "orchestrator")); import knowledge as KN   # kiến thức agent (ai-team/knowledge + theme .claude)
import requirements as RQ   # yêu cầu dự án (ai-team/requirements)
import overview as OV       # tổng quan dự án (ops/dashboard/overview.py)
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
GH_WAKE = threading.Event()   # ticker đánh thức khi lượt agent/Orchestrator vừa kết thúc
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
            merged = json.loads(sh("gh", "pr", "list", "-R", REPO, "--state", "merged", "-L", "200", "--json",
                                   "number,title,headRefName,createdAt,mergedAt,url") or "[]")
            merged = [{"number": p["number"], "title": p["title"], "branch": p["headRefName"], "createdAt": p["createdAt"],
                       "mergedAt": p["mergedAt"], "url": p["url"]} for p in sorted(merged, key=lambda p: p.get("mergedAt") or "", reverse=True)]
            with LOCK: STATE["prs"] = out; STATE["merged"] = merged; STATE["ci_develop"] = runs; STATE["gh_at"] = now(); STATE["errors"].pop("gh", None)
        except Exception as e:
            with LOCK: STATE["errors"]["gh"] = str(e)[:200]
        GH_WAKE.wait(20 if busy else 60); GH_WAKE.clear()   # CI đang chạy thì 20s; lượt vừa xong thì lấy ngay

# ---------- nguồn nhanh (file local) ----------
def read_runs():
    """Lượt chạy = bản ghi Orchestrator (luôn có started_at). Bỏ dòng do hook Stop của theme (.claude/hooks/log-cost.sh) ghi
    cùng file — chỉ có ts/session, không phải một lượt — và dòng agent claude-code_* (Claude Code tự đặt AI_AGENT)."""
    p = os.path.join(RAW, "_runs.jsonl"); out = []
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            try: r = json.loads(l)
            except Exception: continue
            if not r.get("started_at") or not r.get("agent") or str(r.get("agent")).startswith("claude-code"): continue
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
                last = f"{c.get('name')} " + short(i.get("command") or i.get("file_path") or i.get("pattern") or "")[:140]
            elif c.get("type") == "text" and c.get("text", "").strip():
                last = c["text"].strip().replace("\n", " ")[:160]
    return len(turns), tools, last

LIVE_SRC = {}   # ticket → file sự kiện đang dùng cho /api/live
HOME = os.path.expanduser("~")
def short(s):
    """/Users/x/.../theme-efitco/blocks/a.liquid → blocks/a.liquid; ai-team → ai-team/…; home → ~."""
    s = str(s or "")
    for a, b in ((THEME + os.sep, ""), (ROOT + os.sep, "ai-team/"), (HOME + os.sep, "~/")): s = s.replace(a, b)
    return s

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
                    ev.append({"kind": "tool", "name": c.get("name"), "text": short(i.get("command") or i.get("file_path") or i.get("pattern") or i.get("description") or "")[:200]})
                elif c.get("type") == "text" and c.get("text", "").strip():
                    ev.append({"kind": "say", "text": short(c["text"].strip())[:400]})
        elif t == "user":
            for c in (e.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                    txt = c.get("content"); txt = txt if isinstance(txt, str) else json.dumps(txt)[:200]
                    ev.append({"kind": "error", "text": short(txt)[:200]})
        elif t == "result":
            ev.append({"kind": "done", "text": f"{'lỗi' if e.get('is_error') else 'xong'} · {e.get('num_turns')} turn · {round((e.get('duration_ms') or 0) / 60000, 1)} phút"})
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

def req_meta():
    return {"sources": RQ.SOURCES, "statuses": RQ.STATUSES, "prios": RQ.PRIOS, "analysts": RQ.ANALYSTS, "default_analyst": RQ.DEFAULT_ANALYST,
            "limit": RQ.LIMIT, "body_max": RQ.BODY_MAX}

def req_detail(id):
    r = RQ.get(id)
    kn = [x for a in KN.AGENTS + [KN.SHARED] for x in KN.items(a) if id in (x.get("source") or "")]
    return {"req": r, "proposals": RQ.proposals(r), "knowledge": kn, **req_meta(),
            "prompt_agents": ([a for a in KN.AGENTS if not r["agents"] or a in r["agents"]] if r["status"] == "ap-dung" else [])}

def req_write(act, d):
    """Nạp / sửa / đổi trạng thái / giao phân tích / lưu trữ yêu cầu dự án — chỉ CTO trên localhost."""
    if act == "save": return req_detail(RQ.save(d, UI_USER))
    if act == "status": return req_detail(RQ.set_status(str(d.get("id") or ""), str(d.get("status") or ""), UI_USER, str(d.get("note") or "")[:200]))
    if act == "archive": RQ.archive(str(d.get("id") or "")); return {"ok": True}
    if act == "ticket":   # tạo ticket thực hiện từ yêu cầu, gắn nhãn REQ-xxxx
        import ticket_local as L
        r = RQ.get(str(d.get("id") or "")); f = RQ.impl_ticket(r, d)
        t = L.create(f["title"], type="task", agent=f["agent"], side=f["side"], points=f["points"], body=f["body"], parent=f["parent"],
                     labels=f["labels"], priority=f["priority"], due_date=f["due_date"], sprint=f["sprint"], by=UI_USER)
        RQ.note(r["id"], f"tạo ticket thực hiện {t['key']}", UI_USER); load_tickets(); VERSION["n"] += 1
        return req_detail(r["id"]) | {"created": t["key"]}
    if act == "analyze":
        import ticket_local as L
        r = RQ.get(str(d.get("id") or "")); agent = str(d.get("agent") or RQ.DEFAULT_ANALYST.get(r["source"], "po"))
        title, body = RQ.analysis_ticket(r, agent)
        t = L.create(title, type="task", agent=agent, task_type=RQ.ANALYSTS[agent], body=body, parent=(r["stories"][0] if r["stories"] else None),
                     labels=["ai-draft"], priority={"cao": "high", "vua": "medium", "thap": "low"}[r["priority"]], due_date=r["due"] or None, by=UI_USER)
        RQ.add_ticket(r["id"], t["key"], UI_USER, agent); load_tickets(); VERSION["n"] += 1
        return req_detail(r["id"])
    raise ValueError("thao tác không hỗ trợ")

def knowledge_detail(agent):
    txt, used, skipped = KN.prompt_for(agent)
    rq, rq_used, rq_skip = RQ.prompt_for(agent) if agent != KN.SHARED else ("", [], [])
    return {"agent": agent, "items": KN.items(agent), "shared": KN.items(KN.SHARED) if agent != KN.SHARED else [], "current": KN.current(agent),
            "prompt": {"text": txt, "chars": len(txt), "used": [f"{x['agent']}/{x['id']}" for x in used], "skipped": [f"{x['agent']}/{x['id']}" for x in skipped]},
            "archived": KN.archived_count(agent), "limit": KN.LIMIT, "kinds": KN.KINDS, "body_max": KN.BODY_MAX,
            "req_prompt": {"text": rq, "chars": len(rq), "used": [{"id": r["id"], "title": r["title"]} for r in rq_used], "skipped": [r["id"] for r in rq_skip], "limit": RQ.LIMIT}}

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

# ---------- kiểm môi trường cho trang "Việc chờ tôi" (chỉ đọc; không in giá trị bí mật, chỉ có/không) ----------
SETUP = {"items": [], "at": None}
SETUP_LOCK = threading.Lock()
def setup_checks():
    out = []
    def add(ok, text, fix="", level="warn"): out.append({"ok": bool(ok), "text": text, "fix": fix, "level": level})
    for v in ("AGENT_GH_TOKEN", "SHOPIFY_CLI_THEME_TOKEN", "STORE_PASSWORD", "FIGMA_TOKEN"):
        add(bool(os.environ.get(v)), f"{v} {'có' if os.environ.get(v) else 'chưa có'} trong môi trường",
            "Thêm vào ai-team/.env rồi mở lại dashboard bằng ops/dashboard.sh (nạp ops/env.sh)", "bad")
    add(bool(shutil.which("claude")), "Claude Code CLI " + ("có" if shutil.which("claude") else "chưa cài"), "Cài Claude Code để Orchestrator chạy agent", "bad")
    try:
        ver = (re.search(r"\d+\.\d+\.\d+", sh("shopify", "version", timeout=30)) or [None])[0]
        major = (ver or "0").split(".")[0]
        if major != "4": add(False, f"Shopify CLI {ver or '?'} — cần 4.x như CI", "npm i -g @shopify/cli@4.9.5", "bad")
        else: add(ver == "4.9.5", f"Shopify CLI {ver}" + ("" if ver == "4.9.5" else " — CI ghim 4.9.5"), "npm i -g @shopify/cli@4.9.5")
    except Exception as e:
        add(False, "Không chạy được shopify version", "Cài Shopify CLI 4.9.5: npm i -g @shopify/cli@4.9.5", "bad")
    try:
        me = sh("gh", "api", "user", "--jq", ".login", timeout=20).strip()
        add(me != "nextsky-ai-agent", f"gh đăng nhập: {me}" + (" — phải là tài khoản CTO" if me == "nextsky-ai-agent" else ""), "unset GH_TOKEN; gh auth login bằng tài khoản CTO", "bad")
    except Exception:
        add(False, "gh chưa đăng nhập", "gh auth login (tài khoản CTO)", "bad")
    if read_live() is None:   # agent đang chạy thì theme đang ở nhánh feature và có thay đổi — bình thường
        try:
            dirty = [l for l in sh("git", "-C", THEME, "status", "--porcelain", "--untracked-files=normal", timeout=15).splitlines() if l.strip()]
            add(not dirty, "theme-efitco sạch" if not dirty else f"theme-efitco có {len(dirty)} file thay đổi chưa commit — Orchestrator sẽ bỏ qua ticket",
                "git -C ../theme-efitco status rồi commit/stash; hoặc chạy ops/preflight.sh", "bad")
        except Exception:
            add(False, "Không đọc được git theme-efitco", "Kiểm tra thư mục ../theme-efitco", "bad")
    try:
        import ticket_local as L
        b = os.path.join(os.path.dirname(L.DB), "backup")
        last = max((f for f in os.listdir(b) if f.startswith("tickets-")), default="") if os.path.isdir(b) else ""
        add(bool(last), f"Sao lưu ticket gần nhất: {last[8:18] or 'chưa có'}", "python3 ops/ticket.py backup")
    except Exception:
        pass
    with SETUP_LOCK: SETUP["items"] = out; SETUP["at"] = now()
    VERSION["n"] += 1
    return out

def poll_setup():
    while True:
        try: setup_checks()
        except Exception as e:
            with LOCK: STATE["errors"]["setup"] = str(e)[:200]
        time.sleep(600)

def snapshot():
    runs = read_runs()
    with LOCK:
        s = {k: STATE[k] for k in ("tickets", "prs", "merged", "ci_develop", "tickets_at", "gh_at", "backend")} | {"errors": dict(STATE["errors"])}
    with SETUP_LOCK: setup = {"items": list(SETUP["items"]), "at": SETUP["at"]}
    s.update({"live": read_live(), "runs": runs[-500:], "server_time": now(), "evals_n": evals_count(), "required_checks": required_checks(),
              "setup": setup, "review_overdue_days": (CFG or {}).get("review_overdue_days", 2)})
    return s

def ticker():
    prev = None
    while True:
        s = snapshot(); s.pop("server_time")
        lv = s.get("live") or {}; cur = (lv.get("ticket"), lv.get("phase")) if lv.get("alive") else None
        if prev and cur != prev: GH_WAKE.set()   # agent xong / Orchestrator vừa đẩy code, mở PR → cập nhật PR + CI ngay
        prev = cur
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
        if u.path not in ("/api/roles/update", "/api/setup/recheck") and not u.path.startswith(("/api/ticket/", "/api/knowledge/", "/api/req/")): return self._send(404, '{"error":"not found"}')
        if not self._local_ok(): return self._send(403, json.dumps({"error": "chỉ nhận từ dashboard trên localhost"}))
        if u.path.startswith("/api/req/"):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 200_000: return self._send(413, '{"error":"quá lớn"}')
                d = json.loads(self.rfile.read(n) or b"{}")
                return self._send(200, json.dumps(req_write(u.path.rsplit("/", 1)[-1], d), ensure_ascii=False, default=str))
            except (ValueError, TypeError, KeyError) as e:
                return self._send(400, json.dumps({"error": str(e).strip("'")}, ensure_ascii=False))
        if u.path.startswith("/api/knowledge/"):   # nạp / sửa / tắt / lưu trữ kiến thức agent — chỉ CTO trên localhost
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 120_000: return self._send(413, '{"error":"quá lớn"}')
                d = json.loads(self.rfile.read(n) or b"{}"); act = u.path.rsplit("/", 1)[-1]; ag = str(d.get("agent") or "")
                if act == "save":
                    kid = KN.save(ag, d.get("title"), d.get("body"), d.get("kind") or "kinh-nghiem", d.get("priority") or "thuong",
                                  d.get("status") or "active", d.get("source") or "", UI_USER, d.get("id") or None)
                elif act == "status": kid = KN.set_status(ag, str(d.get("id") or ""), "off" if d.get("status") == "off" else "active", UI_USER)
                elif act == "archive": kid = KN.archive(ag, str(d.get("id") or ""))
                else: return self._send(404, '{"error":"not found"}')
                return self._send(200, json.dumps({"ok": True, "id": kid, "detail": knowledge_detail(ag)}, ensure_ascii=False))
            except (ValueError, TypeError) as e:
                return self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))
        if u.path == "/api/setup/recheck":
            return self._send(200, json.dumps({"items": setup_checks(), "at": SETUP["at"]}, ensure_ascii=False))
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
    def _send(self, code, body, ctype="application/json; charset=utf-8", cache="no-store"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", cache)
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
                return self._send(200, open(fp, "rb").read(), ctype, cache="public, max-age=3600")
            return self._send(404, '{"error":"not found"}')
        if u.path == "/api/project":   # trang thông tin (chuyển từ Efitco-thong-tin-du-an.xlsx), đọc lại mỗi lần để sửa file là thấy
            try: return self._send(200, open(os.path.join(HERE, "project.json"), "rb").read())
            except Exception as e: return self._send(500, json.dumps({"error": str(e)}))
        if u.path == "/api/roles":
            try: return self._send(200, json.dumps(roles_merged(), ensure_ascii=False))
            except Exception as e: return self._send(500, json.dumps({"error": str(e)[:300]}, ensure_ascii=False))
        if u.path == "/api/req":   # ?id=REQ-0001 → chi tiết (kèm đề xuất từ impact.md); không có → danh sách
            rid = (parse_qs(u.query).get("id") or [""])[0]
            try: return self._send(200, json.dumps(req_detail(rid) if rid else {"items": RQ.items(), **req_meta()}, ensure_ascii=False))
            except ValueError as e: return self._send(404, json.dumps({"error": str(e)}, ensure_ascii=False))
        if u.path == "/api/overview":   # Tổng quan dự án: charter, PRD, SRS, kiến trúc, ADR, checklist, E2E của theme-efitco nhánh develop
            try: return self._send(200, json.dumps(OV.build(THEME, REPO), ensure_ascii=False))
            except Exception as e: return self._send(500, json.dumps({"error": str(e)[:300]}, ensure_ascii=False))
        if u.path == "/api/knowledge":   # ?agent=dev-fe → chi tiết; không có → số liệu mọi agent
            ag = (parse_qs(u.query).get("agent") or [""])[0]
            try: return self._send(200, json.dumps(knowledge_detail(ag) if ag else KN.summary(), ensure_ascii=False))
            except ValueError as e: return self._send(404, json.dumps({"error": str(e)}, ensure_ascii=False))
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
    for f in (poll_tickets, poll_gh, ticker, backup_daily, poll_setup): threading.Thread(target=f, daemon=True).start()
    print(f"Dashboard Efitco: http://localhost:{PORT}  (Ctrl+C để dừng)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
