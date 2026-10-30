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
    agent, tid = t["agent"], t["id"]; key = t.get("key") or tid
    if t.get("task_type") not in RACI.get(agent, []):
        T.set_label(tid, "ai-draft", note=f"orchestrator: {agent} không có A cho {t.get('task_type')} theo raci.yaml"); return None
    env = dict(os.environ, AI_AGENT=agent, AI_TICKET=tid, AI_TICKET_KEY=key, AI_AGENT_VERSION=agent_version(agent), AI_TEAM_DIR=ROOT)
    branch = None
    if agent != "gate-reviewer":
        # Mọi agent ghi file đều làm trên nhánh riêng; không bao giờ ghi lên develop
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=THEME, capture_output=True, text=True).stdout.strip()
        if dirty:
            print(f"BỎ QUA {key}: theme-efitco có thay đổi chưa commit, dọn trước khi chạy:\n{dirty[:500]}"); return None
        branch = f"feature/ai-{key}"
        subprocess.run(["git", "fetch", "origin"], cwd=THEME, check=False)
        subprocess.run(["git", "checkout", "-B", branch, "origin/develop"], cwd=THEME, check=True)
    prompt = (f"Ticket {key} (id {tid}): {t['title']}. Đọc ticket bằng mcp__ticket__get với id {tid}. Đặt tên file đầu ra theo key {key} "
              f"(vd drafts/{agent}/{key}/, tests/e2e/{key}.spec.ts). Làm theo skill của bạn, KHÔNG git commit/push (Orchestrator làm), "
              f"rồi set_label ai-review kèm tóm tắt tự kiểm tra.")
    cmd = [CFG["claude_bin"], "-p", "--agent", agent, "--permission-mode", CFG["permission_mode"], "--output-format", "json",
           "--max-turns", str(t.get("max_turns") or CFG["max_turns_default"])]
    if CFG.get("model_override", {}).get(agent): cmd += ["--model", CFG["model_override"][agent]]
    cmd.append(prompt)
    started = datetime.datetime.now().isoformat(timespec="seconds")
    r = subprocess.run(cmd, cwd=THEME, env=env, capture_output=True, text=True, timeout=3600)
    try: out = json.loads(r.stdout)
    except Exception: out = {"result": r.stdout[-2000:], "stderr": r.stderr[-2000:], "is_error": True}
    rec = {"agent": agent, "ticket": key, "ticket_id": tid, "task_type": t.get("task_type"), "agent_version": env["AI_AGENT_VERSION"],
           "model": out.get("model") or ",".join((out.get("modelUsage") or {}).keys()) or CFG.get("model_override", {}).get(agent, ""), "tokens": (out.get("usage") or {}).get("output_tokens"),
           "cost_usd": out.get("total_cost_usd"), "num_turns": out.get("num_turns"), "session_id": out.get("session_id"),
           "started_at": started, "is_error": out.get("is_error", False), "result": (out.get("result") or "")[:4000]}
    d = os.path.join(ROOT, "evals/raw", agent); os.makedirs(d, exist_ok=True)
    json.dump(rec, open(os.path.join(d, f"{key}.run.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(os.path.join(ROOT, "evals/raw/_runs.jsonl"), "a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
    if branch:
        rec["branch"] = branch
        subprocess.run(["git", "add", "-A"], cwd=THEME, check=False)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=THEME).returncode != 0
        if staged:
            subprocess.run(["git", "commit", "-q", "-m", f"ai({agent}): {key} {t['title']}\n\nAgent-Version: {rec['agent_version']}\nSession: {rec['session_id']}"], cwd=THEME, check=False)
            p = subprocess.run(["git", "push", "-q", "-u", "origin", branch], cwd=THEME, capture_output=True, text=True)
            rec["pushed"] = p.returncode == 0
            if p.returncode != 0: print(f"push {branch} lỗi: {p.stderr[-300:]}")
            link = f"branch {branch}"
            if rec.get("pushed") and agent in ("dev-fe", "dev-be", "devops"):
                pr = subprocess.run(["gh", "pr", "create", "-B", "develop", "-H", branch, "-t", f"{key}: {t['title'][:200]}",
                                     "-b", f"Ticket {key} (Zoho {tid}). Agent {rec['agent_version']}, {rec['num_turns']} turns, ~{rec['cost_usd']} USD.\n\n{rec['result'][:3000]}"],
                                    cwd=THEME, capture_output=True, text=True)
                if pr.returncode == 0: link = pr.stdout.strip().splitlines()[-1]; rec["pr"] = link
                else: print(f"tạo PR lỗi: {pr.stderr[-300:]}")
            T.set_label(tid, "ai-review", link=link, note=f"orchestrator: đầu ra {link}")
        subprocess.run(["git", "checkout", "-q", "develop"], cwd=THEME, check=False)
        json.dump(rec, open(os.path.join(d, f"{key}.run.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
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
        p = os.path.join(ROOT, "evals/raw", t["agent"], f"{t.get('key') or t['id']}.json")
        if os.path.exists(p): continue
        runp = p.replace(".json", ".run.json"); run = json.load(open(runp)) if os.path.exists(runp) else {}
        rev = t.get("review") or {}
        rec = {"agent": t["agent"], "ticket": t.get("key") or t["id"], "ticket_id": t["id"], "task_type": t.get("task_type", ""), "input_refs": t.get("input_refs", []),
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

SIDE_TYPE = {"fe": "fe_task", "be": "be_task"}

def blockers_open(full):
    """Trả danh sách key ticket chặn chưa xong (closed hoặc ai-dat mới tính là xong)."""
    out = []
    for b in full.get("blocked_by") or []:
        try:
            if not (T.is_done(b) if hasattr(T, "is_done") else "ai-dat" in T.get(b).get("labels", [])): out.append(T.get(b).get("key") or b)
        except Exception: out.append(b)
    return out

def pick(only=None):
    """Ticket ai-draft đủ điều kiện chạy, theo thứ tự key. Bỏ câu hỏi [Q] (cho người trả lời)."""
    ready = []
    for t in T.list(label="ai-draft"):
        full = T.get(t["id"])
        if only and full.get("key") != only: continue
        if (full.get("status") or "").lower() in ("closed", "đã đóng", "cancelled"): continue
        if not full.get("agent") or (full.get("title") or "").startswith("[Q]"): continue
        if not full.get("task_type") and full.get("side") in SIDE_TYPE: full["task_type"] = SIDE_TYPE[full["side"]]
        bl = blockers_open(full)
        if bl: print(f"chờ {full.get('key')}: bị chặn bởi {', '.join(bl)}"); continue
        ready.append(full)
    return sorted(ready, key=lambda x: int(re.sub(r"\D", "", x.get("key") or "0") or 0))

def once(max_n=1, only=None):
    if not remind_and_budget(): return
    make_eval_records()
    for full in pick(only)[:max_n]:
        print("→", full.get("key"), full["agent"]); run_agent(full)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--once", action="store_true"); ap.add_argument("--loop", type=int, default=0); ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max", type=int, default=1, help="số ticket tối đa mỗi lượt (mặc định 1)"); ap.add_argument("--ticket", help="chỉ chạy ticket key này, vd ES1-T12")
    a = ap.parse_args()
    if a.dry:
        remind_and_budget(); make_eval_records()
        for full in pick(a.ticket): print("would run", full.get("key"), full["agent"], full.get("task_type"), "ok" if full.get("task_type") in RACI.get(full["agent"], []) else "RACI DENY")
    elif a.loop:
        while True: once(a.max, a.ticket); time.sleep(a.loop)
    else: once(a.max, a.ticket)
