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

# figma MCP: đọc file/node qua REST (FIGMA_TOKEN), xuất ảnh node; ghi chỉ vào page FIGMA_DRAFT_PAGE (Figma REST không cho tạo node → "ghi" = lưu comment).
import os, urllib.request
TOKEN = os.environ.get("FIGMA_TOKEN",""); KEY = os.environ.get("FIGMA_FILE_KEY","")
def _get(path):
    req = urllib.request.Request("https://api.figma.com/v1" + path, headers={"X-Figma-Token": TOKEN})
    return json.load(urllib.request.urlopen(req, timeout=60))
def get_node(node_id, depth=2): return _get(f"/files/{KEY}/nodes?ids={node_id}&depth={depth}")
def list_pages(): return [{"id":p["id"],"name":p["name"]} for p in _get(f"/files/{KEY}?depth=1")["document"]["children"]]
def export_image(node_id, scale=1, format="png"): return _get(f"/images/{KEY}?ids={node_id}&scale={scale}&format={format}")["images"]
def get_styles(): return _get(f"/files/{KEY}/styles")
def add_comment(message, node_id=None):
    data = json.dumps({"message": message, **({"client_meta": {"node_id": node_id, "node_offset": {"x":0,"y":0}}} if node_id else {})}).encode()
    req = urllib.request.Request(f"https://api.figma.com/v1/files/{KEY}/comments", data=data, method="POST", headers={"X-Figma-Token": TOKEN, "Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))
TOOLS = [
 {"name":"get_node","description":"Đọc node Figma (id dạng 1:359)","inputSchema":{"type":"object","properties":{"node_id":{"type":"string"},"depth":{"type":"integer"}},"required":["node_id"]}},
 {"name":"list_pages","description":"Liệt kê page của file","inputSchema":{"type":"object","properties":{}}},
 {"name":"export_image","description":"URL ảnh render của node","inputSchema":{"type":"object","properties":{"node_id":{"type":"string"},"scale":{"type":"number"},"format":{"type":"string"}},"required":["node_id"]}},
 {"name":"get_styles","description":"Styles (màu/chữ) của file","inputSchema":{"type":"object","properties":{}}},
 {"name":"add_comment","description":"Ghi comment (cách duy nhất ghi qua REST) — dùng cho đề xuất của Designer Agent","inputSchema":{"type":"object","properties":{"message":{"type":"string"},"node_id":{"type":"string"}},"required":["message"]}},
]
if __name__ == "__main__": serve("figma", TOOLS, {"get_node":get_node,"list_pages":list_pages,"export_image":export_image,"get_styles":get_styles,"add_comment":add_comment})
