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

# store-dev MCP: chụp preview (Playwright), đọc theme check/lighthouse report. Chỉ store trong SHOPIFY_FLAG_STORE.
import os, subprocess, glob
def screenshot(url, width=1280, out="drafts/_shots/shot.png", full_page=True):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    js = f"""const {{chromium}}=require('playwright');(async()=>{{const b=await chromium.launch();const p=await b.newPage({{viewport:{{width:{int(width)},height:900}}}});await p.goto({json.dumps(url)},{{waitUntil:'networkidle'}});await p.screenshot({{path:{json.dumps(out)},fullPage:{str(bool(full_page)).lower()}}});await b.close();}})();"""
    r = subprocess.run(["node","-e",js], capture_output=True, text=True, timeout=120)
    return out if r.returncode == 0 else f"error: {r.stderr[-500:]}"
def theme_check(path="."):
    r = subprocess.run(["shopify","theme","check","--output","json","--path",path], capture_output=True, text=True, timeout=300)
    return r.stdout or r.stderr
def lighthouse_report(dir=".lighthouseci"):
    files = sorted(glob.glob(os.path.join(dir, "lhr-*.json")))[-6:]
    out = []
    for f in files:
        d = json.load(open(f)); c = d["categories"]
        out.append({"url": d["finalUrl"], "perf": c["performance"]["score"], "a11y": c["accessibility"]["score"], "formFactor": d["configSettings"]["formFactor"]})
    return out
TOOLS = [
 {"name":"screenshot","description":"Chụp URL preview ở width (360/768/1280) ra file png","inputSchema":{"type":"object","properties":{"url":{"type":"string"},"width":{"type":"integer"},"out":{"type":"string"},"full_page":{"type":"boolean"}},"required":["url"]}},
 {"name":"theme_check","description":"Chạy shopify theme check, trả JSON","inputSchema":{"type":"object","properties":{"path":{"type":"string"}}}},
 {"name":"lighthouse_report","description":"Đọc điểm perf/a11y từ .lighthouseci","inputSchema":{"type":"object","properties":{"dir":{"type":"string"}}}},
]
if __name__ == "__main__": serve("store-dev", TOOLS, {"screenshot":screenshot,"theme_check":theme_check,"lighthouse_report":lighthouse_report})
