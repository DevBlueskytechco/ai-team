#!/usr/bin/env python3
"""Kiến thức agent do CTO nạp + đọc kiến thức hiện có của agent (định nghĩa, skill, quy tắc, bộ nhớ agent tự ghi).

Kho kiến thức CTO: ai-team/knowledge/<agent>/<id>.md (và knowledge/_chung/ cho mọi agent), mỗi file có frontmatter:
    ---
    title: Badge sale tính theo variant đang chọn
    kind: kinh-nghiem        # kinh-nghiem | quy-tac | tai-lieu | checklist | bai-hoc
    priority: cao            # cao | thuong
    status: active           # active | off
    source: ES1-T56 (CTO chấm sửa nhẹ)
    by: cto
    created: 2026-11-04T10:00:00
    updated: 2026-11-04T10:00:00
    ---
    nội dung markdown
Orchestrator nối các mục active vào prompt của agent mỗi lượt (prompt_for) và tính vào agent_version (digest).
Agent không ghi được thư mục này (scope-guard chỉ cho ghi trong theme-efitco). Lưu trữ = chuyển vào _archive/, không xoá.

CLI:
  python3 orchestrator/knowledge.py list [agent]          danh sách mục kiến thức CTO nạp
  python3 orchestrator/knowledge.py prompt <agent>        đúng phần agent sẽ nhận ở lượt tới
  python3 orchestrator/knowledge.py add <agent> "<tiêu đề>" --file note.md [--kind kinh-nghiem] [--priority cao] [--source ES1-T56]
  python3 orchestrator/knowledge.py off|on|archive <agent> <id>
"""
import os, re, sys, json, hashlib, datetime, subprocess, unicodedata, shutil

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
KDIR = os.path.join(ROOT, "knowledge")
THEME = os.environ.get("THEME") or os.path.abspath(os.path.join(ROOT, "..", "theme-efitco"))
AGENTS = ["po", "ba", "designer", "techlead", "dev-fe", "dev-be", "qa", "devops", "writer", "gate-reviewer"]
SHARED = "_chung"
KINDS = {"kinh-nghiem": "Kinh nghiệm", "quy-tac": "Quy tắc", "tai-lieu": "Tài liệu", "checklist": "Checklist", "bai-hoc": "Bài học"}
PRIOS = ("cao", "thuong")
LIMIT = 12000          # ký tự tối đa nối vào prompt mỗi lượt (chung + riêng agent)
BODY_MAX = 20000


def now(): return datetime.datetime.now().isoformat(timespec="seconds")

def _ok_agent(agent):
    if agent not in AGENTS and agent != SHARED: raise ValueError(f"không có agent {agent}")
    return agent

def slug(text):
    t = unicodedata.normalize("NFKD", str(text).replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:48] or "muc")

def _parse(path):
    txt = open(path, encoding="utf-8").read()
    meta, body = {}, txt
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", txt, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if k.strip(): meta[k.strip()] = v.split("#", 1)[0].strip() if k.strip() in ("kind", "priority", "status") else v.strip()
    return meta, body.strip()

def _dump(meta, body):
    keys = ("title", "kind", "priority", "status", "source", "by", "created", "updated")
    head = "\n".join(f"{k}: {str(meta.get(k, '')).replace(chr(10), ' ')}" for k in keys if meta.get(k) not in (None, ""))
    return f"---\n{head}\n---\n{body.strip()}\n"

def items(agent, include_off=True):
    """Mục kiến thức CTO nạp của agent (hoặc _chung), mới cập nhật trước."""
    d = os.path.join(KDIR, _ok_agent(agent)); out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith(".md"): continue
        meta, body = _parse(os.path.join(d, f))
        it = {"id": f[:-3], "agent": agent, "title": meta.get("title") or f[:-3], "kind": meta.get("kind") if meta.get("kind") in KINDS else "kinh-nghiem",
              "priority": meta.get("priority") if meta.get("priority") in PRIOS else "thuong", "status": "off" if meta.get("status") == "off" else "active",
              "source": meta.get("source", ""), "by": meta.get("by", ""), "created": meta.get("created", ""), "updated": meta.get("updated", ""), "body": body}
        if include_off or it["status"] == "active": out.append(it)
    out.sort(key=lambda x: x["updated"] or x["created"], reverse=True)
    out.sort(key=lambda x: 0 if x["priority"] == "cao" else 1)   # sort ổn định: ưu tiên cao trước, trong nhóm mới nhất trước
    return out

