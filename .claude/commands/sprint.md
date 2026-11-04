---
description: Tự chạy liên tiếp các ticket sẵn sàng; PR chờ CTO chốt thì để ở Việc chờ tôi, làm ticket khác
argument-hint: "[số ticket tối đa, mặc định 3]"
allowed-tools: Bash(ops/*), Bash(source ops/env.sh*), Bash(python3 ops/*), Bash(gh run rerun*), Read, Grep, Glob
---
Lặp tối đa ${ARGUMENTS:-3} lượt, không hỏi Yes/No giữa chừng:
1. `source ops/env.sh && python3 ops/status.py`. Mục "CTO đã chốt" có PR mà check đạt → `ops/merge_pr.sh <n>` trước. Không còn ticket sẵn sàng và không còn PR đã chốt → dừng, báo CTO.
2. Làm quy trình /run-next (chạy nền, chờ xong).
3. Nếu lượt tạo PR: làm quy trình /review-pr (CI bị huỷ/lỗi môi trường thì tự rerun theo CLAUDE.md). PR đã có trong sổ duyệt → `ops/merge_pr.sh <n>`. Chưa chốt → comment đề xuất nhãn/điểm lên ticket, để ở Việc chờ tôi, sang ticket kế tiếp không phụ thuộc (bỏ qua ticket có blocked_by vào ticket này) — không dừng chờ.
4. Nếu lượt không tạo PR (QA/Tech Lead): tóm tắt đầu ra, đề xuất chấm điểm, rồi sang lượt kế tiếp.
Dừng ngay khi: preflight lỗi, agent is_error, CI lỗi môi trường đã rerun 2 lần vẫn lỗi, mục Gói Claude của status có CẢNH BÁO/DỪNG (hạn mức phiên 5 giờ hoặc tuần ≥ 80%), hoặc lượt chạy có limit_hit (chạm hạn mức gói).
Cuối cùng in bảng: ticket đã chạy, PR tạo ra, việc CTO cần làm.
