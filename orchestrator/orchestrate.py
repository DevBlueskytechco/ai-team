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
sys.path.insert(0, HERE); import knowledge as KN   # kiến thức CTO nạp cho agent (ai-team/knowledge)
import requirements as RQ   # yêu cầu dự án đang áp dụng (ai-team/requirements)
# Thao tác ticket của chính Orchestrator (comment PR, đổi nhãn, nhắc việc) ghi tên "orchestrator". /run-next chạy trong Claude Code,
# nơi AI_AGENT=claude-code_<bản>_agent — bỏ đi; agent con vẫn nhận AI_AGENT=<agent> qua env riêng ở run_agent.
if os.environ.get("AI_AGENT", "").startswith("claude-code"): os.environ.pop("AI_AGENT")
os.environ["TICKET_USER"] = "orchestrator"

def agent_version(agent):
    h = hashlib.sha256()
    for p in [f".claude/agents/{agent}.md"] + [f".claude/skills/{s}/SKILL.md" for s in skills_of(agent)]:
        fp = os.path.join(THEME, p)
        if os.path.exists(fp): h.update(open(fp, "rb").read())
    h.update(KN.digest(agent).encode())   # đổi kiến thức CTO nạp = agent_version mới, eval so được trước/sau
    h.update(RQ.digest(agent).encode())   # yêu cầu dự án đang áp dụng cũng tính vào phiên bản agent
    return f"{agent}@{h.hexdigest()[:10]}"
def skills_of(agent):
    txt = open(os.path.join(THEME, f".claude/agents/{agent}.md"), encoding="utf-8").read()
    m = re.search(r"skills:\n((?:  - .+\n)+)", txt); return [l.strip()[2:] for l in m.group(1).splitlines()] if m else []

# Danh tính agent trên GitHub: commit, push, mở PR bằng nextsky-ai-agent (AGENT_GH_TOKEN trong .env),
# để CTO duyệt PR như người thứ hai. Không có token thì dùng tài khoản đang đăng nhập (cảnh báo).
_AGT = os.environ.get("AGENT_GH_TOKEN", "")
if _AGT:
    import base64
    _hdr = base64.b64encode(f"x-access-token:{_AGT}".encode()).decode()
    AGENT_GIT = ["-c", "user.name=nextsky-ai-agent", "-c", "user.email=nextsky-ai-agent@users.noreply.github.com",
                 "-c", "credential.helper=", "-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {_hdr}"]
    AGENT_GH_ENV = dict(os.environ, GH_TOKEN=_AGT)
else:
    print("CẢNH BÁO: thiếu AGENT_GH_TOKEN — PR sẽ đứng tên tài khoản đang đăng nhập, CTO không tự duyệt được")
    AGENT_GIT, AGENT_GH_ENV = [], dict(os.environ)

LIVE_DIR = os.path.join(ROOT, "evals/raw/live")

def _live_write(state):
    """evals/raw/_live.json: agent đang chạy (dashboard đọc). state=None → xoá."""
    p = os.path.join(ROOT, "evals/raw/_live.json")
    if state is None:
        if os.path.exists(p): os.remove(p)
        return
    tmp = p + ".tmp"; json.dump(state, open(tmp, "w", encoding="utf-8"), ensure_ascii=False); os.replace(tmp, p)

