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
- Chạm 80% ngân sách: hạ model cho qa/writer bằng `model_override`; chạm 100%: orchestrator dừng, CTO nới.
- Ticket backend = Zoho Projects (quyết định CTO 22/10). Cấu hình trong `ai-team/.env` (mẫu `.env.example`); adapter `mcp/ticket_zoho.py`; dò field bằng `python3 mcp/zoho_probe.py`. Backend file vẫn dùng được khi `TICKET_BACKEND=file` (thử nghiệm offline).
- Zoho lỗi 401/invalid_token: refresh token hết hạn hoặc sai DC → tạo lại ở api-console.zoho.<dc>; lỗi 400 custom field: api_name sai → chạy probe, sửa `ZOHO_CF_*`.
