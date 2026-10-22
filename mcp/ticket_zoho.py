"""Adapter Zoho Projects (API v3) cho ticket MCP. Cùng giao diện với backend file:
get, list, create, set_label, comment, set_review, set_task_type, all.

Thiết kế: metadata của agent (agent, task_type, side, points, parent, labels, output_link, review, r_codes)
lưu trong dòng đầu description của task dưới dạng `[ai] {json}`; phần còn lại của description là body.
Không cần custom field hay tag trong Zoho. Comment dùng API comments của task.

Cấu hình (ai-team/.env): TICKET_BACKEND=zoho, ZOHO_DC, ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN,
ZOHO_PORTAL_ID (số), ZOHO_PROJECT_ID. Scope: ZohoProjects.tasks.ALL,ZohoProjects.projects.READ,ZohoProjects.portals.READ.
Kiểm: python3 mcp/zoho_probe.py
"""
import os, re, json, time, html, urllib.request, urllib.parse, urllib.error

DC = os.environ.get("ZOHO_DC", "com")
ACCOUNTS = f"https://accounts.zoho.{DC}"
API = f"https://projectsapi.zoho.{DC}/api/v3"
PORTAL = os.environ.get("ZOHO_PORTAL_ID", ""); PROJECT = os.environ.get("ZOHO_PROJECT_ID", "")
_tok = {"v": None, "exp": 0}
META_RE = re.compile(r"\[ai\]\s*(\{.*?\})\s*(?:</p>|<br\s*/?>|\n|$)", re.S)

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
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read(); return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"zoho {method} {path}: {e.code} {e.read()[:500].decode(errors='ignore')}")

def _task_of(r): return r.get("task") or (r.get("tasks") or [r])[0] if isinstance(r, dict) else r

def _split(desc):
    desc = desc or ""
    m = META_RE.search(html.unescape(desc))
    meta = {}
    if m:
        try: meta = json.loads(m.group(1))
        except Exception: meta = {}
    body = META_RE.sub("", html.unescape(desc), count=1)
    body = re.sub(r"<br\s*/?>|</p>", "\n", body); body = re.sub(r"<[^>]+>", "", body)
    return meta, re.sub(r"\n{2,}", "\n", body).strip()

def _join(meta, body):
    return f"<p>[ai] {json.dumps(meta, ensure_ascii=False)}</p>" + (f"<p>{html.escape(body)}</p>" if body else "")

def _norm(z):
    meta, body = _split(z.get("description"))
    return {"id": str(z.get("id")), "key": z.get("prefix"), "title": z.get("name"), "type": meta.get("type", "task"),
            "agent": meta.get("agent"), "task_type": meta.get("task_type"), "side": meta.get("side"), "points": meta.get("points"),
            "parent": meta.get("parent"), "blocked_by": meta.get("blocked_by", []), "r_codes": meta.get("r_codes", []),
            "body": body, "labels": meta.get("labels", []), "status": (z.get("status") or {}).get("name"),
            "output_link": meta.get("output_link"), "review": meta.get("review", {}),
            "created_at": (z.get("created_time") or "")[:10], "comments": [], "_meta": meta}

def all():
    out, page = [], 1
    while True:
        r = _req("GET", "/tasks", params={"page": page, "per_page": 100})
        out += [_norm(t) for t in r.get("tasks", [])]
        if not (r.get("page_info") or {}).get("has_next_page"): return out
        page += 1

def get(id):
    t = _norm(_task_of(_req("GET", f"/tasks/{id}")))
    try:
        c = _req("GET", f"/tasks/{id}/comments")
        t["comments"] = [{"by": (x.get("added_by") or x.get("created_by") or {}).get("name", ""), "at": (x.get("created_time") or "")[:16],
                          "text": html.unescape(re.sub(r"<[^>]+>", "", x.get("comment") or x.get("content") or ""))} for x in c.get("comments", [])]
    except RuntimeError: pass
    return t

def list(label=None, agent=None, status=None, type=None, sprint=None):
    rows = [t for t in all() if (not label or label in t["labels"]) and (not agent or t["agent"] == agent)
            and (not status or t["status"] == status) and (not type or t["type"] == type)]
    return [{k: t.get(k) for k in ("id", "key", "title", "type", "agent", "side", "status", "labels", "points")} for t in rows]

def _patch_meta(id, **changes):
    z = _task_of(_req("GET", f"/tasks/{id}")); meta, body = _split(z.get("description"))
    meta.update({k: v for k, v in changes.items() if v is not None})
    _req("PATCH", f"/tasks/{id}", {"description": _join(meta, body)}); return meta

def create(title, type="task", agent=None, side=None, points=None, body="", parent=None, blocked_by=None, labels=None, r_codes=None, task_type=None):
    meta = {"type": type, "agent": agent, "task_type": task_type, "side": side, "points": points, "parent": parent,
            "blocked_by": blocked_by or [], "labels": labels or [], "r_codes": r_codes or [], "review": {}}
    r = _req("POST", "/tasks", {"name": title, "description": _join(meta, body)})
    return _norm(_task_of(r))

def set_label(id, label, remove=None, link=None, note=None):
    z = _task_of(_req("GET", f"/tasks/{id}")); meta, body = _split(z.get("description"))
    labels = [l for l in meta.get("labels", []) if l != remove and not (label.startswith("ai-") and l.startswith("ai-"))] + [label]
    meta["labels"] = labels
    if link: meta["output_link"] = link
    _req("PATCH", f"/tasks/{id}", {"description": _join(meta, body)})
    if note: comment(id, (f"[{os.environ['AI_AGENT']}] " if os.environ.get("AI_AGENT") else "") + note)
    return get(id)

def comment(id, text):
    _req("POST", f"/tasks/{id}/comments", {"comment": text}); return {"ok": True}

def set_review(id, review, label):
    z = _task_of(_req("GET", f"/tasks/{id}")); meta, body = _split(z.get("description"))
    meta["review"] = review; meta["labels"] = [l for l in meta.get("labels", []) if not l.startswith("ai-")] + [label]
    _req("PATCH", f"/tasks/{id}", {"description": _join(meta, body)}); return get(id)

def set_task_type(id, task_type):
    _patch_meta(id, task_type=task_type); return get(id)
