#!/usr/bin/env python3
"""落ち先（→ 反映済 / → タスク ID / → 未決 課題 ID …）の解析・解決の共有モジュール。

pickup_check.py（Stop hook）・scripts/check_drops.py・build.py・close.py・new.py が同じ解釈で読むために置く。
scripts/ や docs/案件/01_タスク管理/ からは `sys.path.insert(0, <root>/.claude/hooks)` で import する。標準ライブラリのみ。

落ち先の書き方（docs/案件/02_打合せ/README.md が人向けの正本）:
  行末の最後の `→` 以降が落ち先。複数は `、` で区切る。
  反映済: 01 §3 ／ 反映済: ADR-003 ／ 反映済: 記録のみ（理由） ／ 候補: 05 §3 ／ ハーネス候補 HN-01
  APP-03（タスク） ／ 未決 QA-01（課題） ／ 取り下げ: 理由
  ID の書式は [A-Z][A-Z0-9]*-NN（2 桁以上）。`APP-1` は書式違反（起票前の予想 ID の典型）。

どの関数も例外を外に出さない作りにしている（読めないファイルは 0 件扱い）。
"""
from __future__ import annotations

import datetime
import glob as globmod
import hashlib
import os
import re
import sys
from dataclasses import dataclass, field

MEETING_DIR = "docs/案件/02_打合せ"
TASK_DIR = "docs/案件/01_タスク管理"
DESIGN_DIR = "docs/設計書"
CONFIRM_MD = "docs/案件/確認依頼一覧.md"
LEDGER_MD = "docs/ハーネス台帳.md"
OVERVIEW_HTML = "docs/プロジェクト概要.html"

ID_OK = re.compile(r"^[A-Z][A-Z0-9]*-\d{2,}$")
ID_ANY = re.compile(r"^([A-Z][A-Z0-9]*-\d+)(?=$|[\s（(])")
ID_IN_TEXT = re.compile(r"(?<![A-Za-z0-9_-])([A-Z][A-Z0-9]*-\d+)(?![0-9A-Za-z])")
# ID のように見えるが タスク・課題ではないもの（ロール・ADR・ハーネス・原則・不変条件・画面）
NON_TASK_PREFIXES = {"SH", "ADR", "HN", "P", "INV", "SCR", "U"}
DOC_REF = re.compile(r"[（(]未決\s*([A-Z][A-Z0-9]*-\d+)\s*[）)]")
OLD_U = re.compile(r"(?<![A-Za-z0-9_-])U-\d{2,}(?!\d)")
NO_DROP_WORDS = {"", "?", "？", "未定", "-", "—"}

MEETING_SECTIONS = {"決定": "決定", "決定事項": "決定", "未決": "未決", "宿題": "宿題"}


@dataclass
class Row:
    kind: str            # 決定 / 未決 / 宿題
    text: str            # 行の本文（落ち先を除く）
    drop_raw: str | None  # 落ち先の生文字列（`→` の後）。無ければ None
    line_no: int


@dataclass
class Drop:
    kind: str            # applied / record / candidate / harness / task / issue / withdrawn / none / format
    target: str
    raw: str


@dataclass
class Item:
    id: str
    kind: str            # タスク / 課題
    state: str           # open / closed
    path: str            # ルート相対
    fields: dict = field(default_factory=dict)


@dataclass
class Problem:
    code: str            # orphan / format / missing / notissue
    message: str


# ---------------------------------------------------------------------------
# 読み込みの小物
# ---------------------------------------------------------------------------

def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def strip_comments(text: str) -> str:
    """HTML コメントを消す（行数は保つ）。"""
    return re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            fields: dict = {}
            for fl in lines[1:i]:
                if ":" in fl:
                    k, _, v = fl.partition(":")
                    v = v.strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]
                    fields[k.strip()] = v
            return fields, "\n".join(lines[i + 1:])
    return {}, text