def save(agent, title, body, kind="kinh-nghiem", priority="thuong", status="active", source="", by="cto", id=None):
    _ok_agent(agent)
    title = str(title or "").strip(); body = str(body or "").strip()
    if not title or len(title) > 120: raise ValueError("tiêu đề 1–120 ký tự")
    if not body: raise ValueError("nội dung trống")
    if len(body) > BODY_MAX: raise ValueError(f"nội dung quá {BODY_MAX} ký tự — tách thành nhiều mục")
    if kind not in KINDS: raise ValueError("loại không hợp lệ")
    if priority not in PRIOS: raise ValueError("ưu tiên không hợp lệ")
    if status not in ("active", "off"): raise ValueError("trạng thái không hợp lệ")
    d = os.path.join(KDIR, agent); os.makedirs(d, exist_ok=True)
    created = now()
    if id:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,80}", id): raise ValueError("id không hợp lệ")
        p = os.path.join(d, id + ".md")
        if not os.path.exists(p): raise ValueError(f"không có mục {id}")
        created = _parse(p)[0].get("created") or created
    else:
        base = f"{datetime.date.today().strftime('%Y%m%d')}-{slug(title)}"; id = base; n = 2
        while os.path.exists(os.path.join(d, id + ".md")): id = f"{base}-{n}"; n += 1
        p = os.path.join(d, id + ".md")
    meta = {"title": title, "kind": kind, "priority": priority, "status": status, "source": str(source or "").strip()[:160], "by": by, "created": created, "updated": now()}
    tmp = p + ".tmp"; open(tmp, "w", encoding="utf-8").write(_dump(meta, body)); os.replace(tmp, p)
    return id

def set_status(agent, id, status, by="cto"):
    it = next((x for x in items(agent) if x["id"] == id), None)
    if not it: raise ValueError(f"không có mục {id}")
    return save(agent, it["title"], it["body"], it["kind"], it["priority"], status, it["source"], by, id)

def archive(agent, id):
    """Không xoá: chuyển vào knowledge/<agent>/_archive/ (khôi phục bằng cách chuyển lại)."""
    _ok_agent(agent)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,80}", id or ""): raise ValueError("id không hợp lệ")
    src = os.path.join(KDIR, agent, id + ".md")
    if not os.path.exists(src): raise ValueError(f"không có mục {id}")
    dst_dir = os.path.join(KDIR, agent, "_archive"); os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, f"{id}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.md")
    shutil.move(src, dst)
    return os.path.relpath(dst, ROOT)

def archived_count(agent):
    d = os.path.join(KDIR, agent, "_archive")
    return len([f for f in os.listdir(d) if f.endswith(".md")]) if os.path.isdir(d) else 0

def prompt_for(agent):
    """Phần nối vào prompt agent: mục active của _chung rồi của agent; ưu tiên cao trước; cắt ở LIMIT ký tự.
    Trả (text, dùng, bỏ) — text rỗng nếu không có mục nào."""
    act = [x for x in items(SHARED, False)] + ([x for x in items(agent, False)] if agent != SHARED else [])
    act.sort(key=lambda x: 0 if x["priority"] == "cao" else 1)
    head = (f"\n\n## Kiến thức CTO nạp cho {agent} (ai-team/knowledge) — áp dụng khi liên quan; mâu thuẫn với AGENTS.md/ADR thì theo AGENTS.md/ADR và ghi KHÔNG CHẮC\n")
    parts, used, skipped, size = [], [], [], len(head)
    for x in act:
        blk = f"\n### {x['title']} [{KINDS[x['kind']]}{' · chung' if x['agent'] == SHARED else ''}]\n{x['body']}\n"
        if size + len(blk) > LIMIT: skipped.append(x); continue
        parts.append(blk); used.append(x); size += len(blk)
    if not used: return "", [], skipped
    if skipped: parts.append(f"\n(Còn {len(skipped)} mục chưa nạp vì quá {LIMIT} ký tự.)\n")
    return head + "".join(parts), used, skipped

