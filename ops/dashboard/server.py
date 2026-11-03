#!/usr/bin/env python3
"""Dashboard theo dõi agent Efitco — chạy local, chỉ nghe 127.0.0.1.
   cd ai-team && source ops/env.sh && python3 ops/dashboard/server.py   → http://localhost:8787
Nguồn dữ liệu (không lộ bí mật ra trình duyệt):
  - evals/raw/_live.json, evals/raw/live/<key>.jsonl   agent đang chạy (Orchestrator ghi, cập nhật mỗi lượt)   — đọc mỗi 2s
  - evals/raw/_runs.jsonl                               lịch sử lượt chạy, chi phí                               — mỗi 2s
  - Zoho (mcp/ticket_server)                            ticket, nhãn, chấm điểm                                  — mỗi 60s
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

STATE = {"tickets": [], "prs": [], "ci_develop": [], "zoho_at": None, "gh_at": None, "errors": {}}
LOCK = threading.Lock()
VERSION = {"n": 0, "hash": ""}

def sh(*a, timeout=60):
    """Chạy lệnh, lỗi thì raise để dashboard báo (vd gh chưa đăng nhập)."""
    r = subprocess.run(a, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError(f"{' '.join(a[:3])}: {(r.stderr or r.stdout).strip()[:160]}")
    return r.stdout

# ---------- nguồn chậm ----------
def poll_zoho():
    while True:
        try:
            import ticket_server as T
            rows = []
            for t in T.all():
                rows.append({k: t.get(k) for k in ("key", "status", "agent", "task_type", "side", "points", "labels", "parent", "blocked_by", "id")} |
                            {"title": html.unescape(t.get("title") or ""), "review": {k: (t.get("review") or {}).get(k) for k in ("severity", "scores", "by", "at")}})
            with LOCK: STATE["tickets"] = rows; STATE["zoho_at"] = now(); STATE["errors"].pop("zoho", None)
        except Exception as e:
            with LOCK: STATE["errors"]["zoho"] = str(e)[:200]
        time.sleep(60)

def poll_gh():
    while True:
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
            runs = json.loads(sh("gh", "run", "list", "-R", REPO, "-b", "develop", "-L", "5", "--json",
                                 "databaseId,status,conclusion,displayTitle,createdAt,url,workflowName") or "[]")
            with LOCK: STATE["prs"] = out; STATE["ci_develop"] = runs; STATE["gh_at"] = now(); STATE["errors"].pop("gh", None)
        except Exception as e:
            with LOCK: STATE["errors"]["gh"] = str(e)[:200]
        time.sleep(60)

# ---------- nguồn nhanh (file local) ----------
def read_runs():
    p = os.path.join(RAW, "_runs.jsonl"); out = []
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            try: r = json.loads(l)
            except Exception: continue
            out.append({k: r.get(k) for k in ("agent", "ticket", "started_at", "cost_usd", "num_turns", "is_error", "pr", "branch", "model")})
    return out

def read_live():
    p = os.path.join(RAW, "_live.json")
    if not os.path.exists(p): return None
    try:
        d = json.load(open(p, encoding="utf-8"))
        st = datetime.datetime.fromisoformat(d["started_at"]); d["elapsed_s"] = int((datetime.datetime.now() - st).total_seconds())
        # tiến trình còn sống?
        try: os.kill(int(d.get("pid") or 0), 0); d["alive"] = True
        except Exception: d["alive"] = False
        return d
    except Exception:
        return None

def live_events(key, limit=60):
    """Rút gọn stream-json của 1 ticket thành dòng sự kiện đọc được."""
    p = os.path.join(RAW, "live", f"{key}.jsonl")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key or "") or not os.path.exists(p): return []
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
            ev.append({"kind": "done", "text": f"xong · {e.get('num_turns')} lượt · {e.get('total_cost_usd')} USD · lỗi={e.get('is_error')}"})
    return ev[-limit:]

def now(): return datetime.datetime.now().isoformat(timespec="seconds")

def snapshot():
    runs = read_runs()
    month = datetime.date.today().strftime("%Y-%m")
    spent = sum(float(r["cost_usd"] or 0) for r in runs if (r.get("started_at") or "")[:7] == month)
    with LOCK:
        s = {k: STATE[k] for k in ("tickets", "prs", "ci_develop", "zoho_at", "gh_at")} | {"errors": dict(STATE["errors"])}
    s.update({"live": read_live(), "runs": runs[-200:], "budget": {"month": month, "spent": round(spent, 2),
              "limit": CFG.get("budget_usd_month", 2000), "warn_pct": CFG.get("budget_warn_pct", 80)}, "server_time": now()})
    return s

def ticker():
    while True:
        s = snapshot(); s.pop("server_time")
        h = hashlib.sha1(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()
        if h != VERSION["hash"]: VERSION["hash"] = h; VERSION["n"] += 1
        time.sleep(2)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8")
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
    for f in (poll_zoho, poll_gh, ticker): threading.Thread(target=f, daemon=True).start()
    print(f"Dashboard Efitco: http://localhost:{PORT}  (Ctrl+C để dừng)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
