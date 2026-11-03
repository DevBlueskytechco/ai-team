---
description: Chuyển ticket từ Zoho sang ticket nội bộ (data/tickets.db) — chạy 1 lần
allowed-tools: Bash(source ops/env.sh*), Bash(python3 ops/ticket_migrate_zoho.py*), Bash(python3 ops/ticket.py*), Read
---
1. Hỏi CTO đã dừng mọi lượt agent chưa (không có /run-next, /sprint đang chạy). Chưa thì dừng.
2. `source ops/env.sh && python3 ops/ticket_migrate_zoho.py` (thêm `--refresh` nếu CTO yêu cầu kéo lại). Chờ xong (vài phút, tự chờ khi Zoho giới hạn).
3. Kiểm: `python3 ops/ticket.py show ES1-T1` và đếm ticket mở: `source ops/env.sh && python3 ops/status.py`.
4. Báo CTO: số ticket, số comment đã chuyển; nhắc mở dashboard menu Ticket; Zoho từ giờ chỉ đọc, không tạo ticket trên Zoho nữa.
