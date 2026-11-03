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
- Ngân sách token 2.000 USD/tháng (`orchestrator/config.yaml`). Chạm 80%: kỹ sư AI hạ model cho qa/writer bằng `model_override`, báo CTO. Chạm 100%: orchestrator tự dừng; chỉ CTO (Tony Pham) được nới bằng cách sửa `budget_usd_month` và commit kèm lý do; kỹ sư AI không tự sửa.
- Ticket = ticket nội bộ SQLite `data/tickets.db` (quyết định CTO 03/11/2026, nguồn duy nhất). Thao tác qua `ops/ticket.py`, `mcp/ticket_local.py` hoặc dashboard menu Ticket; sao lưu tự động `data/backup/` (giữ 30 bản). Mất file .db: chép bản mới nhất trong `data/backup/` về `data/tickets.db`.
