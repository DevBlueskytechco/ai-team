"""Adapter Zoho Projects (API v3) cho ticket MCP. Cùng giao diện với backend file:
get, list, create, set_label, comment, set_review, set_task_type, all.

Cấu hình (env hoặc ai-team/.env):
  ZOHO_DC=com|eu|in|com.au     ZOHO_CLIENT_ID  ZOHO_CLIENT_SECRET  ZOHO_REFRESH_TOKEN
  ZOHO_PORTAL_ID  ZOHO_PROJECT_ID
  Scope khi tạo refresh token: ZohoProjects.tasks.ALL,ZohoProjects.projects.READ,ZohoProjects.portals.READ
Custom field trên task (tạo trong Zoho Projects → Settings → Layouts → Task, kiểu Single line/Pick list), api_name map qua env:
  ZOHO_CF_AI_STATUS (pick list: ai-draft, ai-review, ai-dat, ai-sua, ai-loai)   mặc định cf_ai_status
  ZOHO_CF_AGENT, ZOHO_CF_TASK_TYPE, ZOHO_CF_SIDE, ZOHO_CF_POINTS, ZOHO_CF_PARENT, ZOHO_CF_OUTPUT_LINK, ZOHO_CF_REVIEW (multi-line JSON)
Nếu tên field thật khác, chạy `python3 mcp/zoho_probe.py` để in api_name và sửa env.
"""
import os, json, time, datetime, urllib.request, urllib.parse

DC = os.environ.get("ZOHO_DC", "com")
ACCOUNTS = f"https://accounts.zoho.{DC}"
API = f"https://projectsapi.zoho.{DC}/api/v3"
PORTAL = os.environ.get("ZOHO_PORTAL_ID", ""); PROJECT = os.environ.get("ZOHO_PROJECT_ID", "")
CF = {k: os.environ.get(f"ZOHO_CF_{k.upper()}", f"cf_{k}") for k in
      ["ai_status", "agent", "task_type", "side", "points", "parent", "output_link", "review"]}
_tok = {"v": None, "exp": 0}

def _token():
    if _tok["v"] and time.time() < _tok["exp"] - 60: return _tok["v"]
    data = urllib.parse.urlencode({"refresh_token": os.environ["ZOHO_REFRESH_TOKEN"], "client_id": os.environ["ZOHO_CLIENT_ID"],
                                   "client_secret": os.environ["ZOHO_CLIENT_SECRET"], "grant_type": "refresh_token"}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request(f"{ACCOUNTS}/oauth/v2/token", data=data, method="POST"), timeout=30))
    if "access_token" not in r: raise RuntimeError(f"zoho oauth: {r}")
    _tok["v"] = r["access_token"]; _tok["exp"] = time.time() + int(r.get("expires_in", 3600)); return _tok["v"]

def _req(method, path, body=None, params=None):
    url = f"{API}/portal/{PORTAL}/projects/{PROJECT}{path}" + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": f"Zoho-oauthtoken {_token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp: return json.load(resp) if resp.length != 0 else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"zoho {method} {path}: {e.code} {e.read()[:500].decode(errors='ignore')}")

def _norm(z):
    """Zoho task → dict giống backend file."""
    cf = z.get("custom_fields") or {}
    g = lambda k: (cf.get(CF[k]) if isinstance(cf, dict) else None) or z.get(CF[k])
    try: review = json.loads(g("review") or "{}")
    except Exception: review = {}
    return {"id": str(z.get("id") or z.get("id_string")), "zoho_key": z.get("key"), "title": z.get("name"), "type": "task",
            "agent": g("agent"), "task_type": g("task_type"), "side": g("side"), "points": g("points"), "parent": g("parent"),
            "body": (z.get("description") or ""), "labels": [g("ai_status")] if g("ai_status") else [],
            "status": (z.get("status") or {}).get("name"), "output_link": g("output_link"), "review": review,
            "created_at": (z.get("created_time") or "")[:10], "comments": [], "_raw": z}

def all():
    out, page = [], 1
    while True:
        r = _req("GET", "/tasks", params={"page": page, "per_page": 100})
        out += [_norm(t) for t in r.get("tasks", [])]
        if not (r.get("page_info") or {}).get("has_next_page"): return out
        page += 1

def get(id):
    r = _req("GET", f"/tasks/{id}")
    t = _norm(r.get("task") or (r.get("tasks") or [r])[0])
    try:
        c = _req("GET", f"/tasks/{id}/comments")
        t["comments"] = [{"by": (x.get("added_by") or {}).get("name", ""), "at": (x.get("created_time") or "")[:16], "text": x.get("content", "")} for x in c.get("comments", [])]
    except RuntimeError: pass
    return t

def list(label=None, agent=None, status=None, type=None, sprint=None):
    rows = [t for t in all() if (not label or label in t["labels"]) and (not agent or t["agent"] == agent) and (not status or t["status"] == status)]
    return [{k: t.get(k) for k in ("id", "title", "type", "agent", "side", "status", "labels", "points")} for t in rows]

def _cf(**kw): return {CF[k]: v for k, v in kw.items() if v is not None}

def create(title, type="task", agent=None, side=None, points=None, body="", parent=None, blocked_by=None, labels=None, r_codes=None, task_type=None):
    cfs = _cf(agent=agent, side=side, points=points, parent=parent, task_type=task_type, ai_status=(labels or [None])[0])
    r = _req("POST", "/tasks", {"name": title, "description": body or "", "custom_fields": cfs})
    return _norm(r.get("task") or (r.get("tasks") or [r])[0])

def set_label(id, label, remove=None, link=None, note=None):
    body = {"custom_fields": _cf(ai_status=label, output_link=link)}
    _req("PATCH", f"/tasks/{id}", body)
    if note: comment(id, note)
    return get(id)

def comment(id, text):
    _req("POST", f"/tasks/{id}/comments", {"content": text}); return {"ok": True}

def set_review(id, review: dict, label):
    _req("PATCH", f"/tasks/{id}", {"custom_fields": _cf(review=json.dumps(review, ensure_ascii=False), ai_status=label)}); return get(id)

def set_task_type(id, task_type):
    _req("PATCH", f"/tasks/{id}", {"custom_fields": _cf(task_type=task_type)}); return get(id)
