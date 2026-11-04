---
description: CTO chốt merge PR (ghi sổ duyệt) rồi merge, chấm điểm, đóng ticket
argument-hint: "<số PR> <dat|sua_nhe|sua_nang|loai> <scores k=v,...> \"<lý do>\""
allowed-tools: Bash(ops/merge_pr.sh*), Bash(python3 ops/status.py*), Bash(source ops/env.sh*)
---
CTO gõ lệnh này = đã chốt: hook UserPromptExpansion (ops/hooks/cto_command.py) ghi sổ duyệt trước khi lệnh tới bạn. Chạy luôn `ops/merge_pr.sh $ARGUMENTS`, không hỏi lại.
Script tự dừng nếu theme-check/preview/e2e/lighthouse chưa pass — khi đó báo lý do; CI bị huỷ/lỗi môi trường thì rerun theo CLAUDE.md, sổ duyệt còn hiệu lực 72 giờ nên check đạt thì chạy lại `ops/merge_pr.sh <n>`, không tìm cách vòng.
Xong thì chạy `source ops/env.sh && python3 ops/status.py` và gợi ý ticket kế tiếp (/run-next).
