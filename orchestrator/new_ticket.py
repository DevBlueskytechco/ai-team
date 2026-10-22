#!/usr/bin/env python3
"""Tạo ticket ai-draft nhanh từ sprint planning. Dùng: new_ticket.py <agent> <task_type> "<title>" [--parent TE-3] [--side fe] [--points 5] [--body "..."]"""
import sys, os, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp")); import ticket_server as T
ap = argparse.ArgumentParser(); ap.add_argument("agent"); ap.add_argument("task_type"); ap.add_argument("title")
ap.add_argument("--parent"); ap.add_argument("--side"); ap.add_argument("--points", type=int); ap.add_argument("--body", default="")
a = ap.parse_args()
t = T.create(a.title, type="task", agent=a.agent, side=a.side, points=a.points, body=a.body, parent=a.parent, labels=["ai-draft"])
d = T._load()
for x in d["tickets"]:
    if x["id"] == t["id"]: x["task_type"] = a.task_type
T._save(d); print(t["id"])
