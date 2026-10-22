#!/usr/bin/env python3
"""Orchestrator pha 1 (chế độ nháp). Mỗi vòng:
1. đọc ticket nhãn ai-draft có trường agent + task_type; kiểm RACI
2. tạo nhánh feature/ai-<ticket> (với dev-*), chạy `claude -p --agent <agent>`; ghi JSON run vào evals/raw/<agent>/<ticket>.run.json
3. đổi nhãn ai-review kèm link; ghi run vào runs.jsonl (và Postgres nếu DATABASE_URL)
4. nhắc ticket ai-review quá hạn; cảnh báo ngân sách
5. ticket đã chấm (ai-dat/ai-sua/ai-loai, chưa có record) → sinh evals/raw/<agent>/<ticket>.json
Không có cổng tự qua. Không merge. Không deploy."""
import os, sys, json, subprocess, datetime, hashlib, argparse, time, re
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
import yaml  # pip install pyyaml
CFG = yaml.safe_load(open(os.path.join(HERE, "config.yaml")))
RACI = yaml.safe_load(open(os.path.join(HERE, "raci.yaml")))
THEME = os.path.abspath(os.path.join(ROOT, CFG["theme_dir"]))
sys.path.insert(0, os.path.join(ROOT, "mcp")); import ticket_server as T

def agent_version(agent):
    h = hashlib.sha256()
    for p in [f".claude/agents/{agent}.md"] + [f".claude/skills/{s}/SKILL.md" for s in skills_of(agent)]:
        fp = os.path.join(THEME, p)
        if os.path.exists(fp): h.update(open(fp, "rb").read())
    return f"{agent}@{h.hexdigest()[:10]}"
def skills_of(agent):
    txt = open(os.path.join(THEME, f".claude/agents/{agent}.md"), encoding="utf-8").read()
    m = re.search(r"skills:\n((?:  - .+\n)+)", txt); return [l.strip()[2:] for l in m.group(1).splitlines()] if m else []

