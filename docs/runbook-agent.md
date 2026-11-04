# Runbook vận hành agent · pha 1

## Nhịp
- Thứ Hai: `orchestrator/new_ticket.py` tạo ticket ai-draft từ sprint planning (task_type theo raci.yaml).
- Mỗi 15 phút: `python3 orchestrator/orchestrate.py --loop 900` (service trên máy có `claude` login tài khoản service, cwd = ai-team).
- Role owner: xem ticket ai-review → `orchestrator/review.py <ticket> <label> --scores ... --by <owner> [--fixed ref] [--reason ...]`.
- Thứ Năm: kỹ sư AI đọc `evals/raw/<agent>/*.json` nhãn sua/loai, sửa `.claude/agents|skills`, commit → agent_version đổi tự động; chạy lại 5 ticket cũ.
- Thứ Sáu: `psql -f db/dashboard.sql` hoặc xem view v_cost_by_agent_day, v_pass_rate_14d, v_month_budget.

## Sự cố
- Agent chạy quá maxTurns: run.json is_error → giảm phạm vi ticket (techlead chia nhỏ) → chạy lại; 3 lần thì chuyển người.
- Hook chặn (exit 2) nhiều: đúng hành vi; đếm trong log, nếu agent lặp lại cùng lỗi → sửa system prompt, không nới hook.
- Ngân sách agent theo hạn mức gói Claude Max của CTO (200 USD/tháng cố định, CTO 04/11/2026 thay 2.000 USD/tháng): hạn mức phiên 5 giờ và tuần (%), token agent 7 ngày. Tuần ≥ 80%: kỹ sư AI hạ model cho qa/writer bằng `model_override`, giảm lượt chạy lại, báo CTO. Tuần ≥ `budget_stop_pct` (90%) hoặc hết phiên 5 giờ: Orchestrator tự dừng giao việc; chỉ CTO nới trong `orchestrator/config.yaml`.
- Claude Code ở ai-team chạy auto mode không hỏi Yes/No (CTO 04/11/2026): việc cần CTO quyết nằm ở dashboard → Việc chờ tôi. Merge chỉ khi CTO đã chốt trong sổ duyệt `data/approvals.jsonl` (nút Chốt merge hoặc CTO gõ /merge-pr — hook ghi); `ops/merge_pr.sh` tự kiểm sổ. Hook `ops/hooks/guard_bash.py` chặn push develop/main, force push, merge/approve trực tiếp, publish/xoá theme, đọc .env. Đổi quyền/hook chỉ bằng patch của CTO.
- Ticket = ticket nội bộ SQLite `data/tickets.db` (quyết định CTO 03/11/2026, nguồn duy nhất). Thao tác qua `ops/ticket.py`, `mcp/ticket_local.py` hoặc dashboard menu Ticket; sao lưu tự động `data/backup/` (giữ 30 bản). Mất file .db: chép bản mới nhất trong `data/backup/` về `data/tickets.db`.
