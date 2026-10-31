---
description: Cho agent làm ticket kế tiếp (hoặc ticket chỉ định), chờ PR + CI, báo kết quả
argument-hint: "[ES1-Txx]"
allowed-tools: Bash(ops/run_next.sh*), Bash(ops/ci_watch.sh*), Bash(ops/pr_report.sh*), Bash(source ops/env.sh*), Bash(python3 ops/*), Read
---
1. Chạy `ops/run_next.sh $ARGUMENTS` Ở CHẾ ĐỘ NỀN (run_in_background, timeout 3600000) — agent chạy 3–20 phút. Không chạy lại khi đang chạy.
2. Khi xong, đọc phần "Kết quả lượt chạy". Nếu preflight lỗi hoặc `is_error: True`: báo lỗi + nguyên nhân + cách sửa, DỪNG.
3. Nếu có `pr`: lấy số PR, chạy `ops/ci_watch.sh <số>` ở chế độ nền (chờ CI), rồi làm đúng quy trình /review-pr với PR đó.
4. Nếu agent không tạo PR (agent không sửa code: QA/Tech Lead/BA): chạy `python3 ops/ticket.py show <key>` và `python3 ops/ticket.py children <story>` khi là task_split; tóm tắt đầu ra cho CTO, đề xuất chấm điểm theo rubrics/<agent>.yaml.
Không merge, không approve trong lệnh này.
