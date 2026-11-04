# Yêu cầu dự án

Mỗi yêu cầu một file `requirements/REQ-xxxx.md`; `_archive/` là yêu cầu đã lưu trữ (không xoá).
Quản lý ở dashboard: menu Quản lý dự án → Yêu cầu dự án / Nạp yêu cầu. Dòng lệnh: `python3 orchestrator/requirements.py --help`.

```
---
id: REQ-0001
title: Shopify Editions Fall '26: theme blocks dùng được trong app block
source: shopify          # ban-giam-doc | quan-ly-san-pham | cto | shopify | khach-hang | khac
from: shopify.dev changelog
received: 2026-11-04
due: 2026-11-30
priority: cao            # cao | vua | thap
status: moi              # moi | phan-tich | ap-dung | xong | khong
agents: techlead, dev-fe # agent bị ảnh hưởng; trống = mọi agent
stories: TE-14
link: https://…
tickets: ES1-T80         # ticket phân tích đã giao
history: … | …
---
Nội dung yêu cầu (markdown).
```

Vòng đời:
1. **Mới** — vừa nạp.
2. **Đang phân tích** — ticket ai-draft cho PO (change_request), BA (srs) hoặc Tech Lead (adr). Agent ghi
   `drafts/<agent>/<ticket>/impact.md` với `## Tóm tắt`, `## Ảnh hưởng`, `## Kiến thức cho <agent>: <tiêu đề>`,
   `## Sửa skill <tên>: <tóm tắt>`, `## Ticket cần tạo`. Dashboard đọc file này để CTO nạp kiến thức bằng một nút.
3. **Đang áp dụng** — Orchestrator nối yêu cầu vào prompt agent bị ảnh hưởng mỗi lượt (tối đa 6.000 ký tự), tính vào agent_version.
4. **Đã áp dụng** — nội dung đã vào skill/kiến thức, thôi nạp. **Không áp dụng** — bỏ.
