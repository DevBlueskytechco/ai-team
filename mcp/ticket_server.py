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

# Ticket MCP: ticket nội bộ (SQLite ai-team/data/tickets.db, mcp/ticket_local.py). Không còn backend ngoài.
BACKEND = "local"
from ticket_local import get, list, create, set_label, comment, all, set_review, set_task_type, set_status, is_done, update  # noqa
TOOLS = [
 {"name":"get","description":"Đọc một ticket đầy đủ","inputSchema":{"type":"object","properties":{"id":{"type":"string"}},"required":["id"]}},
 {"name":"list","description":"Liệt kê ticket theo label/agent/status/type/sprint","inputSchema":{"type":"object","properties":{"label":{"type":"string"},"agent":{"type":"string"},"status":{"type":"string"},"type":{"type":"string"},"sprint":{"type":"integer"}}}},
 {"name":"create","description":"Tạo ticket (task, bug, question, feature, story). Ticket con: parent=<id>","inputSchema":{"type":"object","properties":{"title":{"type":"string"},"task_type":{"type":"string"},"type":{"type":"string"},"agent":{"type":"string"},"side":{"type":"string"},"points":{"type":"integer"},"body":{"type":"string"},"parent":{"type":"string"},"blocked_by":{"type":"array","items":{"type":"string"}},"labels":{"type":"array","items":{"type":"string"}},"r_codes":{"type":"array","items":{"type":"string"}}},"required":["title"]}},
 {"name":"set_label","description":"Đổi nhãn ai-* (ai-draft→ai-review…), kèm link đầu ra và ghi chú","inputSchema":{"type":"object","properties":{"id":{"type":"string"},"label":{"type":"string"},"remove":{"type":"string"},"link":{"type":"string"},"note":{"type":"string"}},"required":["id","label"]}},
 {"name":"comment","description":"Thêm comment vào ticket","inputSchema":{"type":"object","properties":{"id":{"type":"string"},"text":{"type":"string"}},"required":["id","text"]}},
]
if __name__ == "__main__": serve("ticket", TOOLS, {"get":get,"list":list,"create":create,"set_label":set_label,"comment":comment})
