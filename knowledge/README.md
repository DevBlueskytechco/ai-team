# Kiến thức agent do CTO nạp

Mỗi agent một thư mục: `knowledge/<agent>/<id>.md` (po, ba, designer, techlead, dev-fe, dev-be, qa, devops, writer, gate-reviewer).
`knowledge/_chung/` áp dụng cho mọi agent. `_archive/` trong mỗi thư mục là mục đã lưu trữ (không xoá).

Quản lý ở dashboard: Vai trò → cột Kiến thức, hoặc menu Vận hành → Kiến thức agent. Dòng lệnh: `python3 orchestrator/knowledge.py --help`.

Mỗi file:

```
---
title: Badge sale tính theo variant đang chọn
kind: kinh-nghiem        # kinh-nghiem | quy-tac | tai-lieu | checklist | bai-hoc
priority: cao            # cao | thuong
status: active           # active | off
source: ES1-T56 (CTO chấm sửa nhẹ)
by: cto
created: 2026-11-04T10:00:00
updated: 2026-11-04T10:00:00
---
Nội dung markdown: ngắn, cụ thể, agent làm theo được.
```

Orchestrator nối mục `active` (chung trước rồi riêng, ưu tiên cao trước) vào prompt agent mỗi lượt, tối đa 12.000 ký tự,
và cộng nội dung vào agent_version để eval so được trước/sau khi đổi kiến thức. Agent không ghi được thư mục này.
Mâu thuẫn với AGENTS.md / ADR thì AGENTS.md / ADR thắng.
