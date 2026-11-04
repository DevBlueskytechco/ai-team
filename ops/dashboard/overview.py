"""Tổng quan dự án (menu Quản lý dự án › Tổng quan dự án): đọc tài liệu PO / BA / Tech Lead / QA của theme-efitco
ở nhánh develop đã tích hợp (origin/develop, không có thì develop) — không đọc thư mục làm việc vì agent có thể đang ở nhánh feature.
Trả JSON: yêu cầu (charter, PRD), giải pháp (SRS, kiến trúc, ADR, mã R), kế hoạch (mốc, ngân sách, rủi ro, chia task),
kết quả (checklist, test E2E, block/template/JS). Cache theo sha của nhánh.
Chạy thử: python3 ops/dashboard/overview.py [../theme-efitco]"""
import os, re, json, subprocess, threading

CACHE, LOCK = {}, threading.Lock()
DOCS = {"charter": "docs/charter.md", "prd": "docs/prd.md", "srs": "docs/srs.md", "arch": "docs/architecture.md",
        "reqmap": "docs/requirements-map.md", "test": "docs/test-strategy.md", "store": "docs/checklist-theme-store.md",
        "canvas": "docs/checklist-canvas.md"}


class Src:
    """Đọc file theo ref git (không đụng thư mục làm việc); ref None = đọc thẳng thư mục (repo chưa có git)."""
    def __init__(self, root, ref):
        self.root, self.ref = root, ref

    def _git(self, *a):
        p = subprocess.run(["git", "-C", self.root, *a], capture_output=True, text=True, timeout=20)
        return p.stdout if p.returncode == 0 else None

    def read(self, path):
        if self.ref: return self._git("show", f"{self.ref}:{path}")
        fp = os.path.join(self.root, path)
        return open(fp, encoding="utf-8").read() if os.path.isfile(fp) else None

    def ls(self, d):
        """[(tên, byte)] các file ngay trong thư mục d."""
        if self.ref:
            out = self._git("ls-tree", "-l", self.ref, d.rstrip("/") + "/") or ""
            res = []
            for l in out.splitlines():
                m = re.match(r"\S+\s+(\w+)\s+\S+\s+(\S+)\t(.+)$", l)
                if m and m.group(1) == "blob": res.append((m.group(3).split("/")[-1], int(m.group(2)) if m.group(2).isdigit() else 0))
            return res
        fp = os.path.join(self.root, d)
        return [(f, os.path.getsize(os.path.join(fp, f))) for f in sorted(os.listdir(fp)) if os.path.isfile(os.path.join(fp, f))] if os.path.isdir(fp) else []

    def dirs(self, d):
        if self.ref:
            out = self._git("ls-tree", self.ref, d.rstrip("/") + "/") or ""
            return [l.split("\t")[1].split("/")[-1] for l in out.splitlines() if " tree " in l]
        fp = os.path.join(self.root, d)
        return sorted(x for x in os.listdir(fp) if os.path.isdir(os.path.join(fp, x))) if os.path.isdir(fp) else []


def ref_of(root):
    for r in ("origin/develop", "develop"):
        p = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", r + "^{commit}"], capture_output=True, text=True, timeout=10)
        if p.returncode == 0: return r, p.stdout.strip()
    return None, None


# ---------- markdown nhỏ ----------
def sections(text, level=2):
    """{tiêu đề: thân} theo heading cấp `level`; khoá "" = phần trước heading đầu."""
    out, cur, buf = {}, "", []
    mark = "#" * level + " "
    for l in (text or "").splitlines():
        if l.startswith(mark) and not l.startswith(mark + "#"):
            out[cur] = "\n".join(buf).strip(); cur, buf = l[len(mark):].strip(), []
        else: buf.append(l)
    out[cur] = "\n".join(buf).strip()
    return out

def pick(secs, *keys):
    """Thân của mục có tiêu đề bắt đầu bằng một trong các khoá (không phân biệt hoa thường, bỏ số thứ tự)."""
    for k in keys:
        for t, b in secs.items():
            if re.sub(r"^\d+\.\s*", "", t).lower().startswith(k.lower()): return b
    return ""

