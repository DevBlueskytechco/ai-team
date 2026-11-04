#!/usr/bin/env python3
"""Hook PreToolUse (Bash, Monitor) của Claude Code trong ai-team — chặn cứng việc CTO đã cấm, để bỏ được các rule "ask" (bắt bấm Yes/No kể cả ở auto mode).

Chặn (exit 2, lý do gửi lại cho Claude để tự đổi cách làm, không hỏi CTO):
  - git push: force (-f, --force*, +refspec), xoá nhánh (--delete, :nhánh), --mirror/--all/--tags, đích develop/main/master,
    không ghi rõ nhánh đích, hoặc đích chỉ là biến ($BR).
  - gh pr merge, gh pr review --approve, gh api .../merge hoặc review APPROVE — merge chỉ qua ops/merge_pr.sh khi CTO đã chốt.
  - shopify theme publish/delete, --live/--allow-live, store khác hoa-qua-nhap-khau.
  - gh secret, đọc file .env, đụng sổ duyệt (data/approvals.jsonl, ops/approvals.py record), ops/hooks/, sửa .claude/settings*.json.
Không chặn được mọi cách viết (deny rule, sandbox mới là ranh giới cứng) — đây là lớp chặn cách Claude thường viết lệnh.
Thử: echo '{"tool_input":{"command":"git push origin develop"}}' | python3 ops/hooks/guard_bash.py; echo $?"""
import sys, json, re, shlex

PROTECTED = {"develop", "main", "master"}
AGENT_STORE = "hoa-qua-nhap-khau"
SEP = re.compile(r"\|\||&&|;|\||&|\n|\$\(|`|\(|\)")


def segments(cmd):
    """Tách lệnh ghép thành từng lệnh con; chuỗi trong nháy (bash -c "...") cũng được tách lại."""
    out, stack = [], [cmd]
    while stack:
        c = stack.pop()
        for part in SEP.split(c):
            part = part.strip()
            if not part: continue
            try: toks = shlex.split(part, posix=True)
            except ValueError: toks = part.split()
            while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]): toks.pop(0)   # FOO=bar lệnh
            if toks and toks[0] in ("sudo", "env", "command", "nohup", "time", "exec"): toks.pop(0)
            if not toks: continue
            out.append(toks)
            for t in toks[1:]:
                if " " in t and re.search(r"\b(git|gh|shopify|cat|python3?)\b", t): stack.append(t)   # bash -c "git push ..."
    return out


