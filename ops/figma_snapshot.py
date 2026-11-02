#!/usr/bin/env python3
"""Làm mới snapshot Figma (1 request Tier 1). CTO chạy khi Designer sửa Figma:
   source ops/env.sh && FIGMA_ALLOW_API=1 python3 ops/figma_snapshot.py [node_id=1:359]
Ghi ../theme-efitco/docs/figma/snapshot-<node>.json rồi tạo PR qua /apply-patch hoặc commit tay."""
import os, sys, json, datetime, urllib.request
key = os.environ["FIGMA_FILE_KEY"]; node = sys.argv[1] if len(sys.argv) > 1 else "1:359"
if os.environ.get("FIGMA_ALLOW_API") != "1": sys.exit("Đặt FIGMA_ALLOW_API=1 để xác nhận dùng 1 request Tier 1 (hạn mức ~20/tháng)")
req = urllib.request.Request(f"https://api.figma.com/v1/files/{key}/nodes?ids={node}", headers={"X-Figma-Token": os.environ["FIGMA_TOKEN"]})
d = json.load(urllib.request.urlopen(req, timeout=120)); n = d["nodes"][node]
out = {"file_key": key, "name": d.get("name"), "lastModified": d.get("lastModified"), "version": d.get("version"),
       "snapshot_at": datetime.date.today().isoformat(), "root": node, "document": n["document"],
       "components": n.get("components", {}), "styles": n.get("styles", {})}
p = os.path.join(os.environ["THEME"], "docs", "figma", f"snapshot-{node.replace(':','-')}.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("đã ghi", p, "lastModified", d.get("lastModified"))
