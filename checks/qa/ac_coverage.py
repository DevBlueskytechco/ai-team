#!/usr/bin/env python3
"""So AC trong story với cột AC của test-cases.md. Dùng: ac_coverage.py <story.md|srs.md#TE-3> <test-cases.md>"""
import re, sys
src, tc = sys.argv[1], sys.argv[2]
path, _, anchor = src.partition('#')
text = open(path, encoding='utf-8').read()
if anchor:
    m = re.search(r'### ' + re.escape(anchor) + r'.*?(?=\n### |\Z)', text, re.S); text = m.group(0) if m else ''
acs = set(re.findall(r'\bAC(\d+)\b', text))
covered = set(re.findall(r'\|\s*AC(\d+)\s*\|', open(tc, encoding='utf-8').read()))
missing = sorted(acs - covered, key=int)
cov = (len(acs) - len(missing)) / len(acs) if acs else 0
print(f"AC: {len(acs)} covered: {len(acs)-len(missing)} coverage: {cov:.2f} missing: {['AC'+m for m in missing]}")
sys.exit(0 if cov == 1.0 and acs else 1)