def short(text: str, n: int = 30) -> str:
    """報告用に本文を n 字で切る。秘密らしき文字列を含む行は本文を出さない。"""
    t = re.sub(r"\s+", " ", text or "").strip()
    if looks_secret(t):
        return "（秘密らしき文字列を含む行）"
    return t if len(t) <= n else t[:n] + "…"


_secret_fn = None


def looks_secret(text: str) -> bool:
    """秘密検出（scripts/check_skeleton.py の secret_hits があればそれ、無ければ簡易版）。"""
    global _secret_fn
    if _secret_fn is None:
        _secret_fn = _fallback_secret
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            scripts = os.path.normpath(os.path.join(here, "..", "..", "scripts"))
            if scripts not in sys.path:
                sys.path.append(scripts)
            from check_skeleton import secret_hits  # type: ignore
            _secret_fn = secret_hits
        except Exception:
            pass
    try:
        return bool(_secret_fn(text))
    except Exception:
        return _fallback_secret(text)


def _fallback_secret(text: str) -> bool:
    if re.search(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@]*:[^\s/@]+@", text):
        return True
    if re.search(r"\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{36,}|\bsk-[A-Za-z0-9_\-]{20,}|PRIVATE KEY-----", text):
        return True
    m = re.search(r"(?i)(password|passwd|secret|token|api[_-]?key|パスワード)\s*[:=：]\s*['\"`]?([^\s'\"`<>|、。，,;]+)", text)
    return bool(m and len(m.group(2)) >= 8 and m.group(2).isascii())


def sha8(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# 打合せ記録
# ---------------------------------------------------------------------------

def split_drop(line: str) -> tuple[str, str | None]:
    """行を (本文, 落ち先の生文字列) に分ける。`→` が無ければ落ち先は None。"""
    i = line.rfind("→")
    if i < 0:
        return line.strip(), None
    return line[:i].strip(), line[i + 1:].strip()


def _is_placeholder(text: str) -> bool:
    t = text.strip()
    return not t or bool(re.fullmatch(r"[（(].*[）)]", t)) or t in ("…", "...")


def meeting_files(root: str) -> list[str]:
    d = os.path.join(root, MEETING_DIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [f"{MEETING_DIR}/{n}" for n in names
            if n.endswith(".md") and n != "README.md" and not n.startswith(".")
            and os.path.isfile(os.path.join(d, n))]


def is_meeting_path(rel: str) -> bool:
    return (rel.startswith(MEETING_DIR + "/") and rel.endswith(".md")
            and "/" not in rel[len(MEETING_DIR) + 1:] and not rel.endswith("/README.md"))


def parse_meeting(path: str) -> list[Row]:
    """`## 決定`（旧 `## 決定事項`）・`## 未決` の箇条と `## 宿題` の表から行を返す。読めなければ空。

    `## 要約` > `### 決定事項` のような H3 の区切りも読む（tl;dv 等で作る記録）。H2 で始まった区切りの下の
    関係の無い H3 は区切りを保ち、H3 で始まった区切りは次の関係の無い H3 か H2 で終わる。
    """
    text = read_text(path)
    if text is None:
        return []
    lines = strip_comments(text).splitlines()
    rows: list[Row] = []
    section = None
    section_level = 0
    in_code = False
    header: list[str] | None = None
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{2,3})\s+(.+?)\s*$", s)
        if m:
            level = len(m.group(1))
            name = MEETING_SECTIONS.get(re.sub(r"[（(].*$", "", m.group(2)).strip())
            if level == 2 or name or section_level == 3:
                section, section_level = name, (level if name else 0)
                header = None
            continue
        if s.startswith("#"):
            continue
        if section in ("決定", "未決"):
            bm = re.match(r"^[-*+]\s+(?:\[.\]\s+)?(.*)$", s)
            if not bm:
                continue
            body, drop = split_drop(bm.group(1))
            if _is_placeholder(body) and drop is None:
                continue
            rows.append(Row(section, body, drop, i))
        elif section == "宿題" and s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set(":- ") for c in cells):
                continue
            if header is None:
                header = cells
                continue
            if all(not c or _is_placeholder(c) for c in cells):
                continue
            rows.append(_homework_row(header, cells, i))
    return rows


