"""Hạn mức gói Claude (Pro/Max) mà agent dùng chung với CTO.
Gói thuê bao không tính tiền theo token: chi phí thật cố định mỗi tháng (plan_usd_month); giới hạn là hạn mức phiên 5 giờ và hạn mức tuần
Claude tự đo (%). total_cost_usd Claude Code báo trong mỗi lượt chỉ là quy đổi theo giá API — không phải hoá đơn.

- evals/raw/_plan_usage.json: % hạn mức đọc bằng `claude -p /usage` (usage_report.rate_limits: kind session / weekly_all / weekly_scoped).
- evals/raw/_plan_event.json: sự kiện hạn mức của lượt agent gần nhất (rate_limit_event, "You've hit your ... limit").
Dashboard và Orchestrator cùng đọc; Orchestrator dừng giao việc khi hết phiên 5 giờ, tuần ≥ budget_stop_pct, hoặc token agent 7 ngày chạm token_budget_week.
Chạy tay: python3 orchestrator/plan_usage.py [--refresh]"""
import os, json, subprocess, datetime, time, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RAW = os.path.join(ROOT, "evals", "raw")
USAGE, EVENT, RUNS = os.path.join(RAW, "_plan_usage.json"), os.path.join(RAW, "_plan_event.json"), os.path.join(RAW, "_runs.jsonl")
BACKFILL = os.path.join(RAW, "_token_backfill.json")   # token lượt cũ (trước 04/11 Orchestrator chưa ghi) tính lại từ transcript Claude Code
KIND = {"session": "phiên 5 giờ", "weekly_all": "tuần · mọi model", "weekly_scoped": "tuần"}


def _rd(p):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return {}

def _wr(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, p)

def now_iso(): return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

def when(iso):
    """'2026-11-10T07:00:00+07:00' → 'T2 10/11 07:00' (giờ máy)."""
    try: t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
    except Exception: return str(iso or "?")
    return f"{['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'][t.weekday()]} {t:%d/%m %H:%M}"

def name_of(x): return f"{KIND.get(x.get('kind'), x.get('kind'))}{' ' + x['label'] if x.get('label') else ''}"

def gone(x):
    """Đã qua giờ reset → % đọc được không còn đúng (chờ lần đọc sau)."""
    try: return datetime.datetime.fromisoformat(str(x.get("resets_at")).replace("Z", "+00:00")) <= datetime.datetime.now().astimezone()
    except Exception: return False

def pct(x): return 0.0 if gone(x) else float(x.get("percent") or 0)

def age_min(d):
    try: return (datetime.datetime.now().astimezone() - datetime.datetime.fromisoformat(d["at"])).total_seconds() / 60
    except Exception: return None

def load(): return _rd(USAGE)
def load_event(): return _rd(EVENT)


