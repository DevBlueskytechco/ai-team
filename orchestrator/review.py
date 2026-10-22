#!/usr/bin/env python3
"""Role owner chấm: review.py <ticket> <dat|sua_nhe|sua_nang|loai> --scores coverage=2,edge_cases=1 --by qa-owner [--fixed <ref>] [--reason "..."]"""
import sys, os, argparse, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp")); import ticket_server as T
ap = argparse.ArgumentParser(); ap.add_argument("ticket"); ap.add_argument("label", choices=["dat","sua_nhe","sua_nang","loai"])
ap.add_argument("--scores", required=True); ap.add_argument("--by", required=True); ap.add_argument("--fixed", default=""); ap.add_argument("--reason", default="")
a = ap.parse_args()
scores = {k: int(v) for k, v in (kv.split("=") for kv in a.scores.split(","))}
d = T._load()
for t in d["tickets"]:
    if t["id"] == a.ticket:
        t["labels"] = [l for l in t.get("labels", []) if not l.startswith("ai-")] + [{"dat":"ai-dat","sua_nhe":"ai-sua","sua_nang":"ai-sua","loai":"ai-loai"}[a.label]]
        t["review"] = {"scores": scores, "by": a.by, "fixed_ref": a.fixed, "reason": a.reason, "severity": a.label, "at": datetime.date.today().isoformat()}
T._save(d); print("ok", a.ticket, a.label, scores)
