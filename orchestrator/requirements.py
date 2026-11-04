#!/usr/bin/env python3
"""Yêu cầu dự án: nạp từ ban giám đốc, quản lý sản phẩm, CTO, thay đổi của Shopify, khách hàng…

Kho: ai-team/requirements/REQ-0001.md (frontmatter + nội dung markdown); lưu trữ = chuyển vào requirements/_archive/, không xoá.
Vòng đời: moi → phan-tich (giao PO/BA/Tech Lead phân tích tác động bằng ticket) → ap-dung (CTO chốt) → xong (đã vào skill/kiến thức) | khong.
- Yêu cầu "ap-dung" được Orchestrator nối vào prompt của agent bị ảnh hưởng mỗi lượt (prompt_for) và cộng vào agent_version (digest).
- Ticket phân tích yêu cầu agent ghi drafts/<agent>/<key>/impact.md với mục "## Kiến thức cho <agent>: <tiêu đề>" và
  "## Sửa skill <tên>: <tóm tắt>" — dashboard đọc các mục này để CTO nạp vào kho kiến thức (knowledge.py) hoặc sửa skill bằng PR.

CLI:
  python3 orchestrator/requirements.py list                 danh sách yêu cầu
  python3 orchestrator/requirements.py prompt <agent>       phần yêu cầu agent sẽ nhận ở lượt tới
  python3 orchestrator/requirements.py status REQ-0001 ap-dung
"""
import os, re, sys, json, hashlib, datetime, shutil

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); import knowledge as KN
RDIR = os.path.join(ROOT, "requirements")
SOURCES = {"ban-giam-doc": "Ban giám đốc", "quan-ly-san-pham": "Quản lý sản phẩm", "cto": "CTO", "shopify": "Shopify thay đổi",
           "khach-hang": "Khách hàng / merchant", "khac": "Khác"}
STATUSES = {"moi": "Mới", "phan-tich": "Đang phân tích", "ap-dung": "Đang áp dụng", "xong": "Đã áp dụng", "khong": "Không áp dụng"}
PRIOS = {"cao": "Cao", "vua": "Vừa", "thap": "Thấp"}
# agent phân tích tác động → loại việc trong RACI (orchestrator/raci.yaml)
ANALYSTS = {"po": "change_request", "ba": "srs", "techlead": "adr"}
DEFAULT_ANALYST = {"ban-giam-doc": "po", "quan-ly-san-pham": "po", "cto": "techlead", "shopify": "techlead", "khach-hang": "po", "khac": "po"}
LIMIT = 6000          # ký tự yêu cầu nối vào prompt mỗi lượt
ONE_MAX = 2500        # mỗi yêu cầu tối đa trong prompt
BODY_MAX = 30000
KEYS = ("id", "title", "source", "from", "received", "due", "priority", "status", "agents", "stories", "link", "tickets", "by", "created", "updated", "history")


def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def _list(v): return [x.strip() for x in re.split(r"[,;\s]+", str(v or "")) if x.strip()]
def _okid(id):
    if not re.fullmatch(r"REQ-\d{4,6}", id or ""): raise ValueError("mã yêu cầu không hợp lệ")
    return id

def _parse(path):
    txt = open(path, encoding="utf-8").read(); meta, body = {}, txt
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", txt, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if k.strip(): meta[k.strip()] = v.strip()
    return meta, body.strip()

def _row(meta, body, fid):
    r = {k: meta.get(k, "") for k in KEYS}
    r["id"] = meta.get("id") or fid
    r["source"] = r["source"] if r["source"] in SOURCES else "khac"
    r["status"] = r["status"] if r["status"] in STATUSES else "moi"
    r["priority"] = r["priority"] if r["priority"] in PRIOS else "vua"
    r["agents"] = [a for a in _list(r["agents"]) if a in KN.AGENTS]
    r["stories"] = _list(r["stories"]); r["tickets"] = _list(r["tickets"])
    r["history"] = [h.strip() for h in (meta.get("history") or "").split(" | ") if h.strip()]
    r["body"] = body
    return r

def _dump(r):
    v = dict(r); v["agents"] = ", ".join(r.get("agents") or []); v["stories"] = ", ".join(r.get("stories") or [])
    v["tickets"] = ", ".join(r.get("tickets") or []); v["history"] = " | ".join(r.get("history") or [])
    head = "\n".join(f"{k}: {str(v.get(k, '')).replace(chr(10), ' ')}" for k in KEYS if v.get(k) not in (None, ""))
    return f"---\n{head}\n---\n{(r.get('body') or '').strip()}\n"

