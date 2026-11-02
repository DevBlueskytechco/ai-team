---
description: Áp file .patch (từ Claude chat) vào theme-efitco/ai-team hoặc lên nhánh PR đang mở
argument-hint: "<đường dẫn .patch> <theme|aiteam|pr:<n>> \"<tiêu đề PR>\""
allowed-tools: Bash(ops/apply_patch.sh*), Read
---
Đọc file patch trước (Read) để biết nó sửa gì, tóm tắt 2–3 dòng cho CTO.
Chạy `ops/apply_patch.sh $ARGUMENTS`. Patch không áp được hoặc theme check lỗi: báo đúng dòng lỗi, không sửa tay patch.