def stream_agent(cmd, env, key, agent, t, started):
    """Chạy claude -p ở stream-json: ghi từng sự kiện vào evals/raw/live/<key>.jsonl để dashboard xem thời gian thực.
    Trả về object giống --output-format json (lấy từ sự kiện type=result)."""
    os.makedirs(LIVE_DIR, exist_ok=True)
    log = os.path.join(LIVE_DIR, f"{key}.jsonl")
    state = {"ticket": key, "agent": agent, "title": t.get("title"), "started_at": started, "pid": None,
             "turns": 0, "tools": 0, "last": "", "log": os.path.relpath(log, ROOT)}
    out, err_tail = None, []
    with open(log, "w", encoding="utf-8") as fh:
        p = subprocess.Popen(cmd, cwd=THEME, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        state["pid"] = p.pid; _live_write(state)
        deadline = time.time() + 3600
        for line in p.stdout:
            fh.write(line); fh.flush()
            try: ev = json.loads(line)
            except Exception: continue
            typ = ev.get("type")
            if typ == "assistant":
                state["turns"] += 1
                for c in (ev.get("message") or {}).get("content") or []:
                    if c.get("type") == "tool_use":
                        state["tools"] += 1
                        inp = c.get("input") or {}
                        state["last"] = f"{c.get('name')} " + str(inp.get("command") or inp.get("file_path") or inp.get("pattern") or "")[:140]
                    elif c.get("type") == "text" and c.get("text"):
                        state["last"] = c["text"].strip().replace("\n", " ")[:160]
                _live_write(state)
            elif typ == "result":
                out = ev
            if time.time() > deadline:
                p.kill(); break
        p.wait()
        err_tail = (p.stderr.read() or "")[-2000:]
    # agent xong: Orchestrator còn commit/push/mở PR — dashboard hiện bước này thay vì "không có agent"
    state.update(phase="push", pid=os.getpid(), last="Orchestrator: commit, push, mở PR")
    _live_write(state)
    if out is None:
        out = {"result": "không có sự kiện result (agent lỗi hoặc quá 60 phút)", "stderr": err_tail, "is_error": True}
    return out

def run_agent(t):
    try: return _run_agent(t)
    finally: _live_write(None)

def _run_agent(t):
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
    kn, kn_used, kn_skip = KN.prompt_for(agent)
    if kn:
        prompt += kn
        print(f"{key}: nạp {len(kn_used)} mục kiến thức CTO ({len(kn)} ký tự)" + (f", bỏ {len(kn_skip)} mục vì quá giới hạn" if kn_skip else ""))
    rq, rq_used, rq_skip = RQ.prompt_for(agent)
    if rq:
        prompt += rq
        print(f"{key}: nạp {len(rq_used)} yêu cầu dự án đang áp dụng ({len(rq)} ký tự)" + (f", bỏ {len(rq_skip)} vì quá giới hạn" if rq_skip else ""))
    cmd = [CFG["claude_bin"], "-p", "--agent", agent, "--permission-mode", CFG["permission_mode"], "--output-format", "stream-json", "--verbose",
           "--max-turns", str(t.get("max_turns") or CFG["max_turns_default"])]
    if CFG.get("model_override", {}).get(agent): cmd += ["--model", CFG["model_override"][agent]]
    cmd.append(prompt)
    started = datetime.datetime.now().isoformat(timespec="seconds")
    out = stream_agent(cmd, env, key, agent, t, started)
    ended = datetime.datetime.now()
    rec = {"agent": agent, "ticket": key, "ticket_id": tid, "task_type": t.get("task_type"), "agent_version": env["AI_AGENT_VERSION"],
           "knowledge": [f"{x['agent']}/{x['id']}" for x in kn_used], "requirements": [r["id"] for r in rq_used],
           "model": out.get("model") or ",".join((out.get("modelUsage") or {}).keys()) or CFG.get("model_override", {}).get(agent, ""), "tokens": (out.get("usage") or {}).get("output_tokens"),
           "cost_usd": out.get("total_cost_usd"), "num_turns": out.get("num_turns"), "session_id": out.get("session_id"),
           "started_at": started, "ended_at": ended.isoformat(timespec="seconds"),
           "duration_s": int((ended - datetime.datetime.fromisoformat(started)).total_seconds()), "is_error": out.get("is_error", False), "result": (out.get("result") or "")[:4000]}
    d = os.path.join(ROOT, "evals/raw", agent); os.makedirs(d, exist_ok=True)
    json.dump(rec, open(os.path.join(d, f"{key}.run.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    try: _push_and_pr(rec, t, tid, key, agent, branch, d)
    finally:   # một dòng mỗi lượt, có nhánh / PR / chi phí — dashboard đọc để nối lượt ↔ PR và tính ngân sách tháng
        open(os.path.join(ROOT, "evals/raw/_runs.jsonl"), "a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
    cur = T.get(tid)
    if "ai-review" not in cur.get("labels", []):
        T.set_label(tid, "ai-review", note=f"orchestrator: agent kết thúc (turns={rec['num_turns']}, cost={rec['cost_usd']}); chưa tự set_label — kiểm tra đầu ra")
    pg_insert(rec); return rec

def _push_and_pr(rec, t, tid, key, agent, branch, d):
    """Commit, push nhánh agent, mở PR (dev-fe, dev-be, devops), gắn ai-review; ghi nhánh / PR vào rec."""
    if branch:
        rec["branch"] = branch
        subprocess.run(["git", "add", "-A"], cwd=THEME, check=False)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=THEME).returncode != 0
        if staged:
            subprocess.run(["git", *AGENT_GIT, "commit", "-q", "-m", f"ai({agent}): {key} {t['title']}\n\nAgent-Version: {rec['agent_version']}\nSession: {rec['session_id']}"], cwd=THEME, check=False)
            p = subprocess.run(["git", *AGENT_GIT, "push", "-q", "-u", "origin", branch], cwd=THEME, capture_output=True, text=True)
            rec["pushed"] = p.returncode == 0
            if p.returncode != 0: print(f"push {branch} lỗi: {p.stderr[-300:]}")
            link = f"branch {branch}"
            if rec.get("pushed") and agent in ("dev-fe", "dev-be", "devops"):
                pr = subprocess.run(["gh", "pr", "create", "-B", "develop", "-H", branch, "-t", f"{key}: {t['title'][:200]}",
                                     "-b", f"Ticket {key}. Agent {rec['agent_version']}, {rec['num_turns']} turns, ~{rec['cost_usd']} USD.\n\n{rec['result'][:3000]}"],
                                    cwd=THEME, capture_output=True, text=True, env=AGENT_GH_ENV)
                if pr.returncode == 0: link = pr.stdout.strip().splitlines()[-1]; rec["pr"] = link
                else: print(f"tạo PR lỗi: {pr.stderr[-300:]}")
            T.set_label(tid, "ai-review", link=link, note=f"orchestrator: đầu ra {link}")
        subprocess.run(["git", "checkout", "-q", "develop"], cwd=THEME, check=False)
        json.dump(rec, open(os.path.join(d, f"{key}.run.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

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

def role_of(agent):
    """(role owner, ngày duyệt) của agent: project.json đè bởi giá trị CTO sửa trên dashboard."""
    try:
        import ticket_local as L
        rows = next(p for p in json.load(open(os.path.join(ROOT, "ops/dashboard/project.json"), encoding="utf-8"))["pages"] if p["id"] == "roles")["rows"]
        ov = L.get_roles()
        for r in rows:
            if len(r) > 3 and r[3] == agent: o = ov.get(r[0], {}); return o.get("owner", r[1]), o.get("day", r[2])
    except Exception: pass
    return agent, ""

def remind_and_budget():
    today = datetime.date.today()
    for t in T.list(label="ai-review"):
        full = T.get(t["id"]); last = max((c["at"] for c in full.get("comments", [])), default=full.get("created_at", str(today)))
        if (today - datetime.date.fromisoformat(last[:10])).days >= CFG["review_overdue_days"]:
            owner, day = role_of(t["agent"])
            print(f"NHẮC: {t['id']} ở ai-review quá {CFG['review_overdue_days']} ngày — role owner {owner}{f' (duyệt {day})' if day else ''}, agent {t['agent']}")
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

def current_sprint():
    """Tên sprint đang chạy theo lịch trong ops/dashboard/project.json (scrum.sprints)."""
    try:
        d = datetime.date.today().isoformat()
        return next((x["name"] for x in json.load(open(os.path.join(ROOT, "ops/dashboard/project.json"), encoding="utf-8"))["scrum"]["sprints"]
                     if x["start"] <= d <= x["end"]), None)
    except Exception: return None

def pick(only=None):
    """Ticket ai-draft đủ điều kiện chạy: sprint hiện tại trước, rồi theo thứ tự key. Bỏ câu hỏi [Q] (cho người trả lời)."""
    ready = []
    for t in T.list(label="ai-draft"):
        full = T.get(t["id"])
        if only and full.get("key") != only: continue
        if (full.get("status") or "").lower() in ("closed", "đã đóng", "cancelled"): continue
        if not full.get("agent") or (full.get("title") or "").startswith("[Q]"): continue
        if not full.get("task_type"):
            # Chỉ dev-fe/dev-be mới suy task_type từ side; agent khác thiếu task_type thì bỏ qua để CTO đặt (ES1-T34, ES1-T41)
            if full.get("agent") in ("dev-fe", "dev-be") and full.get("side") in SIDE_TYPE: full["task_type"] = SIDE_TYPE[full["side"]]
            else: print(f"bỏ qua {full.get('key')}: {full.get('agent')} thiếu task_type (đặt một trong {RACI.get(full.get('agent'), [])})"); continue
        bl = blockers_open(full)
        if bl: print(f"chờ {full.get('key')}: bị chặn bởi {', '.join(bl)}"); continue
        ready.append(full)
    cur = current_sprint()   # ticket CTO đã đưa vào sprint hiện tại (trang Kế hoạch sprint) chạy trước, rồi theo key
    return sorted(ready, key=lambda x: (0 if cur and x.get("sprint") == cur else 1, int(re.sub(r"\D", "", x.get("key") or "0") or 0)))

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
