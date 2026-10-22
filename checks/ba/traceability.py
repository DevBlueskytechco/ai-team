#!/usr/bin/env python3
"""Đọc docs/traceability.md (bảng FR | Story | TC | Mã R | Trạng thái); báo FR/story/TC mồ côi."""
import re, sys
rows = [l for l in open(sys.argv[1], encoding='utf-8') if l.startswith('| FR') or l.startswith('| NFR')]
orphans = [r.strip() for r in rows if re.search(r'\|\s*\|', r.split('|', 2)[2] if r.count('|')>2 else '')]
for o in orphans: print('orphan:', o)
print(f"rows: {len(rows)} orphans: {len(orphans)}"); sys.exit(0 if not orphans else 1)