def _write(r):
    os.makedirs(RDIR, exist_ok=True); p = os.path.join(RDIR, r["id"] + ".md"); tmp = p + ".tmp"
    open(tmp, "w", encoding="utf-8").write(_dump(r)); os.replace(tmp, p)

def items():
    out = []
    for f in sorted(os.listdir(RDIR)) if os.path.isdir(RDIR) else []:
        if re.fullmatch(r"REQ-\d{4,6}\.md", f): out.append(_row(*_parse(os.path.join(RDIR, f)), f[:-3]))
    return sorted(out, key=lambda r: r["id"], reverse=True)

def get(id):
    p = os.path.join(RDIR, _okid(id) + ".md")
    if not os.path.exists(p): raise ValueError(f"không có {id}")
    return _row(*_parse(p), id)

def _next_id():
    nums = [int(m.group(1)) for d in (RDIR, os.path.join(RDIR, "_archive")) if os.path.isdir(d)
            for f in os.listdir(d) for m in [re.match(r"REQ-(\d+)", f)] if m]
    return f"REQ-{(max(nums) + 1 if nums else 1):04d}"

def save(d, by="cto"):
    """Tạo (không có id) hoặc sửa yêu cầu. d: title, source, from, received, due, priority, agents, stories, link, body."""
    title = str(d.get("title") or "").strip(); body = str(d.get("body") or "").strip()
    if not title or len(title) > 160: raise ValueError("tiêu đề 1–160 ký tự")
    if not body: raise ValueError("nội dung trống")
    if len(body) > BODY_MAX: raise ValueError(f"nội dung quá {BODY_MAX} ký tự — tách thành nhiều yêu cầu")
    src = d.get("source") or "khac"; pri = d.get("priority") or "vua"
    if src not in SOURCES: raise ValueError("nguồn không hợp lệ")
    if pri not in PRIOS: raise ValueError("ưu tiên không hợp lệ")
    for k in ("received", "due"):
        if d.get(k) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d[k])): raise ValueError(f"ngày {k} phải dạng YYYY-MM-DD")
    agents = [a for a in (d.get("agents") if isinstance(d.get("agents"), list) else _list(d.get("agents"))) if a in KN.AGENTS]
    if d.get("id"):
        r = get(d["id"])
    else:
        r = {"id": _next_id(), "status": "moi", "tickets": [], "history": [], "by": by, "created": now()}
        r["history"] = [f"{now()[:16]} {by}: nạp yêu cầu"]
    r.update({"title": title, "source": src, "from": str(d.get("from") or "").strip()[:120], "received": d.get("received") or datetime.date.today().isoformat(),
              "due": d.get("due") or "", "priority": pri, "agents": agents, "stories": _list(d.get("stories"))[:10],
              "link": str(d.get("link") or "").strip()[:300], "body": body, "updated": now()})
    _write(r); return r["id"]

def set_status(id, status, by="cto", note=""):
    if status not in STATUSES: raise ValueError("trạng thái không hợp lệ")
    r = get(id)
    if r["status"] != status:
        r["history"].append(f"{now()[:16]} {by}: {STATUSES[r['status']]} → {STATUSES[status]}{(' — ' + note) if note else ''}")
        r["status"] = status; r["updated"] = now(); _write(r)
    return id

def add_ticket(id, key, by="cto", agent=""):
    r = get(id)
    if key not in r["tickets"]: r["tickets"].append(key)
    r["history"].append(f"{now()[:16]} {by}: giao {agent} phân tích ({key})")
    if r["status"] == "moi": r["history"].append(f"{now()[:16]} {by}: Mới → Đang phân tích"); r["status"] = "phan-tich"
    r["updated"] = now(); _write(r); return id

def archive(id):
    src = os.path.join(RDIR, _okid(id) + ".md")
    if not os.path.exists(src): raise ValueError(f"không có {id}")
    d = os.path.join(RDIR, "_archive"); os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, f"{id}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.md"); shutil.move(src, dst)
    return os.path.relpath(dst, ROOT)