def bullets(text):
    items = []
    for l in (text or "").splitlines():
        m = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$", l)
        if m: items.append(m.group(1).strip())
        elif items and re.match(r"^\s{2,}\S", l): items[-1] += " " + l.strip()
    return items

def numbered(text):
    return [m.group(1).strip() for m in re.finditer(r"^\s*\d+[.)]\s+(.*)$", text or "", re.M)]

def table(text):
    """Bảng markdown → list hàng (bỏ hàng tiêu đề và hàng ---)."""
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in (text or "").splitlines() if l.strip().startswith("|")]
    rows = [r for r in rows if not all(re.fullmatch(r":?-{3,}:?", c) for c in r if c)]
    return rows[1:] if rows else []

def keys(text): return sorted(set(re.findall(r"\bTE-\d+\b", text or "")), key=lambda k: int(k[3:]))

def first_line(text, prefix):
    m = re.search(rf"^{prefix}.*$", text or "", re.M)
    return m.group(0).strip() if m else ""


# ---------- PO ----------
def charter(t):
    s = sections(t)
    head = (t or "").splitlines()[0].lstrip("# ").strip() if t else ""
    pre = s.get("", "")
    decisions = [l.strip() for l in pre.splitlines() if l.strip().startswith("Quyết định")]
    scope = pick(s, "Phạm vi")
    sc = {"in": "", "out": ""}
    for l in scope.splitlines():
        m = re.match(r"^\s*(Trong|Ngoài)\s*:\s*(.*)$", l)
        if m: sc["in" if m.group(1) == "Trong" else "out"] = m.group(2).strip()
    budget = pick(s, "Ngân sách")
    hours = {m.group(1): int(m.group(2)) for m in re.finditer(r"(PO|BA|Tech Lead|Designer|Dev FE|Dev BE|QA|DevOps|Writer)\s+(\d+)", budget)}
    total = re.search(r"=\s*([\d.]+)\s*giờ\s*/\s*(\d+)\s*tuần", budget)
    risks = []
    for it in numbered(pick(s, "Rủi ro")):
        m = re.split(r"\s*Xử lý:\s*", it, maxsplit=1)
        risks.append({"risk": m[0].strip(), "action": m[1].strip() if len(m) > 1 else ""})
    succ = pick(s, "Tiêu chí thành công")
    gates = [{"gate": m.group(1), "text": m.group(0).strip()} for m in re.finditer(r"^(G\d)\s*[—-].*$", t or "", re.M)]
    ms = pick(s, "Mốc")
    return {"head": head, "decisions": decisions, "goals": numbered(pick(s, "Mục tiêu")), "persona": pick(s, "Persona"),
            "scope": sc, "milestones": ms.split("\n")[0].strip(), "milestones_note": "\n".join(ms.split("\n")[1:]).strip(),
            "canvas_week": _int(re.search(r"Canvas[^·.]*?tuần\s*(\d+)", ms)), "eval_weeks": [_int(m) for m in [re.search(r"eval\s*tuần\s*(\d+)", ms), re.search(r"eval\s*tuần\s*\d+\s*[–-]\s*(\d+)", ms)]],
            "budget": {"hours": hours, "total_h": _int(total, 1), "weeks": _int(total, 2), "text": budget.strip()},
            "risks": risks, "success": [l for l in succ.splitlines() if l.strip() and not re.match(r"^G\d\s*[—-]", l)][:1], "gates": gates}

def _int(m, g=1):
    try: return int(float(m.group(g))) if m else None
    except (ValueError, IndexError): return None

