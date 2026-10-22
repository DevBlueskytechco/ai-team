import sys, json
def serve(name, tools, handlers):
    def send(o): sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
    for line in sys.stdin:
        try: req = json.loads(line)
        except Exception: continue
        m, i, p = req.get("method"), req.get("id"), req.get("params") or {}
        if m == "initialize":
            send({"jsonrpc":"2.0","id":i,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{"name":name,"version":"0.1"}}})
        elif m == "notifications/initialized": pass
        elif m == "tools/list":
            send({"jsonrpc":"2.0","id":i,"result":{"tools":tools}})
        elif m == "tools/call":
            n, a = p.get("name"), p.get("arguments") or {}
            try: out = handlers[n](**a); res = {"content":[{"type":"text","text": out if isinstance(out,str) else json.dumps(out, ensure_ascii=False)}]}
            except Exception as e: res = {"content":[{"type":"text","text":f"error: {e}"}],"isError":True}
            send({"jsonrpc":"2.0","id":i,"result":res})
        elif i is not None:
            send({"jsonrpc":"2.0","id":i,"error":{"code":-32601,"message":"not found"}})

# Ticket MCP. Backend "file": tickets.json cạnh repo ai-team. Đổi sang Zoho/Linear: viết adapter cùng 5 hàm.
import os, datetime
BACKEND = os.environ.get("TICKET_BACKEND", "file")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tickets.json")
def _load():
    if not os.path.exists(DB): return {"tickets": []}
    return json.load(open(DB, encoding="utf-8"))
def _save(d): json.dump(d, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
def get(id):
    for t in _load()["tickets"]:
        if t["id"] == id: return t
    raise KeyError(id)
def list(label=None, agent=None, status=None, type=None, sprint=None):
    out = [t for t in _load()["tickets"] if (not label or label in t.get("labels", [])) and (not agent or t.get("agent") == agent)
           and (not status or t.get("status") == status) and (not type or t.get("type") == type) and (not sprint or t.get("sprint") == sprint)]
    return [{k: t.get(k) for k in ("id","title","type","agent","side","status","labels","points","sprint")} for t in out]
def create(title, type="task", agent=None, side=None, points=None, body="", parent=None, blocked_by=None, labels=None, r_codes=None):
    d = _load(); n = len(d["tickets"]) + 1; pid = (parent or "TE")
    tid = f"{pid}-{type[:1].upper()}{n}" if parent else f"TE-{n}"
    t = {"id": tid, "title": title, "type": type, "agent": agent, "side": side, "points": points, "body": body, "parent": parent,
         "blocked_by": blocked_by or [], "labels": labels or [], "r_codes": r_codes or [], "status": "Backlog",
         "comments": [], "created_at": datetime.date.today().isoformat()}
    d["tickets"].append(t); _save(d); return t
def set_label(id, label, remove=None, link=None, note=None):
    d = _load()
    for t in d["tickets"]:
        if t["id"] == id:
            labels = [l for l in t.get("labels", []) if l != remove and not (label.startswith("ai-") and l.startswith("ai-"))]
            labels.append(label); t["labels"] = labels
            if link: t["output_link"] = link
            if note: t["comments"].append({"by": os.environ.get("AI_AGENT", "agent"), "at": datetime.datetime.now().isoformat(timespec="minutes"), "text": note})
            _save(d); return t
    raise KeyError(id)
def comment(id, text):
    return set_label(id, next(l for l in get(id).get("labels", ["ai-draft"]) if True), note=text)
TOOLS = [
 {"name":"get","description":"Đọc một ticket đầy đủ","inputSchema":{"type":"object","properties":{"id":{"type":"string"}},"required":["id"]}},
 {"name":"list","description":"Liệt kê ticket theo label/agent/status/type/sprint","inputSchema":{"type":"object","properties":{"label":{"type":"string"},"agent":{"type":"string"},"status":{"type":"string"},"type":{"type":"string"},"sprint":{"type":"integer"}}}},
 {"name":"create","description":"Tạo ticket (task, bug, question, feature, story). Ticket con: parent=<id>","inputSchema":{"type":"object","properties":{"title":{"type":"string"},"type":{"type":"string"},"agent":{"type":"string"},"side":{"type":"string"},"points":{"type":"integer"},"body":{"type":"string"},"parent":{"type":"string"},"blocked_by":{"type":"array","items":{"type":"string"}},"labels":{"type":"array","items":{"type":"string"}},"r_codes":{"type":"array","items":{"type":"string"}}},"required":["title"]}},
 {"name":"set_label","description":"Đổi nhãn ai-* (ai-draft→ai-review…), kèm link đầu ra và ghi chú","inputSchema":{"type":"object","properties":{"id":{"type":"string"},"label":{"type":"string"},"remove":{"type":"string"},"link":{"type":"string"},"note":{"type":"string"}},"required":["id","label"]}},
 {"name":"comment","description":"Thêm comment vào ticket","inputSchema":{"type":"object","properties":{"id":{"type":"string"},"text":{"type":"string"}},"required":["id","text"]}},
]
if __name__ == "__main__": serve("ticket", TOOLS, {"get":get,"list":list,"create":create,"set_label":set_label,"comment":comment})