def fetch(claude_bin="claude", timeout=90):
    """`claude -p /usage` → usage_report.rate_limits (Claude Code có SDKUsageReport). Gọi thưa: endpoint usage có giới hạn tần suất."""
    d = {"at": now_iso(), "source": "claude -p /usage"}
    try:
        p = subprocess.run([claude_bin, "-p", "/usage", "--output-format", "stream-json", "--verbose"], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        d["error"] = f"không chạy được {claude_bin}: {e}"[:300]; return d
    rep = None
    for line in (p.stdout or "").splitlines():
        try: ev = json.loads(line)
        except Exception: continue
        r = ev.get("usage_report") or (ev.get("message") or {}).get("usage_report") if isinstance(ev, dict) else None
        if r: rep = r
    rl = (rep or {}).get("rate_limits")
    if not rl:
        d["error"] = ("Claude Code chưa trả hạn mức gói dạng JSON (usage_report) — cập nhật Claude Code, hoặc phiên đăng nhập thiếu quyền user:profile"
                      if p.returncode == 0 else f"claude -p /usage lỗi (mã {p.returncode}): {(p.stderr or '')[-200:]}")
        return d
    lab = lambda s: (((s or {}).get("model") or {}).get("display_name") or ((s or {}).get("surface") or {}).get("display_name"))
    d["limits"] = [{"kind": x.get("kind"), "group": x.get("group"), "percent": x.get("percent"), "resets_at": x.get("resets_at"),
                    "label": lab(x.get("scope")), "severity": x.get("severity"), "active": x.get("is_active")} for x in rl.get("limits") or []]
    eu = rl.get("extra_usage")
    if eu: d["extra_usage"] = {k: eu.get(k) for k in ("is_enabled", "monthly_limit", "used_credits", "utilization", "currency")}
    return d


def refresh(claude_bin="claude", min_age_min=10, force=False):
    """Đọc lại nếu số cũ hơn min_age_min phút; lỗi thì giữ số đọc được lần trước kèm lỗi."""
    cur = load(); a = age_min(cur)
    if not force and cur and a is not None and a < min_age_min: return cur
    d = fetch(claude_bin)
    if d.get("error") and cur.get("limits"): d = {**cur, "error": d["error"], "error_at": d["at"]}
    _wr(USAGE, d); return d


def record_event(rec):
    """Orchestrator gọi sau mỗi lượt: lưu rate_limit_event / chạm hạn mức để dashboard và lượt sau biết."""
    if not rec.get("rate_limit") and not rec.get("limit_hit"): return
    rl = rec.get("rate_limit") or {}; lim = rec.get("limit_hit") or {}
    ts = rl.get("resetsAt") or lim.get("resets_ts")
    _wr(EVENT, {"at": now_iso(), "ticket": rec.get("ticket"), "agent": rec.get("agent"), "status": rl.get("status"), "utilization": rl.get("utilization"),
                "resets_ts": ts, "limit_hit": lim or None})


LIMIT_RE = re.compile(r"(?:you'?ve )?hit your (\w+) limit(?:[^\n]*?resets ([^\n·]+))?", re.I)

def limit_of(out):
    """Lượt bị chặn vì hạn mức gói? → {kind, text, resets_ts}. Nguồn: rate_limit_event status rejected, hoặc câu "You've hit your ... limit"."""
    rl = out.get("rate_limit") or {}
    m = LIMIT_RE.search(f"{out.get('result') or ''}\n{out.get('stderr') or ''}")
    if rl.get("status") != "rejected" and not m: return None
    return {"kind": (m.group(1).lower() if m else "plan"), "text": (m.group(0).strip()[:160] if m else "rate_limit_event rejected"),
            "resets_ts": rl.get("resetsAt") or int(time.time()) + 3600}   # không rõ giờ reset: thử lại sau 1 giờ


def usage_of(out):
    """Token của lượt theo modelUsage (mọi model, kể cả subagent): input, output, cache ghi, cache đọc.
    total = input + output + cache ghi — cache đọc tính riêng (rẻ hơn nhiều, gần như mọi lượt đều đọc lại ngữ cảnh)."""
    mu = out.get("modelUsage") or {}
    if mu:
        g = lambda k: sum(int((v or {}).get(k) or 0) for v in mu.values())
        u = {"input": g("inputTokens"), "output": g("outputTokens"), "cache_write": g("cacheCreationInputTokens"), "cache_read": g("cacheReadInputTokens")}
    else:
        x = out.get("usage") or {}
        u = {"input": int(x.get("input_tokens") or 0), "output": int(x.get("output_tokens") or 0),
             "cache_write": int(x.get("cache_creation_input_tokens") or 0), "cache_read": int(x.get("cache_read_input_tokens") or 0)}
    u["total"] = u["input"] + u["output"] + u["cache_write"]
    return u if any(u.values()) else None


def usage_from_transcripts(paths):
    """Cộng token từ transcript Claude Code (~/.claude/projects/<thư mục>/<session>.jsonl, kèm subagents/*.jsonl).
    Mỗi tin nhắn assistant ghi lặp theo từng khối nội dung với cùng message.id → gộp theo id, lấy số lớn nhất."""
    per = {}
    for f in paths:
        try: fh = open(f, encoding="utf-8")
        except Exception: continue
        with fh:
            for i, line in enumerate(fh):
                if '"usage"' not in line: continue
                try: ev = json.loads(line)
                except Exception: continue
                m = ev.get("message") if isinstance(ev, dict) else None
                if ev.get("type") != "assistant" or not isinstance(m, dict) or not isinstance(m.get("usage"), dict): continue
                u, k = m["usage"], f"{f}:{m.get('id') or ev.get('uuid') or i}"
                cur = per.setdefault(k, [0, 0, 0, 0])
                for j, key in enumerate(("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")):
                    cur[j] = max(cur[j], int(u.get(key) or 0))
    if not per: return None
    t = [sum(v[j] for v in per.values()) for j in range(4)]
    return {"input": t[0], "output": t[1], "cache_write": t[2], "cache_read": t[3], "total": t[0] + t[1] + t[2], "src": "transcript", "messages": len(per)}


def backfill(projects_dir=None, force=False):
    """Bù token cho lượt chưa có usage (Orchestrator trước 04/11 chỉ ghi output_tokens) bằng transcript theo session_id.
    Kết quả lưu evals/raw/_token_backfill.json {session_id: usage}; chỉ đọc lại transcript khi file đổi. Trả số lượt mới bù được."""
    import glob
    base = projects_dir or os.path.expanduser("~/.claude/projects")
    cache = _rd(BACKFILL) if not force else {}; need, hint = {}, {}
    if not os.path.exists(RUNS): return 0
    for l in open(RUNS, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        sid = r.get("session_id")
        if not sid: continue
        if r.get("transcript"): hint[sid] = r["transcript"]   # dòng do hook Stop của theme ghi: có đường dẫn transcript
        if r.get("started_at") and not r.get("usage"): need[sid] = True
    n = 0
    for sid in need:
        main = [p for p in [hint.get(sid)] if p and os.path.exists(p)] or glob.glob(os.path.join(base, "*", f"{sid}.jsonl"))
        if not main: continue
        files = main + glob.glob(os.path.join(os.path.splitext(main[0])[0], "subagents", "*.jsonl"))
        sig = [[f, os.path.getmtime(f), os.path.getsize(f)] for f in files]
        if (cache.get(sid) or {}).get("sig") == sig: continue
        u = usage_from_transcripts(files)
        if u: cache[sid] = {**u, "sig": sig}; n += 1
    if n or force: _wr(BACKFILL, cache)
    return n


def load_backfill(): return _rd(BACKFILL)


def tokens_7d():
    """Token agent 7 ngày gần nhất (lượt có usage; lượt cũ lấy số bù từ transcript)."""
    since, n, bf = datetime.datetime.now() - datetime.timedelta(days=7), 0, None
    if os.path.exists(RUNS):
        for l in open(RUNS, encoding="utf-8"):
            try: r = json.loads(l)
            except Exception: continue
            try: st = datetime.datetime.fromisoformat((r.get("started_at") or "")[:19])
            except Exception: continue
            if st < since: continue
            u = r.get("usage")
            if not u and r.get("session_id"): bf = bf if bf is not None else load_backfill(); u = bf.get(r["session_id"])
            if u: n += int(u.get("total") or 0)
    return n


def check(cfg):
    """(dừng: str | None, cảnh báo: [str], dòng tóm tắt: str) cho Orchestrator trước mỗi lượt."""
    U, E = load(), load_event(); warn, stop_pct, cap = cfg.get("budget_warn_pct", 80), cfg.get("budget_stop_pct", 90), int(cfg.get("token_budget_week") or 0)
    L = U.get("limits") or []; a = age_min(U); fresh = bool(L) and a is not None and a <= 180
    sess = next((x for x in L if x.get("kind") == "session"), None); week = next((x for x in L if x.get("kind") == "weekly_all"), None)
    stop, warns, parts = None, [], []
    if fresh:
        for x in L: parts.append(f"{name_of(x)} " + ("đã reset" if gone(x) else f"{pct(x):.0f}%"))
        if sess and pct(sess) >= 100: stop = f"hết hạn mức phiên 5 giờ — reset {when(sess.get('resets_at'))}"
        if week and pct(week) >= stop_pct: stop = stop or f"hạn mức tuần {pct(week):.0f}% ≥ {stop_pct}% (chừa phần cho CTO) — reset {when(week.get('resets_at'))}"
        for x in L:
            if pct(x) >= warn: warns.append(f"{name_of(x)} {pct(x):.0f}% ≥ {warn}% — reset {when(x.get('resets_at'))}")
    else:
        parts.append("chưa đọc được hạn mức gói" + (f" ({U.get('error')})" if U.get("error") else ""))
    lim = E.get("limit_hit"); ev_newer = not U.get("at") or (E.get("at") or "") > (U.get("at") or "")
    if lim and ev_newer and (E.get("resets_ts") or 0) > time.time():
        stop = stop or f"lượt {E.get('ticket')} chạm hạn mức ({lim.get('kind')}) — chờ reset {datetime.datetime.fromtimestamp(E['resets_ts']).strftime('%d/%m %H:%M')}"
    tok = tokens_7d(); parts.append(f"token agent 7 ngày {tok:,}" + (f" / {cap:,}" if cap else ""))
    if cap and tok >= cap: stop = stop or f"token agent 7 ngày {tok:,} chạm trần token_budget_week {cap:,}"
    elif cap and tok >= cap * warn / 100: warns.append(f"token agent 7 ngày {tok * 100 / cap:.0f}% trần")
    return stop, warns, " · ".join(parts)


if __name__ == "__main__":
    import sys
    try:
        import yaml; cfg = yaml.safe_load(open(os.path.join(ROOT, "orchestrator", "config.yaml"), encoding="utf-8"))
    except Exception: cfg = {}
    if "--refresh" in sys.argv: refresh(cfg.get("claude_bin", "claude"), force=True)
    stop, warns, line = check(cfg)
    print(f"{cfg.get('plan_name', 'Gói Claude')}: {line}")
    for w in warns: print("CẢNH BÁO:", w)
    if stop: print("DỪNG:", stop)
