---
description: Duyệt + merge PR, chấm điểm, đóng ticket — chỉ khi CTO gõ lệnh này
argument-hint: "<số PR> <dat|sua_nhe|sua_nang|loai> <scores k=v,...> \"<lý do>\""
allowed-tools: Bash(ops/merge_pr.sh*), Bash(python3 ops/status.py*), Bash(source ops/env.sh*)
---
CTO đã gõ lệnh này = đồng ý merge. Chạy `ops/merge_pr.sh $ARGUMENTS`.
Script tự dừng nếu theme-check/preview/e2e/lighthouse chưa pass — khi đó báo CTO lý do, không tìm cách vòng.
Xong thì chạy `source ops/env.sh && python3 ops/status.py` và gợi ý ticket kế tiếp (/run-next).