def run_agent(t):
    agent, tid = t["agent"], t["id"]
    if t.get("task_type") not in RACI.get(agent, []):
        T.set_label(tid, "ai-draft", note=f"orchestrator: {agent} không có A cho {t.get('task_type')} theo raci.yaml"); return None
    env = dict(os.environ, AI_AGENT=agent, AI_TICKET=tid, AI_AGENT_VERSION=agent_version(agent), AI_TEAM_DIR=ROOT)
    if agent in ("dev-fe", "dev-be"):
        subprocess.run(["git", "fetch", "origin"], cwd=THEME, check=False)
        subprocess.run(["git", "checkout", "-B", f"feature/ai-{tid}", "origin/develop"], cwd=THEME, check=False)
    prompt = f"Ticket {tid}: {t['title']}. Đọc ticket bằng mcp__ticket__get, làm theo skill của bạn, nộp đúng nơi quy định rồi set_label ai-review kèm link và tóm tắt tự kiểm tra."
    cmd = [CFG["claude_bin"], "-p", "--agent", agent, "--permission-mode", CFG["permission_mode"], "--output-format", "json",
           "--max-turns", str(t.get("max_turns") or CFG["max_turns_default"])]
    if CFG.get("model_override", {}).get(agent): cmd += ["--model", CFG["model_override"][agent]]
    cmd.append(prompt)
    started = datetime.datetime.now().isoformat(timespec="seconds")
    r = subprocess.run(cmd, cwd=THEME, env=env, capture_output=True, text=True, timeout=3600)
    try: out = json.loads(r.stdout)
    except Exception: out = {"result": r.stdout[-2000:], "stderr": r.stderr[-2000:], "is_error": True}
    rec = {"agent": agent, "ticket": tid, "task_type": t.get("task_type"), "agent_version": env["AI_AGENT_VERSION"],
           "model": out.get("model") or CFG.get("model_override", {}).get(agent, ""), "tokens": (out.get("usage") or {}).get("output_tokens"),
           "cost_usd": out.get("total_cost_usd"), "num_turns": out.get("num_turns"), "session_id": out.get("session_id"),
           "started_at": started, "is_error": out.get("is_error", False), "result": (out.get("result") or "")[:4000]}
    d = os.path.join(ROOT, "evals/raw", agent); os.makedirs(d, exist_ok=True)
    json.dump(rec, open(os.path.join(d, f"{tid}.run.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(os.path.join(ROOT, "evals/raw/_runs.jsonl"), "a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
    cur = T.get(tid)
    if "ai-review" not in cur.get("labels", []):
        T.set_label(tid, "ai-review", note=f"orchestrator: agent kết thúc (turns={rec['num_turns']}, cost={rec['cost_usd']}); chưa tự set_label — kiểm tra đầu ra")
    pg_insert(rec); return rec

def pg_insert(rec):
    url = os.environ.get("DATABASE_URL")
    if not url: return
    try:
        import psycopg2; c = psycopg2.connect(url); cur = c.cursor()
        cur.execute("insert into runs(agent,ticket,task_type,agent_version,model,tokens,cost_usd,turns,started_at,is_error) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (rec["agent"], rec["ticket"], rec["task_type"], rec["agent_version"], rec["model"], rec["tokens"], rec["cost_usd"], rec["num_turns"], rec["started_at"], rec["is_error"]))
        c.commit(); c.close()
    except Exception as e: print("pg:", e)

def make_eval_records():
    for t in T.all():
        lab = next((l for l in t.get("labels", []) if l in ("ai-dat", "ai-sua", "ai-loai")), None)
        if not lab or not t.get("agent"): continue
        p = os.path.join(ROOT, "evals/raw", t["agent"], f"{t['id']}.json")
        if os.path.exists(p): continue
        runp = p.replace(".json", ".run.json"); run = json.load(open(runp)) if os.path.exists(runp) else {}
        rev = t.get("review") or {}
        rec = {"agent": t["agent"], "ticket": t["id"], "task_type": t.get("task_type", ""), "input_refs": t.get("input_refs", []),
               "agent_output_ref": t.get("output_link", ""), "agent_version": run.get("agent_version", ""), "model": run.get("model", ""),
               "tokens": run.get("tokens"), "cost_usd": run.get("cost_usd"), "num_turns": run.get("num_turns"),
               "self_check": rev.get("self_check", {}), "label": {"ai-dat": "dat", "ai-sua": rev.get("severity", "sua_nhe"), "ai-loai": "loai"}[lab],
               "rubric_scores": rev.get("scores", {}), "reviewer": rev.get("by", ""), "fixed_output_ref": rev.get("fixed_ref", ""),
               "reason": rev.get("reason", ""), "reviewed_at": rev.get("at", datetime.date.today().isoformat())}
        os.makedirs(os.path.dirname(p), exist_ok=True); json.dump(rec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2); print("eval record", p)

def remind_and_budget():
    today = datetime.date.today()
    for t in T.list(label="ai-review"):
        full = T.get(t["id"]); last = max((c["at"] for c in full.get("comments", [])), default=full.get("created_at", str(today)))
        if (today - datetime.date.fromisoformat(last[:10])).days >= CFG["review_overdue_days"]:
            print(f"NHẮC: {t['id']} ở ai-review quá {CFG['review_overdue_days']} ngày — role owner {t['agent']}")
    runs = os.path.join(ROOT, "evals/raw/_runs.jsonl"); spent = 0.0
    if os.path.exists(runs):
        for l in open(runs, encoding="utf-8"):
            try: r = json.loads(l)
            except Exception: continue
            if (r.get("started_at") or "")[:7] == today.strftime("%Y-%m") and r.get("cost_usd"): spent += float(r["cost_usd"])
    pct = spent / CFG["budget_usd_month"] * 100
    print(f"Token tháng này: {spent:.2f} USD ({pct:.0f}% ngân sách)")
    if pct >= 100: print("DỪNG: chạm 100% ngân sách — chờ người nới"); return False
    if pct >= CFG["budget_warn_pct"]: print("CẢNH BÁO: ≥ 80% ngân sách")
    return True

def once():
    if not remind_and_budget(): return
    make_eval_records()
    for t in T.list(label="ai-draft"):
        full = T.get(t["id"])
        if not full.get("agent"): continue
        print("→", full["id"], full["agent"]); run_agent(full)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--once", action="store_true"); ap.add_argument("--loop", type=int, default=0); ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.dry:
        remind_and_budget(); make_eval_records()
        for t in T.list(label="ai-draft"): print("would run", t["id"], t["agent"], "ok" if T.get(t["id"]).get("task_type") in RACI.get(t["agent"], []) else "RACI DENY")
    elif a.loop:
        while True: once(); time.sleep(a.loop)
    else: once()