def prd(t):
    s = sections(t)
    feat = pick(s, "Tính năng")
    moscow = []
    for l in feat.splitlines():
        m = re.match(r"^\s*(Must|Should|Could|Won't|Won’t)\s*:\s*(.*)$", l, re.I)
        if not m: continue
        items = [x.strip().rstrip(".") for x in re.split(r";\s*", m.group(2)) if x.strip()]
        moscow.append({"level": m.group(1).replace("’", "'").capitalize(), "items": [{"text": x, "stories": keys(x)} for x in items]})
    split = lambda x: [y.strip().rstrip(".") for y in re.split(r";\s*", x.replace("\n", " ")) if y.strip()]
    return {"problem": pick(s, "Vấn đề"), "users": bullets(pick(s, "Người dùng")), "moscow": moscow, "metrics": split(pick(s, "Chỉ số")),
            "constraints": split(pick(s, "Ràng buộc")), "open": split(pick(s, "Câu hỏi mở"))}


# ---------- BA ----------
def srs(t):
    top = sections(t)
    stories = {}
    for title, body in sections(pick(top, "Module", "2."), 3).items():
        m = re.match(r"^(TE-\d+)\s*[—-]\s*(.+)$", title)
        if not m: continue
        meta = first_line(body, "Phía:")
        side = re.search(r"Phía:\s*([^·]+)", meta); est = re.search(r"(\d+)\s*point", meta)
        acs = []
        for l in body.splitlines():
            a = re.match(r"^\s*-\s*(AC\d+)\b\s*(?:\(([^)]*)\))?\s*(.*)$", l)
            if a: acs.append({"id": a.group(1), "tag": a.group(2) or "", "text": a.group(3).strip()})
        story = next((l.strip() for l in body.splitlines() if re.match(r"^\s*Là\s", l)), "")
        rc = first_line(body, "Mã R:")
        stories[m.group(1)] = {"title": m.group(2).strip(), "side": side.group(1).strip() if side else "", "est": int(est.group(1)) if est else None,
                               "story": story, "acs": acs, "rcodes": rc[len("Mã R:"):].strip() if rc else ""}
    return {"head": (t or "").splitlines()[0].lstrip("# ").strip() if t else "", "nfr": bullets(pick(top, "1.", "Yêu cầu phi chức năng")),
            "stories": stories, "decided": bullets(pick(top, "3.", "Quyết định"))}

def reqmap(t):
    return [{"code": r[0], "text": r[1], "apply": r[2], "stories": keys(r[3]) if len(r) > 3 else [], "story_text": r[3] if len(r) > 3 else ""}
            for r in table(t) if len(r) >= 3]


# ---------- Tech Lead ----------
def arch(t):
    s = sections(t)
    return {"head": (t or "").splitlines()[0].lstrip("# ").strip() if t else "",
            "parts": [{"title": k, "text": v} for k, v in s.items() if k and v]}

def adrs(src):
    out = []
    for f, _ in src.ls("docs/adr"):
        if not f.endswith(".md"): continue
        t = src.read(f"docs/adr/{f}") or ""
        h = re.search(r"^#\s+(.*)$", t, re.M); meta = first_line(t, "Ngày:")
        st = re.search(r"Trạng thái:\s*([^|(]+)", meta)
        out.append({"file": f"docs/adr/{f}", "num": f[:4], "title": re.sub(r"^\d+\.\s*", "", h.group(1)).strip() if h else f,
                    "date": (re.search(r"Ngày:\s*([\d-]+)", meta) or [None, ""])[1], "status": st.group(1).strip() if st else "", "meta": meta})
    return sorted(out, key=lambda x: x["num"])

def splits(src):
    out = []
    for d in src.dirs("drafts/techlead"):
        t = src.read(f"drafts/techlead/{d}/task-split.md")
        if not t: continue
        h = re.search(r"^#\s+(.*)$", t, re.M)
        est = next((l.strip() for l in t.splitlines() if l.startswith("Ước lượng")), "")
        out.append({"ticket": d, "title": h.group(1).strip() if h else d, "stories": keys(h.group(1) if h else ""), "estimate": est[:400],
                    "file": f"drafts/techlead/{d}/task-split.md"})
    return out


