#!/usr/bin/env python3
import re, sys
VAGUE = ['nhanh','đẹp','dễ dùng','hợp lý','phù hợp','tối ưu','thân thiện','mượt','tốt hơn','chuyên nghiệp']
text = open(sys.argv[1], encoding='utf-8').read()
hits = [(w, m.start()) for w in VAGUE for m in re.finditer(r'\b' + re.escape(w) + r'\b', text, re.I)]
for w, pos in hits: print(f"{w} @ {text.count(chr(10), 0, pos)+1}")
print(f"vague words: {len(hits)}"); sys.exit(0 if not hits else 1)