def analysis_ticket(r, agent):
    """Nội dung ticket giao agent phân tích tác động của yêu cầu (Orchestrator chạy như ticket thường)."""
    if agent not in ANALYSTS: raise ValueError("chỉ PO, BA, Tech Lead phân tích yêu cầu")
    title = f"{r['id']} phân tích tác động: {r['title']}"[:290]
    body = (f"Yêu cầu dự án {r['id']} — nguồn {SOURCES[r['source']]}{(' (' + r['from'] + ')') if r['from'] else ''}, nhận {r['received']}"
            f"{', hạn ' + r['due'] if r['due'] else ''}, ưu tiên {PRIOS[r['priority']]}.\n"
            f"Agent bị ảnh hưởng (CTO chọn): {', '.join(r['agents']) or 'chưa chọn — đề xuất'}. Story: {', '.join(r['stories']) or '—'}."
            f"{(' Link: ' + r['link']) if r['link'] else ''}\n\n## Nội dung yêu cầu\n{r['body']}\n\n"
            f"## Việc cần làm\nGhi drafts/{agent}/<key>/impact.md (key = mã ticket này), theo đúng các tiêu đề sau để dashboard đọc được:\n"
            f"1. `## Tóm tắt` — yêu cầu nói gì, áp dụng từ khi nào, có mâu thuẫn với AGENTS.md / ADR / SRS không.\n"
            f"2. `## Ảnh hưởng` — story, ticket, block, skill, agent bị ảnh hưởng.\n"
            f"3. Mỗi kiến thức đề xuất nạp cho một agent: `## Kiến thức cho <agent>: <tiêu đề ngắn>` rồi nội dung ngắn, cụ thể, agent làm theo được "
            f"(agent: {', '.join(KN.AGENTS)}, hoặc _chung cho mọi agent).\n"
            f"4. Mỗi skill cần sửa: `## Sửa skill <tên skill>: <tóm tắt>` rồi đoạn đề xuất thay đổi (không tự sửa .claude/ — CTO sửa bằng PR).\n"
            f"5. `## Ticket cần tạo` — mỗi dòng `- ` một việc: tên cụ thể, phía FE/BE (hoặc QA), `N point` ước lượng. Không tự tạo ticket; CTO tạo từ dashboard (gắn nhãn mã yêu cầu).\n"
            f"Thiếu thông tin thì tạo ticket câu hỏi cho CTO, ghi KHÔNG CHẮC ở đầu file và vẫn nộp.")
    return title, body

def proposals(r):
    """Đọc impact.md của các ticket phân tích (develop, hoặc nhánh feature/ai-<key> khi PR chưa merge)."""
    out = []
    for key in r["tickets"]:
        for agent in ANALYSTS:
            rel = f"drafts/{agent}/{key}/impact.md"; txt, ref_used = None, None
            for ref in ("origin/develop", "develop", f"origin/feature/ai-{key}", f"feature/ai-{key}"):
                try: txt = KN._git("show", f"{ref}:{rel}"); ref_used = ref; break
                except Exception: continue
            if txt is None: continue
            secs = re.split(r"^## ", "\n" + txt, flags=re.M)[1:]
            items = []
            for s in secs:
                head, _, body = s.partition("\n"); body = body.strip()
                m = re.match(r"Kiến thức cho\s+([a-z_-]+)\s*:\s*(.+)$", head.strip(), re.I)
                if m and (m.group(1) in KN.AGENTS or m.group(1) == KN.SHARED):
                    items.append({"type": "knowledge", "agent": m.group(1), "title": m.group(2).strip()[:120], "body": body}); continue
                m = re.match(r"Sửa skill\s+([A-Za-z0-9_-]+)\s*:\s*(.+)$", head.strip(), re.I)
                if m: items.append({"type": "skill", "skill": m.group(1), "title": m.group(2).strip()[:160], "body": body}); continue
                if re.match(r"Ticket cần tạo", head.strip(), re.I):
                    for line in body.splitlines():   # chỉ dòng gạch đầu dòng / đánh số là một ticket
                        m = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$", line)
                        if m and m.group(1).strip(): items.append({"type": "ticket", **ticket_hint(m.group(1).strip())})
            out.append({"ticket": key, "agent": agent, "path": rel, "ref": ref_used, "text": txt[:BODY_MAX], "items": items})
    return out

def ticket_hint(line):
    """'TE-14-FE3 rà 17 block (FE, 5 point)' → title, side, points, agent đoán từ phía."""
    side = "fe" if re.search(r"\bFE\b", line) else "be" if re.search(r"\bBE\b", line) else None
    pts = re.search(r"(\d+)\s*(?:point|pt|điểm)\b", line, re.I)
    agent = {"fe": "dev-fe", "be": "dev-be"}.get(side) or ("qa" if re.search(r"\bQA\b|test|e2e", line, re.I) else None)
    title = re.sub(r"\s*\((?:[^()]*\b(?:FE|BE|QA|point|pt)\b[^()]*)\)\s*$", "", line).strip() or line
    return {"title": title[:280], "side": side, "points": int(pts.group(1)) if pts and int(pts.group(1)) <= 100 else None, "agent": agent, "line": line}

