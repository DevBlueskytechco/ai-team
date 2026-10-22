# ai-team — bộ máy vận hành 9 agent cho theme-ember

```
rubrics/      9 rubric YAML (role owner chấm, gate-reviewer chấm)
evals/raw/    bản ghi eval sinh sau mỗi lần chấm (schema: evals/schema/record.schema.json)
evals/golden/ mẫu chuẩn role owner nộp tuần 2
evals/sets/   bộ eval chốt tuần 13
checks/       script tự kiểm tra (ac_coverage, vague_words, traceability)
mcp/          MCP server: ticket (file backend, đổi sang Zoho/Linear bằng adapter), store-dev, figma
orchestrator/ orchestrate.py: phát ticket ai-draft → claude -p --agent → ghi run → ai-review; raci.yaml
db/           schema Postgres + query dashboard
docs/         runbook vận hành agent
```
Chạy: `python3 orchestrator/orchestrate.py --once` (một vòng) hoặc `--loop 900` (mỗi 15 phút). Cần `claude` CLI đã login bằng tài khoản service; làm việc trong `../theme-ember`.
