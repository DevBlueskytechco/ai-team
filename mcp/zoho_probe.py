#!/usr/bin/env python3
"""Dò kết nối Zoho Projects: in portal/project, 3 task đầu, và tên custom field thật để điền ZOHO_CF_* vào .env."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticket_server  # nạp .env
import ticket_zoho as Z
print("DC:", Z.DC, "portal:", Z.PORTAL, "project:", Z.PROJECT)
r = Z._req("GET", "/tasks", params={"page": 1, "per_page": 3})
tasks = r.get("tasks", [])
print("tasks trả về:", len(tasks))
for t in tasks:
    print("-", t.get("id"), t.get("name"), "| status:", (t.get("status") or {}).get("name"))
    print("  custom_fields:", json.dumps(t.get("custom_fields"), ensure_ascii=False)[:400])
print("\nMetadata agent nằm ở dòng [ai] {...} đầu description; không cần custom field.")