def _homework_row(header: list[str], cells: list[str], line_no: int) -> Row:
    def col(*names: str) -> int:
        for n in names:
            for j, h in enumerate(header):
                if n in h:
                    return j
        return -1

    what = col("何を")
    drop_col = col("落ち先")
    old_col = col("関連タスク")
    text = cells[what] if 0 <= what < len(cells) else " / ".join(c for c in cells if c)
    drop: str | None = None
    if 0 <= drop_col < len(cells):
        v = cells[drop_col]
        drop = v[v.rfind("→") + 1:].strip() if "→" in v else (v if v else None)
    elif 0 <= old_col < len(cells):
        v = cells[old_col].strip()                          # 旧形式: 関連タスク ID をそのまま落ち先と読む
        drop = v if v and v not in NO_DROP_WORDS else None
    if drop is None and "→" in text:
        text, drop = split_drop(text)
    return Row("宿題", text, drop, line_no)


# ---------------------------------------------------------------------------
# 落ち先の分類と解決
# ---------------------------------------------------------------------------

def _split_top(s: str) -> list[str]:
    """`、` で分ける（括弧の中の `、` では分けない）。"""
    out, buf, depth = [], "", 0
    for ch in s:
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        if ch == "、" and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    out.append(buf)
    return [x.strip() for x in out]


def _after_label(s: str, label: str) -> str | None:
    m = re.match(rf"^{label}\s*[:：]?\s*(.*)$", s)
    return m.group(1).strip() if m else None


def parse_drops(raw: str | None) -> list[Drop]:
    """落ち先の生文字列を分類する。None・空・`?`・`未定` は kind=none。"""
    if raw is None:
        return [Drop("none", "", "")]
    raw = raw.strip()
    if raw.startswith("→"):
        raw = raw[1:].strip()
    if raw in NO_DROP_WORDS:
        return [Drop("none", "", raw)]
    out: list[Drop] = []
    for part in _split_top(raw):
        if not part:
            continue
        d = _classify(part)
        # `反映済: ADR-003、01 §3` の 2 つ目のように、ラベルの無い文書参照は直前の 反映済／候補 を引き継ぐ
        if (d.kind == "format" or (d.kind == "task" and part.startswith("ADR-"))) \
                and out and out[-1].kind in ("applied", "candidate") \
                and re.match(r"^(\d{2}(?!\d)|ADR-\d+)", part):
            d = Drop(out[-1].kind, part, part)
        out.append(d)
    return out or [Drop("none", "", raw)]


def _classify(p: str) -> Drop:
    if p in NO_DROP_WORDS:
        return Drop("none", "", p)
    v = _after_label(p, "反映済")
    if v is not None:
        if v.startswith("記録のみ"):
            reason = re.search(r"[（(]\s*([^）)]+?)\s*[）)]", v)
            return Drop("record", reason.group(1) if reason else "", p)
        return Drop("applied", v, p)
    v = _after_label(p, "ハーネス候補")
    if v is not None:
        return Drop("harness", v, p)
    v = _after_label(p, "候補")
    if v is not None:
        return Drop("candidate", v, p)
    v = _after_label(p, "未決")
    if v is not None:
        return Drop("issue", v, p)
    v = _after_label(p, "取り下げ")
    if v is not None:
        return Drop("withdrawn", v, p)
    if p.startswith("保留"):
        return Drop("format", "保留は落ち先にしない（決まっていないなら未決に起票する）", p)
    m = ID_ANY.match(p)
    if m:
        return Drop("task", m.group(1), p)
    return Drop("format", "落ち先の書き方が不明", p)


def load_items(root: str) -> dict[str, Item]:
    """open/・closed/ のタスク md（frontmatter に id を持つもの）を読む。"""
    items: dict[str, Item] = {}
    for state in ("open", "closed"):
        d = os.path.join(root, TASK_DIR, state)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if not n.endswith(".md") or n.startswith("."):
                continue
            text = read_text(os.path.join(d, n))
            if text is None:
                continue
            fields, _ = parse_frontmatter(text)
            iid = fields.get("id", "").strip()
            if not iid:
                continue
            items[iid] = Item(iid, fields.get("kind", "").strip() or "タスク", state,
                              f"{TASK_DIR}/{state}/{n}", fields)
    return items


