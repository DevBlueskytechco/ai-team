---
description: Review PR của agent theo rubric + quy ước team, đề xuất chấm điểm và merge hay sửa
argument-hint: "<số PR>"
allowed-tools: Bash(ops/pr_report.sh*), Bash(ops/ci_watch.sh*), Bash(python3 ops/ticket.py*), Bash(source ops/env.sh*), Read, Grep, Glob
---
1. `ops/pr_report.sh $ARGUMENTS`. CI chưa xong thì chạy `ops/ci_watch.sh $ARGUMENTS` ở chế độ nền và chờ.
2. Đọc toàn bộ /tmp/pr-$ARGUMENTS.diff, ticket (`python3 ops/ticket.py show <key>`), AC liên quan trong ../theme-efitco/docs/srs.md, rubric ../ai-team/rubrics/<agent>.yaml, ../theme-efitco/AGENTS.md và .claude/rules/.
3. Kiểm bắt buộc: đúng AC; Skeleton block-first (doc, schema không presets, shopify_attributes, chuỗi qua | t, routes.*); JS chỉ ở BE, FE không có .js; chỉ dùng token CSS; a11y (tên truy cập, focus, contrast); locale JSON không trùng key; không sửa ngoài phạm vi ticket.
4. Phân loại lỗi CI: lỗi do code PR / lỗi môi trường (store, dữ liệu, Shopify 502) / lỗi test. Lighthouse không chặn merge (quyết định CTO 31/10) nhưng báo điểm + A11Y FAIL.
5. Trả CTO: bảng điểm từng tiêu chí rubric (0/1/2 + lý do 1 dòng), nhãn đề xuất (dat/sua_nhe/sua_nang/loai), danh sách việc phải sửa trước merge.
   - Cần sửa nhỏ: viết sửa trực tiếp trên nhánh PR trong ../theme-efitco (checkout nhánh, sửa, `shopify theme check`, commit, push), rồi quay về develop.
   - Cần làm lại: đề xuất comment lên ticket và set ai-draft để agent chạy lại.
6. Kết thúc bằng lệnh merge đề xuất dạng: `/merge-pr <n> <nhãn> <scores> "<lý do>"`. KHÔNG tự merge.
