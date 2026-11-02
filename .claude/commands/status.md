---
description: Bảng trạng thái sprint Efitco — ticket Zoho, PR mở, CI develop
allowed-tools: Bash(source ops/env.sh*), Bash(python3 ops/status.py*), Bash(ops/preflight.sh*)
---
Chạy `source ops/env.sh && python3 ops/status.py` rồi `ops/preflight.sh`.
Trả lời CTO bằng tiếng Việt, ngắn:
1. Ticket nào sẵn sàng chạy kế tiếp (ai-draft, không bị chặn, không phải [Q]).
2. Ticket chờ CTO: ai-review chưa chấm, câu hỏi [Q] chưa trả lời.
3. PR mở và trạng thái CI; PR nào đủ điều kiện review.
4. Lỗi preflight (nếu có) và cách sửa.
Kết thúc bằng 1 dòng "Việc tiếp theo: ..." gợi ý đúng 1 lệnh (/run-next, /review-pr <n>, ...).