def ledger_ids(root: str) -> set[str]:
    """ハーネス台帳の表の 1 列目にある HN-ID。"""
    text = read_text(os.path.join(root, LEDGER_MD))
    if text is None:
        return set()
    ids = set()
    for line in strip_comments(text).splitlines():
        s = line.strip()
        if s.startswith("|"):
            first = s.strip("|").split("|")[0].strip()
            m = re.match(r"^(HN-\d+)", first)
            if m:
                ids.add(m.group(1))
    return ids


def design_doc_exists(root: str, nn: str) -> bool:
    """番号 nn の設計書があるか（拡張子・名前は問わない。template/ の中は数えない）。"""
    return any(os.path.isfile(p) for p in globmod.glob(os.path.join(globmod.escape(os.path.join(root, DESIGN_DIR)), f"{nn}-*")))


def design_doc_addable(root: str, nn: str) -> bool:
    """番号 nn の設計書がまだ無く、docs/設計書/template/ にあって足せるか（`候補: 05 §3` の行き先）。"""
    return bool(globmod.glob(os.path.join(globmod.escape(os.path.join(root, DESIGN_DIR, "template")), f"{nn}-*.md")))


def adr_exists(root: str, num: str) -> bool:
    pat = os.path.join(globmod.escape(os.path.join(root, DESIGN_DIR, "decisions")), f"ADR-{int(num):03d}-*.md")
    return bool(globmod.glob(pat))


def _check_id(iid: str, items: dict[str, Item]) -> Problem | None:
    if not ID_OK.match(iid):
        return Problem("format", f"書式違反の ID「{iid}」（2 桁以上。起票してから new.py の出力を写す）")
    if iid not in items:
        return Problem("missing", f"ID 不在「{iid}」（起票してから new.py の出力を写す）")
    return None


def resolve(drop: Drop, items: dict[str, Item], root: str, ledger: set[str] | None = None) -> Problem | None:
    """落ち先 1 つの問題を返す。問題が無ければ None（候補・取り下げも None）。"""
    k, t = drop.kind, drop.target
    if k == "none":
        return Problem("orphan", "落ち先なし")
    if k == "format":
        return Problem("format", f"書式違反「{short(drop.raw, 20)}」: {t}")
    if k in ("applied", "candidate"):
        if not t:
            return Problem("format", f"書式違反「{short(drop.raw, 20)}」: 反映先が空")
        m = re.match(r"^(\d{2})(?!\d)", t)
        # 候補はまだ足していない文書でもよい（文書を育てる: template/ にあれば、足すときに反映する先）
        if m and not design_doc_exists(root, m.group(1)) and not (k == "candidate" and design_doc_addable(root, m.group(1))):
            return Problem("missing", f"文書不在「{m.group(1)}」（docs/設計書/{m.group(1)}-*.md が無い）")
        if k == "candidate" and not m:
            return Problem("format", f"書式違反「{short(drop.raw, 20)}」: 候補は `候補: 05 §3` の形")
        m = re.match(r"^ADR-(\d+)", t)
        if m and not adr_exists(root, m.group(1)):
            return Problem("missing", f"文書不在「ADR-{m.group(1)}」（decisions/ に無い）")
        return None
    if k == "record":
        return None if t else Problem("format", "書式違反「記録のみ」: 括弧で理由を書く（例: 記録のみ（議事の共有だけ））")
    if k == "withdrawn":
        return None if t else Problem("format", "書式違反「取り下げ」: 理由を書く（例: 取り下げ: 重複）")
    if k == "harness":
        m = re.match(r"^(HN-\d+)", t)
        if not m:
            return Problem("format", f"書式違反「{short(drop.raw, 20)}」: `ハーネス候補 HN-01` の形")
        if not ID_OK.match(m.group(1)):
            return Problem("format", f"書式違反の ID「{m.group(1)}」")
        if m.group(1) not in (ledger if ledger is not None else ledger_ids(root)):
            return Problem("missing", f"ID 不在「{m.group(1)}」（{LEDGER_MD} の表に無い）")
        return None
    if k == "task":
        return _check_id(t, items)
    if k == "issue":
        m = ID_ANY.match(t)
        if not m:
            return Problem("format", f"書式違反「{short(drop.raw, 20)}」: `未決 QA-01` の形（課題を起票してから）")
        p = _check_id(m.group(1), items)
        if p:
            return p
        if items[m.group(1)].kind != "課題":
            return Problem("notissue", f"課題でない「{m.group(1)}」（未決の落ち先は kind: 課題 の ID）")
        return None
    return Problem("format", "書式違反")