def git_push(t):
    """t = token sau 'git' (đã bỏ -C dir, -c k=v)."""
    i = 0
    while i < len(t) and t[i].startswith("-"):
        i += 2 if t[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if i >= len(t) or t[i] != "push": return None
    a, flags, pos, j = t[i + 1:], [], [], 0
    while j < len(a):   # tuỳ chọn có giá trị (-o x, --repo x) không tính là remote/refspec
        x = a[j]
        if x.startswith("-"):
            flags.append(x); j += 2 if x in ("-o", "--push-option", "--repo", "--receive-pack", "--exec") else 1
        else: pos.append(x); j += 1
    for f in flags:
        if f in ("-f", "--force", "--force-if-includes") or f.startswith("--force-with-lease") or (re.match(r"^-[a-zA-Z]+$", f) and "f" in f[1:]):
            return "force push bị cấm (quy tắc CTO). Đẩy commit mới lên nhánh, không viết lại lịch sử."
        if f in ("-d", "--delete", "--mirror", "--all", "--tags", "--prune"):
            return f"git push {f} bị cấm — không xoá/đẩy hàng loạt nhánh, tag."
    refs = pos[1:]   # pos[0] = remote
    if not refs:
        return ("git push phải ghi rõ remote và nhánh đích, vd `git push origin HEAD:feature/ai-ES1-T67` hoặc `ops/push_branch.sh <nhánh>` "
                "(hook không biết nhánh hiện tại để kiểm develop/main).")
    for r in refs:
        if r.startswith("+"): return "refspec có + là force push — bị cấm."
        src, _, dst = r.partition(":")
        if _ and not src: return f"`{r}` là xoá nhánh trên remote — bị cấm."
        dst = (dst if _ else src).replace("refs/heads/", "")
        if dst in PROTECTED:
            return f"Không push thẳng {dst} (quy tắc CTO) — đẩy lên nhánh feature/ai-*, fix/*, patch/* rồi mở PR."
        if dst == "HEAD" or dst.startswith("$") or dst.startswith("@"):
            return f"Nhánh đích `{dst}` không xác định được — ghi tên nhánh cụ thể, vd HEAD:feature/ai-ES1-T67."
    return None


def check(cmd):
    low = cmd.lower()
    # sổ duyệt, hook, cấu hình quyền: chỉ CTO đổi (patch / dashboard)
    if "approvals.jsonl" in low or re.search(r"approvals(\.py)?\b.*\b(record|cancel)\b|import\s+approvals|from\s+approvals", low) or "/api/approve" in low:
        return ("Không đụng trực tiếp sổ duyệt — xem bằng `python3 ops/approvals.py list`; chỉ CTO ghi (dashboard → Việc chờ tôi → Chốt merge, "
                "hoặc CTO gõ /merge-pr). Chưa chốt thì để việc ở Việc chờ tôi và làm việc khác.")
    if re.search(r"(python3?|bash|sh|zsh|node)\s+[^;&|]*ops/hooks/|>\s*\S*ops/hooks/|\b(sed\s+-i|tee|mv|cp|rm|chmod|ln)\b[^;&|]*ops/hooks/", low):
        return "Không chạy/sửa hook (ops/hooks/) — CTO đổi bằng patch."
    if ".claude/settings" in low and re.search(r"sed\s+-i|>|\btee\b|\bmv\b|\bcp\b|\brm\b|python|node|perl|\bjq\b.*>", low):
        return "Không sửa .claude/settings*.json (quyền của Claude) — CTO đổi bằng patch."
    for t in segments(cmd):
        p = t[0].rsplit("/", 1)[-1]
        if p == "git":
            why = git_push(t[1:])
            if why: return why
        elif p == "gh":
            s = " ".join(t[1:])
            if re.match(r"pr\s+merge\b", s): return "Merge chỉ qua `ops/merge_pr.sh <PR>` khi CTO đã chốt (python3 ops/approvals.py list)."
            if re.match(r"pr\s+review\b", s) and re.search(r"(^|\s)(--approve|-a)(\s|$)", s): return "Approve PR chỉ qua ops/merge_pr.sh khi CTO đã chốt."
            if re.match(r"api\b", s) and (re.search(r"pulls/\d+/merge", s) or re.search(r"event=?\s*\"?APPROVE", s, re.I)):
                return "Merge/approve qua gh api bị cấm — dùng ops/merge_pr.sh khi CTO đã chốt."
            if re.match(r"secret\b", s): return "gh secret bị cấm."
        elif p == "shopify":
            s = " ".join(t[1:])
            if re.search(r"\btheme\s+(publish|delete)\b", s): return "Không publish/xoá theme (quy tắc CTO)."
            if re.search(r"(^|\s)--(live|allow-live)\b", s): return "Không đụng theme live (quy tắc CTO)."
            m = re.search(r"(?:--store[=\s]|-s\s)(\S+)", s)
            if m and AGENT_STORE not in m.group(1): return f"Agent chỉ push store {AGENT_STORE} (quy tắc CTO), không phải {m.group(1)}."
        elif p in ("cat", "less", "more", "head", "tail", "bat", "source", ".", "grep", "sed", "awk", "cp", "base64", "xxd", "strings"):
            if any(re.search(r"(^|/)\.env(\.[\w-]+)?$", x) and not x.endswith(".example") for x in t[1:]):
                return "Không đọc/in/chép .env (quy tắc CTO). Biến môi trường nạp qua `source ops/env.sh`."
    return None


def main():
    try: ev = json.load(sys.stdin)
    except Exception: return 0
    cmd = ((ev.get("tool_input") or {}).get("command") or "") if isinstance(ev, dict) else ""
    if not cmd: return 0
    why = check(cmd)
    if why:
        print(f"Bị chặn bởi ops/hooks/guard_bash.py: {why}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
