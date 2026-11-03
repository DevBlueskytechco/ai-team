---
description: Mở dashboard theo dõi agent thời gian thực (http://localhost:8787)
allowed-tools: Bash(ops/dashboard.sh*)
---
Chạy `ops/dashboard.sh` Ở CHẾ ĐỘ NỀN (run_in_background, timeout 7200000) rồi báo CTO mở http://localhost:8787.
Dashboard tự cập nhật: agent đang chạy (mỗi 2s), ticket Zoho và PR/CI GitHub (mỗi 60s). Không cần chạy lại khi có ticket mới.