# ---------- QA / kết quả ----------
def checks(store_t, canvas_t):
    st = []
    for r in table(store_t):
        if len(r) >= 4: st.append({"code": r[0], "text": r[1], "apply": r[2], "result": r[3], "evidence": r[4] if len(r) > 4 else ""})
    head = next((l for l in (canvas_t or "").splitlines() if l.strip().startswith("|")), "")
    cols = [c.strip() for c in head.strip().strip("|").split("|")][2:] if head else []
    cv = [{"code": r[0], "text": r[1], "cells": r[2:2 + len(cols)]} for r in table(canvas_t) if len(r) >= 2]
    sk = [x.strip() for x in re.split(r"\s*\d+\.\s+", (sections(canvas_t).get(next((k for k in sections(canvas_t) if "Sidekick" in k), ""), "") or "")) if x.strip()]
    return {"store": st, "canvas": {"cols": cols, "rows": cv}, "sidekick": sk[:20]}

def specs(src):
    out = []
    for f, size in src.ls("tests/e2e"):
        if not f.endswith(".spec.ts"): continue
        t = src.read(f"tests/e2e/{f}") or ""
        key = f[:-len(".spec.ts")]
        out.append({"file": f"tests/e2e/{f}", "key": key, "acs": sorted(set(re.findall(r"\bAC\d+\b", t)), key=lambda a: int(a[2:])),
                    "stories": keys(t), "tests": len(re.findall(r"(?<![.\w$])test(?:\.(?:only|fixme))?\s*\(\s*['\"`]", t))})
    return out

def code(src):
    js = [{"name": f, "bytes": b} for f, b in src.ls("assets") if f.endswith(".js")]
    css = [{"name": f, "bytes": b} for f, b in src.ls("assets") if f.endswith(".css")]
    ver = None
    try:
        for x in json.loads(src.read("config/settings_schema.json") or "[]"):
            if x.get("name") == "theme_info": ver = {"name": x.get("theme_name"), "version": x.get("theme_version")}
    except Exception: pass
    return {"blocks": sorted(f[:-7] for f, _ in src.ls("blocks") if f.endswith(".liquid")),
            "templates": sorted(f for f, _ in src.ls("templates")), "snippets": len([1 for f, _ in src.ls("snippets") if f.endswith(".liquid")]),
            "locales": len(src.ls("locales")), "js": js, "css": css, "merchant_docs": sorted(f for f, _ in src.ls("docs/merchant") if f.endswith(".md")),
            "theme": ver}


def build(root, repo="DevBlueskytechco/theme-efitco"):
    ref, sha = ref_of(root) if os.path.isdir(os.path.join(root, ".git")) else (None, None)
    with LOCK:
        if sha and CACHE.get("sha") == sha: return CACHE["data"]
    src = Src(root, ref)
    raw = {k: src.read(p) for k, p in DOCS.items()}
    date = src._git("log", "-1", "--format=%cI|%s", ref).strip() if ref else ""
    d = {"ref": ref, "sha": (sha or "")[:7], "date": date.split("|")[0] if date else "", "subject": date.split("|", 1)[1][:160] if "|" in date else "",
         "repo": repo, "branch": (ref or "").split("/")[-1] or "develop", "missing": [p for k, p in DOCS.items() if not raw[k]],
         "charter": charter(raw["charter"]), "prd": prd(raw["prd"]), "srs": srs(raw["srs"]), "reqmap": reqmap(raw["reqmap"]),
         "arch": arch(raw["arch"]), "adr": adrs(src), "splits": splits(src),
         "test": bullets(pick(sections(raw["test"]), "Phạm vi")), "checks": checks(raw["store"], raw["canvas"]), "specs": specs(src), "code": code(src)}
    if sha:
        with LOCK: CACHE.update(sha=sha, data=d)
    return d


if __name__ == "__main__":
    import sys
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "..", "theme-efitco"))
    print(json.dumps(build(root), ensure_ascii=False, indent=1)[:6000])
