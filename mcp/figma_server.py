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

# figma MCP: đọc node từ SNAPSHOT trong repo theme (docs/figma/), không gọi API — plan Starter chỉ cho ~20 request Tier 1/tháng.
# API chỉ dùng khi FIGMA_ALLOW_API=1 (CTO làm mới snapshot) và cho comment (Tier 2, 5/phút) có retry theo Retry-After.
import os, time, urllib.request, urllib.error
TOKEN = os.environ.get("FIGMA_TOKEN",""); KEY = os.environ.get("FIGMA_FILE_KEY","")
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.environ.get("FIGMA_SNAPSHOT_DIR") or os.path.abspath(os.path.join(HERE, "..", "..", "theme-efitco", "docs", "figma"))
_snap = {}

def _load():
    if not _snap:
        for f in sorted(os.listdir(SNAP_DIR)) if os.path.isdir(SNAP_DIR) else []:
            if f.startswith("snapshot-") and f.endswith(".json"):
                d = json.load(open(os.path.join(SNAP_DIR, f), encoding="utf-8"))
                _snap[d["root"]] = d
    return _snap

def _find(n, i):
    if n.get("id") == i: return n
    for k in n.get("children", []):
        r = _find(k, i)
        if r: return r

def _trim(n, depth):
    n = dict(n)
    if depth <= 0: n.pop("children", None); return n
    if "children" in n: n["children"] = [_trim(c, depth - 1) for c in n["children"]]
    return n

def _api(path, method="GET", data=None):
    if method == "GET" and os.environ.get("FIGMA_ALLOW_API") != "1":
        raise RuntimeError("API Figma Tier 1 bị tắt (hạn mức ~20 request/tháng). Dùng snapshot docs/figma/; CTO làm mới bằng ops/figma_snapshot.py")
    for attempt in range(3):
        req = urllib.request.Request("https://api.figma.com/v1" + path, data=data, method=method,
                                     headers={"X-Figma-Token": TOKEN, "Content-Type": "application/json"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            wait = int(e.headers.get("Retry-After") or 60)
            info = f"429 plan={e.headers.get('X-Figma-Plan-Tier')} seat={e.headers.get('X-Figma-Rate-Limit-Type')} retry_after={wait}s"
            if wait > 120 or attempt == 2: raise RuntimeError(f"Figma rate limit: {info}. Dùng snapshot, đừng thử lại.")
            time.sleep(wait)

def get_node(node_id, depth=2):
    for root, d in _load().items():
        n = _find(d["document"], node_id)
        if n:
            return {"source": f"snapshot {d['snapshot_at']} (Figma lastModified {d.get('lastModified')})", "node": _trim(n, int(depth))}
    raise RuntimeError(f"node {node_id} không có trong snapshot {list(_load())}. Báo CTO export/làm mới snapshot, ghi KHÔNG CHẮC và tiếp tục.")

def list_pages():
    return [{"root": r, "name": d.get("name"), "snapshot_at": d.get("snapshot_at")} for r, d in _load().items()]

def export_image(node_id, scale=2, format="png"):
    base = node_id.replace(":", "-")
    for name in (f"{base}.png", f"{base}.lowres.png"):
        p = os.path.join(SNAP_DIR, "img", name)
        if os.path.exists(p): return {"path": p, "quality": "2x export tay" if not name.endswith("lowres.png") else "0,25x tham chiếu bố cục"}
    raise RuntimeError(f"chưa có ảnh {base}.png trong docs/figma/img/. Dùng get_node để đọc kích thước, ghi KHÔNG CHẮC phần hình ảnh.")

def get_styles():
    out = {}
    for r, d in _load().items(): out.update(d.get("styles", {}))
    return out

def add_comment(message, node_id=None):
    data = json.dumps({"message": message, **({"client_meta": {"node_id": node_id, "node_offset": {"x":0,"y":0}}} if node_id else {})}).encode()
    return _api(f"/files/{KEY}/comments", method="POST", data=data)

TOOLS = [
 {"name":"get_node","description":"Đọc node Figma (id dạng 1:359) từ snapshot trong repo; depth giới hạn độ sâu cây","inputSchema":{"type":"object","properties":{"node_id":{"type":"string"},"depth":{"type":"integer"}},"required":["node_id"]}},
 {"name":"list_pages","description":"Snapshot Figma đang có","inputSchema":{"type":"object","properties":{}}},
 {"name":"export_image","description":"Đường dẫn ảnh tham chiếu của node trong docs/figma/img/ (đọc bằng Read)","inputSchema":{"type":"object","properties":{"node_id":{"type":"string"},"scale":{"type":"number"},"format":{"type":"string"}},"required":["node_id"]}},
 {"name":"get_styles","description":"Styles (màu/chữ) trong snapshot","inputSchema":{"type":"object","properties":{}}},
 {"name":"add_comment","description":"Ghi comment lên Figma (Tier 2, ~5/phút) — chỉ Designer Agent dùng cho đề xuất","inputSchema":{"type":"object","properties":{"message":{"type":"string"},"node_id":{"type":"string"}},"required":["message"]}},
]
if __name__ == "__main__": serve("figma", TOOLS, {"get_node":get_node,"list_pages":list_pages,"export_image":export_image,"get_styles":get_styles,"add_comment":add_comment})