def row_problems(raw: str | None, items: dict[str, Item], root: str,
                 ledger: set[str] | None = None) -> list[Problem]:
    out = []
    for d in parse_drops(raw):
        p = resolve(d, items, root, ledger)
        if p:
            out.append(p)
    return out


def has_candidate(raw: str | None) -> bool:
    return any(d.kind == "candidate" for d in parse_drops(raw))


# ---------------------------------------------------------------------------
# 課題の `## 決定`
# ---------------------------------------------------------------------------

def section_lines(body: str, title: str) -> list[str] | None:
    """`## <title>` の直下（次の `## ` まで）の行。HTML コメントは除く。見出しが無ければ None。"""
    lines = strip_comments(body).splitlines()
    out: list[str] | None = None
    for line in lines:
        if re.match(r"^##\s", line) and not line.startswith("###"):
            if out is not None:
                break
            if re.match(rf"^##\s+{re.escape(title)}\s*$", line.strip()):
                out = []
            continue
        if out is not None:
            out.append(line)
    return out


def issue_decision(text: str) -> tuple[str, list[str]]:
    """課題 md の `## 決定` から (決定の 1 行目, 落ち先の生文字列のリスト) を返す。"""
    _, body = parse_frontmatter(text)
    lines = section_lines(body, "決定") or []
    first = ""
    drops: list[str] = []
    for line in lines:
        s = re.sub(r"^[-*+]\s+", "", line.strip())
        if not s:
            continue
        if s.startswith("→"):
            drops.append(s[1:].strip())
            continue
        if not first:
            body_text, drop = split_drop(s)
            if _is_placeholder(body_text) and drop is None:
                continue                                  # 雛形の案内（「（…）」だけの行）は決定に数えない
            first = body_text
            if drop is not None:
                drops.append(drop)
    return first, drops


def issue_problems(text: str, items: dict[str, Item], root: str, ledger: set[str] | None = None) -> list[str]:
    """課題を閉じる条件（決定の 1 行目・落ち先 1 行以上・ID の実在）を満たさない理由の一覧。"""
    first, drops = issue_decision(text)
    out = []
    if not first:
        out.append("`## 決定` の 1 行目（決定の内容）が空")
    if not drops:
        out.append("`## 決定` に落ち先の行（→ 反映済: 01 §3 / → APP-03 / → 未決 QA-02 / → 取り下げ: 理由）が無い")
    for d in drops:
        for p in row_problems(d, items, root, ledger):
            out.append(f"落ち先「{short(d, 30)}」: {p.message}")
    return out


# ---------------------------------------------------------------------------
# 設計書の（未決 ID）・確認依頼一覧
# ---------------------------------------------------------------------------