def digest(agent):
    """Băm nội dung kiến thức active (chung + riêng) — Orchestrator cộng vào agent_version để eval biết kiến thức đã đổi."""
    txt, _, _ = prompt_for(agent)
    return hashlib.sha256(txt.encode()).hexdigest()[:10] if txt else ""

# ---------- kiến thức hiện có trong theme-efitco (chỉ đọc) ----------
def _git(*a, timeout=10):
    r = subprocess.run(["git", "-C", THEME, *a], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError(r.stderr.strip()[:160])
    return r.stdout

def theme_ref():
    """Đọc định nghĩa/skill/quy tắc ở nhánh develop (không phụ thuộc nhánh feature đang checkout)."""
    for ref in ("origin/develop", "develop"):
        try: _git("rev-parse", "--verify", "-q", ref); return ref
        except Exception: pass
    return None

def _read_theme(rel, ref):
    if ref:
        try: return _git("show", f"{ref}:{rel}")
        except Exception: pass
    p = os.path.join(THEME, rel)
    return open(p, encoding="utf-8").read() if os.path.isfile(p) else None

def _list_theme(rel_dir, ref):
    if ref:
        try: return [l for l in _git("ls-tree", "-r", "--name-only", ref, "--", rel_dir).splitlines() if l]
        except Exception: pass
    base = os.path.join(THEME, rel_dir); out = []
    for dp, _, fs in os.walk(base) if os.path.isdir(base) else []:
        out += [os.path.relpath(os.path.join(dp, f), THEME) for f in fs]
    return sorted(out)

def _front(txt):
    meta, body, lists = {}, txt or "", {}
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", txt or "", re.S)
    if m:
        body = m.group(2); cur = None
        for line in m.group(1).splitlines():
            if re.match(r"^\s+-\s+", line) and cur: lists.setdefault(cur, []).append(line.strip()[2:].strip()); continue
            k, _, v = line.partition(":"); cur = k.strip()
            if cur: meta[cur] = v.strip()
    meta.update({k: v for k, v in lists.items()})
    return meta, body.strip()

def current(agent):
    """Kiến thức hiện có của agent: định nghĩa, skill, quy tắc chung, bộ nhớ agent tự ghi."""
    _ok_agent(agent)
    ref = theme_ref(); out = {"theme_ref": ref or "thư mục làm việc", "definition": None, "skills": [], "rules": [], "memory": []}
    if agent == SHARED: agent_txt = None
    else: agent_txt = _read_theme(f".claude/agents/{agent}.md", ref)
    if agent_txt:
        meta, body = _front(agent_txt)
        tools = meta.get("tools", ""); tools = tools if isinstance(tools, list) else [t.strip() for t in tools.split(",") if t.strip()]
        sk = meta.get("skills", []); sk = sk if isinstance(sk, list) else [s.strip() for s in str(sk).split(",") if s.strip()]
        out["definition"] = {"path": f".claude/agents/{agent}.md", "description": meta.get("description", ""), "model": meta.get("model", ""),
                             "max_turns": meta.get("maxTurns", ""), "memory": meta.get("memory", ""), "tools": tools, "skills": sk, "body": body, "chars": len(agent_txt)}
        for s in sk:
            txt = _read_theme(f".claude/skills/{s}/SKILL.md", ref)
            m2, b2 = _front(txt or "")
            out["skills"].append({"name": s, "found": txt is not None, "description": m2.get("description", ""), "body": b2, "chars": len(txt or "")})
    for rel in _list_theme(".claude/rules", ref):
        if rel.endswith(".md"):
            txt = _read_theme(rel, ref) or ""
            out["rules"].append({"name": os.path.basename(rel)[:-3], "path": rel, "body": txt.strip(), "chars": len(txt)})
    if agent != SHARED:   # bộ nhớ agent tự ghi: gitignored, chỉ có trên máy chạy agent
        mdir = os.path.join(THEME, ".claude", "agent-memory", agent)
        for dp, _, fs in os.walk(mdir) if os.path.isdir(mdir) else []:
            for f in sorted(fs):
                if not f.endswith((".md", ".txt")): continue
                p = os.path.join(dp, f)
                try: txt = open(p, encoding="utf-8").read()
                except Exception: continue
                out["memory"].append({"name": os.path.relpath(p, mdir), "body": txt[:BODY_MAX], "chars": len(txt),
                                      "updated": datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")})
    return out

def summary():
    """Số liệu cho bảng Vai trò / trang tổng quan Kiến thức."""
    ref = theme_ref(); res = {}
    for a in AGENTS + [SHARED]:
        its = items(a); txt, used, skipped = prompt_for(a)
        sk = []
        if a != SHARED:
            meta, _ = _front(_read_theme(f".claude/agents/{a}.md", ref) or "")
            sk = meta.get("skills", []); sk = sk if isinstance(sk, list) else []
        mdir = os.path.join(THEME, ".claude", "agent-memory", a)
        mem = sum(1 for _, _, fs in os.walk(mdir) for f in fs if f.endswith((".md", ".txt"))) if a != SHARED and os.path.isdir(mdir) else 0
        res[a] = {"cto_total": len(its), "cto_active": sum(1 for x in its if x["status"] == "active"), "prompt_chars": len(txt), "skipped": len(skipped),
                  "skills": len(sk), "memory": mem, "archived": archived_count(a), "updated": max((x["updated"] or x["created"] for x in its), default="")}
    return {"agents": res, "limit": LIMIT, "kinds": KINDS, "theme_ref": ref or "thư mục làm việc"}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Kiến thức agent do CTO nạp (ai-team/knowledge)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("list"); p.add_argument("agent", nargs="?")
    p = sp.add_parser("prompt"); p.add_argument("agent")
    p = sp.add_parser("add"); p.add_argument("agent"); p.add_argument("title"); p.add_argument("--file", required=True)
    p.add_argument("--kind", default="kinh-nghiem", choices=list(KINDS)); p.add_argument("--priority", default="thuong", choices=PRIOS); p.add_argument("--source", default="")
    for c in ("off", "on", "archive"):
        p = sp.add_parser(c); p.add_argument("agent"); p.add_argument("id")
    a = ap.parse_args()
    if a.cmd == "list":
        for ag in ([a.agent] if a.agent else AGENTS + [SHARED]):
            for x in items(ag): print(f"{ag:14} {x['status']:6} {x['priority']:6} {x['kind']:12} {x['id']:48} {x['title']}")
    elif a.cmd == "prompt":
        txt, used, skipped = prompt_for(a.agent); print(txt or f"(chưa có kiến thức active cho {a.agent})")
        print(f"\n-- {len(used)} mục, {len(txt)}/{LIMIT} ký tự" + (f", bỏ {len(skipped)} mục vì quá giới hạn" if skipped else ""), file=sys.stderr)
    elif a.cmd == "add":
        print(save(a.agent, a.title, open(a.file, encoding="utf-8").read(), a.kind, a.priority, "active", a.source, os.environ.get("TICKET_USER") or "cto"))
    elif a.cmd in ("off", "on"):
        print(set_status(a.agent, a.id, "off" if a.cmd == "off" else "active"))
    elif a.cmd == "archive":
        print(archive(a.agent, a.id))