def impl_ticket(r, d):
    """Ticket thực hiện tạo từ yêu cầu (mục Ticket cần tạo của impact.md hoặc CTO tự gõ): gắn nhãn mã yêu cầu để nối yêu cầu ↔ ticket ↔ sprint."""
    title = str(d.get("title") or "").strip()
    if not title: raise ValueError("tên ticket trống")
    agent = d.get("agent") if d.get("agent") in KN.AGENTS else None
    side = d.get("side") if d.get("side") in ("fe", "be") else ({"dev-fe": "fe", "dev-be": "be"}.get(agent))
    runnable = agent in ("dev-fe", "dev-be")   # Orchestrator suy fe_task/be_task từ phía; agent khác cần CTO đặt loại việc
    body = (f"Từ yêu cầu dự án {r['id']}: {r['title']} (ai-team/requirements/{r['id']}.md)"
            f"{(' — đề xuất trong ' + d['from_ticket'] + ' impact.md') if d.get('from_ticket') else ''}.\n\n"
            f"Nguồn: {r['id']}\nGiải pháp: \nDoD: ")
    try: pts = int(d.get("points")) if d.get("points") not in (None, "") else None
    except (TypeError, ValueError): pts = None
    return {"title": title[:300], "agent": agent, "side": side, "points": pts if pts is None or 0 <= pts <= 100 else None,
            "parent": (r["stories"][0] if r["stories"] else None),
            "labels": [r["id"]] + (["ai-draft"] if runnable else []), "body": body, "sprint": (str(d.get("sprint") or "").strip()[:60] or None),
            "priority": {"cao": "high", "vua": "medium", "thap": "low"}[r["priority"]], "due_date": r["due"] or None}

def note(id, text, by="cto"):
    r = get(id); r["history"].append(f"{now()[:16]} {by}: {text}"); r["updated"] = now(); _write(r); return id

def prompt_for(agent):
    """Yêu cầu đang áp dụng có liên quan tới agent (không chọn agent = mọi agent). Trả (text, dùng, bỏ)."""
    act = [r for r in items() if r["status"] == "ap-dung" and (not r["agents"] or agent in r["agents"])]
    act.sort(key=lambda r: ({"cao": 0, "vua": 1, "thap": 2}[r["priority"]], r["id"]))
    head = "\n\n## Yêu cầu dự án đang áp dụng (ai-team/requirements) — tuân thủ khi làm ticket; mâu thuẫn với ticket thì tạo ticket câu hỏi cho CTO\n"
    parts, used, skipped, size = [], [], [], len(head)
    for r in act:
        b = r["body"] if len(r["body"]) <= ONE_MAX else r["body"][:ONE_MAX] + "…"
        blk = f"\n### {r['id']} · {r['title']} [{SOURCES[r['source']]}{', hạn ' + r['due'] if r['due'] else ''}]\n{b}\n"
        if size + len(blk) > LIMIT: skipped.append(r); continue
        parts.append(blk); used.append(r); size += len(blk)
    if not used: return "", [], skipped
    if skipped: parts.append(f"\n(Còn {len(skipped)} yêu cầu chưa nạp vì quá {LIMIT} ký tự.)\n")
    return head + "".join(parts), used, skipped

def digest(agent):
    txt, _, _ = prompt_for(agent)
    return hashlib.sha256(txt.encode()).hexdigest()[:10] if txt else ""


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Yêu cầu dự án (ai-team/requirements)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("list")
    p = sp.add_parser("prompt"); p.add_argument("agent")
    p = sp.add_parser("status"); p.add_argument("id"); p.add_argument("status", choices=list(STATUSES))
    a = ap.parse_args()
    if a.cmd == "list":
        for r in items(): print(f"{r['id']:9} {r['status']:10} {r['priority']:5} {r['source']:17} {','.join(r['agents']) or '-':30} {r['title']}")
    elif a.cmd == "prompt":
        txt, used, skipped = prompt_for(a.agent); print(txt or f"(không có yêu cầu đang áp dụng cho {a.agent})")
        print(f"\n-- {len(used)} yêu cầu, {len(txt)}/{LIMIT} ký tự" + (f", bỏ {len(skipped)}" if skipped else ""), file=sys.stderr)
    elif a.cmd == "status":
        print(set_status(a.id, a.status, os.environ.get("TICKET_USER") or "cto"))