def _iter_md_lines(path: str):
    text = read_text(path)
    if text is None:
        return
    in_code = False
    for i, line in enumerate(strip_comments(text).splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            yield i, line


def design_docs(root: str) -> list[str]:
    base = os.path.join(root, DESIGN_DIR)
    out = []
    for p in sorted(globmod.glob(os.path.join(globmod.escape(base), "**", "*.md"), recursive=True)):
        rel = os.path.relpath(p, root).replace("\\", "/")
        if rel.startswith(DESIGN_DIR + "/template/"):
            continue                                        # 足す前の元。本文の例示を参照として数えない
        out.append(rel)
    return out


def doc_refs(root: str) -> list[tuple[str, int, str]]:
    """設計書本文の「（未決 <ID>）」。「」やバッククォートで囲んだ書き方の例は数えない。"""
    out = []
    for rel in design_docs(root):
        for i, line in _iter_md_lines(os.path.join(root, rel)):
            for m in DOC_REF.finditer(line):
                before = line[m.start() - 1] if m.start() > 0 else ""
                if before in "「`『":
                    continue
                out.append((rel, i, m.group(1)))
    return out


def old_u_refs(root: str) -> list[tuple[str, int, str]]:
    out = []
    for rel in design_docs(root):
        for i, line in _iter_md_lines(os.path.join(root, rel)):
            for m in OLD_U.finditer(line):
                out.append((rel, i, m.group(0)))
    return out


def confirm_rows(root: str) -> list[tuple[int, str, list[str]]]:
    """確認依頼一覧の未確認 `[ ]` 行（履歴節を除く）。(行, 本文, 行に書かれた ID) を返す。"""
    out = []
    in_history = False
    for i, line in _iter_md_lines(os.path.join(root, CONFIRM_MD)):
        s = line.strip()
        if s.startswith("## "):
            in_history = "履歴" in s
            continue
        if in_history:
            continue
        m = re.match(r"^[-*+]\s+\[\s\]\s+(.*)$", s)
        if not m:
            continue
        ids = [x for x in ID_IN_TEXT.findall(m.group(1)) if x.split("-")[0] not in NON_TASK_PREFIXES]
        out.append((i, m.group(1), ids))
    return out


# ---------------------------------------------------------------------------
# 決定の一覧（概要 HTML「直近の決定」）
# ---------------------------------------------------------------------------

def _meeting_date(rel: str) -> tuple[str, str]:
    name = os.path.splitext(os.path.basename(rel))[0]
    m = re.match(r"^(\d{4})(\d{2})(\d{2})_?(.*)$", name)
    if not m:
        return "", name
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", m.group(4)


def recent_decisions(root: str, n: int = 5) -> list[dict]:
    """打合せ記録の決定行（日付はファイル名）と閉じた課題の `## 決定`（日付は closed）を新しい順に n 件。

    決定の正本は課題。落ち先が課題の ID の決定行は、課題の側で数える（二重にしない）。
    旧い形（`→ 反映済: 01 §3` など）の決定行は、そのまま決定として数える。
    """
    found = []
    seq = 0
    items = load_items(root)
    issue_ids = {i for i, it in items.items() if it.kind == "課題"}
    for rel in meeting_files(root):
        date, title = _meeting_date(rel)
        if not date:
            continue
        for r in parse_meeting(os.path.join(root, rel)):
            if r.kind != "決定" or not r.text:
                continue
            m = ID_ANY.match((r.drop_raw or "").strip())
            if m and m.group(1) in issue_ids:
                continue
            seq += 1
            found.append({"date": date, "text": r.text, "source": f"打合せ {date[5:7]}/{date[8:10]} {title}".strip(),
                          "ref": rel, "seq": seq})
    for it in items.values():
        if it.state != "closed" or it.kind != "課題":
            continue
        text = read_text(os.path.join(root, it.path)) or ""
        first, _ = issue_decision(text)
        date = (it.fields.get("closed") or "").strip()
        if not first or not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        seq += 1
        found.append({"date": date, "text": first, "source": it.id, "ref": it.path, "seq": seq})
    found.sort(key=lambda d: (d["date"], -d["seq"]), reverse=True)
    return found[:n]


# ---------------------------------------------------------------------------
# 期限
# ---------------------------------------------------------------------------

def parse_date(s: str) -> datetime.date | None:
    s = (s or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def today() -> datetime.date:
    """テスト用に環境変数 CLAUDE_SKELETON_TODAY（YYYY-MM-DD）で今日を上書きできる。"""
    return parse_date(os.environ.get("CLAUDE_SKELETON_TODAY", "")) or datetime.date.today()
