---
description: Tự chạy liên tiếp các ticket sẵn sàng; dừng ở mỗi PR chờ CTO duyệt
argument-hint: "[số ticket tối đa, mặc định 3]"
allowed-tools: Bash(ops/*), Bash(source ops/env.sh*), Bash(python3 ops/*), Read, Grep, Glob
---
Lặp tối đa ${ARGUMENTS:-3} lượt:
1. `source ops/env.sh && python3 ops/status.py`. Không còn ticket sẵn sàng → dừng, báo CTO.
2. Làm quy trình /run-next (chạy nền, chờ xong).
3. Nếu lượt tạo PR: làm quy trình /review-pr. Đề xuất lệnh /merge-pr rồi DỪNG CHỜ CTO — không merge, không chạy ticket kế tiếp có blocked_by vào ticket này.
4. Nếu lượt không tạo PR (QA/Tech Lead): tóm tắt đầu ra, đề xuất chấm điểm, rồi sang lượt kế tiếp.
Dừng ngay khi: preflight lỗi, agent is_error, CI lỗi môi trường, ngân sách token ≥ 80%, hoặc gói Claude báo usage limit.
Cuối cùng in bảng: ticket đã chạy, PR tạo ra, việc CTO cần làm.
