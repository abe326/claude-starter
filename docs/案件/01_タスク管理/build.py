#!/usr/bin/env python3
"""
build.py — open/ closed/ screens/ の *.md を走査して data.js を生成する

Usage:
  python3 build.py            # data.js を生成し、docs/プロジェクト概要.html の自動欄を更新
  python3 build.py --check    # 何も書かずに検証だけ行う（警告 0 なら終了コード 0、あれば 1）

生成物:
  data.js
    window.TASKS   = [...]   タスク（open/ closed/）。due・decider を含む
    window.SCREENS = [...]   画面（screens/）。tasks は screens: を持つタスクからの逆引き

  docs/プロジェクト概要.html（= ../../プロジェクト概要.html）の自動欄（マーカーの内側だけを置換。手で編集しない）
    task-snapshot     タスクの状況（課題は除き、期限列つき）
    open-issues       決めてほしいこと（open の課題）
    milestones        次の節目（ロードマップの時期が日付の行 + open の due）
    recent-decisions  直近の決定（打合せ記録の決定行 + 閉じた課題の `## 決定`。.claude/hooks/drops.py を使う）
    ファイルやマーカーが無い・drops.py を読めないときは注記だけ出して続行する（--check の警告数には数えない）。

検証（警告。--check で exit 1）: ID 重複・必須欄・許可値・due の形式・未知の画面 ID。
孤児の添付（open/ closed/ の `<ID>_…` で、同じフォルダに本体が無いもの）は警告行を出すが exit は変えない。
今日の日付はテスト用に環境変数 CLAUDE_SKELETON_TODAY（YYYY-MM-DD）で上書きできる。
"""
import datetime
import html
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

BASE_DIR = Path(__file__).parent
OPEN_DIR = BASE_DIR / "open"
CLOSED_DIR = BASE_DIR / "closed"
SCREENS_DIR = BASE_DIR / "screens"
OUT_PATH = BASE_DIR / "data.js"
ROOT = BASE_DIR.parent.parent.parent          # docs/案件/01_タスク管理 → 案件ルート
HOOKS_DIR = ROOT / ".claude" / "hooks"
SNAPSHOT_HTML = BASE_DIR.parent.parent / "プロジェクト概要.html"

VALID_STATUS = {"未着手", "進行中", "方針確定", "確認待ち", "保留", "完了"}
VALID_PRIORITY = {"最高", "高", "中", "低"}
VALID_KIND = {"タスク", "課題"}  # 分類（省略時はタスク）
VALID_SCREEN_STATUS = {"未着手", "実装中", "確認待ち", "完了", "保留"}
LIST_FIELDS = {"tags", "screens"}
PRIORITY_RANK = {"最高": 0, "高": 1, "中": 2, "低": 3}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

OPEN_ISSUES_MAX = 8
MILESTONES_MAX = 5
DECISIONS_MAX = 5


def today() -> datetime.date:
    s = os.environ.get("CLAUDE_SKELETON_TODAY", "").strip()
    if DATE_RE.match(s):
        try:
            return datetime.date.fromisoformat(s)
        except ValueError:
            pass
    return datetime.date.today()


def parse_date(s: str) -> datetime.date | None:
    s = (s or "").strip()
    if not DATE_RE.match(s):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    PyYAML を使わず Python 標準ライブラリのみでフロントマターをパースする。

    先頭の `---` から次の `---` までを取り出し、各行を最初の `:` で分割。
    tags / screens フィールドは `[a, b]` インラインリスト形式で扱う。
    本文はフロントマター終端以降の全文を返す。

    Returns:
        (fields dict, body str) のタプル。
        フロントマターが無ければ ({}, text) を返す。
    """
    lines = text.splitlines()

    if not lines or lines[0].strip() != "---":
        return {}, text

    # 終端 `---` を探す
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break

    if end is None:
        return {}, text

    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:])

    fields: dict = {}
    for line in fm_lines:
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()

        if key in LIST_FIELDS:
            # `[]` または `[a, b, c]` 形式
            inner = val.strip("[]").strip()
            if inner:
                fields[key] = [t.strip().strip("\"'") for t in inner.split(",") if t.strip()]
            else:
                fields[key] = []
        else:
            # 値が同一の囲み引用符（" または '）で挟まれていれば除去する。
            # 例: title: "[エピック] ..." → [エピック] ...
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("\"", "'"):
                val = val[1:-1]
            fields[key] = val

    return fields, body


def id_sort_key(item: dict) -> tuple:
    """
    ID を (prefix, number) でソートするキーを返す。
    例: QA-03 → ("QA", 3)、SCR-01 → ("SCR", 1)
    マッチしない場合は (id_string, 0) でフォールバック。
    """
    id_val = item.get("id", "")
    m = re.match(r"^([A-Za-z][A-Za-z0-9]*?)-?(\d+)$", id_val)
    if m:
        return (m.group(1).upper(), int(m.group(2)))
    return (id_val, 0)


def read_md_files(folder: Path):
    """フォルダ内の *.md を (path, fields, body) で順に返す。id の無い md（付随資料）は除く。"""
    if not folder.is_dir():
        return
    for md_path in sorted(folder.glob("*.md")):
        if md_path.name.startswith("."):
            continue  # .gitkeep など隠しファイルはスキップ
        try:
            text = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"⚠ 読み込み失敗 ({md_path.name}): {e}", file=sys.stderr)
            continue
        fields, body = parse_frontmatter(text)
        if not fields.get("id"):
            # frontmatter に id が無い md はタスク／画面ではなく付随資料
            # （「<ID>_内容_YYYYMMDD.md」併置規約）
            continue
        yield md_path, fields, body


def scan_folder(folder: Path, state: str) -> list[dict]:
    """
    フォルダ内の *.md を走査してタスクリストを返す。
    state はフォルダ名由来（"open" | "closed"）。
    """
    tasks = []
    for _, fields, body in read_md_files(folder):
        tasks.append({
            "id":       fields.get("id", ""),
            "title":    fields.get("title", ""),
            "area":     fields.get("area", ""),
            "status":   fields.get("status", ""),
            "priority": fields.get("priority", ""),
            "kind":     fields.get("kind", "") or "タスク",
            "epic":     fields.get("epic", ""),
            "owner":    fields.get("owner", ""),
            "due":      fields.get("due", ""),
            "decider":  fields.get("decider", ""),
            "tags":     fields.get("tags", []),
            "screens":  fields.get("screens", []),
            "source":   fields.get("source", ""),
            "created":  fields.get("created", ""),
            "updated":  fields.get("updated", ""),
            "closed":   fields.get("closed", ""),
            "state":    state,
            "body":     body,
        })
    return tasks


def scan_screens(folder: Path) -> list[dict]:
    """screens/ 内の *.md を走査して画面リストを返す。tasks は後で link_screens が埋める。"""
    screens = []
    for md_path, fields, body in read_md_files(folder):
        screens.append({
            "id":      fields.get("id", ""),
            "name":    fields.get("name", "") or md_path.stem,
            "path":    fields.get("path", ""),
            "status":  fields.get("status", ""),
            "owner":   fields.get("owner", ""),
            "tags":    fields.get("tags", []),
            "created": fields.get("created", ""),
            "updated": fields.get("updated", ""),
            "state":   "screen",
            "body":    body,
            "tasks":   [],
        })
    return screens


def link_screens(tasks: list[dict], screens: list[dict]) -> list[str]:
    """
    タスクの screens: から画面側の tasks を逆引き計算する。
    未知の SCR 参照は警告として返す。
    """
    warnings = []
    by_id = {s["id"]: s for s in screens}
    for t in tasks:
        for scr_id in t.get("screens", []):
            scr = by_id.get(scr_id)
            if scr is None:
                warnings.append(f"⚠ {t['id']}: screens に未知の画面 ID '{scr_id}'")
                continue
            scr["tasks"].append({
                "id":     t["id"],
                "title":  t["title"],
                "state":  t["state"],
                "status": t["status"],
                "kind":   t["kind"],
            })
    for s in screens:
        s["tasks"].sort(key=id_sort_key)
    return warnings


def validate_tasks(tasks: list[dict]) -> list[str]:
    """
    タスクリストをバリデーションして警告メッセージのリストを返す。
    警告は出すが処理は止めない。
    """
    warnings = []
    seen_ids: dict[str, str] = {}
    required_fields = ["id", "title", "area", "status", "priority"]

    for i, t in enumerate(tasks):
        label = t.get("id") or f"[index {i}]"

        # ID 重複チェック
        tid = t.get("id", "")
        if tid:
            if tid in seen_ids:
                warnings.append(
                    f"⚠ ID重複: {tid}（{seen_ids[tid]}/ と {t['state']}/ に同名ID）"
                )
            else:
                seen_ids[tid] = t["state"]

        # 必須欄欠落チェック
        for field in required_fields:
            if not t.get(field):
                warnings.append(f"⚠ {label}: 必須欄 '{field}' が空")

        # 許可値チェック（値がある場合のみ）
        s = t.get("status", "")
        if s and s not in VALID_STATUS:
            warnings.append(
                f"⚠ {label}: status '{s}' は許可値外"
                f"（許可: {'/'.join(sorted(VALID_STATUS))}）"
            )
        p = t.get("priority", "")
        if p and p not in VALID_PRIORITY:
            warnings.append(
                f"⚠ {label}: priority '{p}' は許可値外"
                f"（許可: {'/'.join(sorted(VALID_PRIORITY))}）"
            )
        k = t.get("kind", "")
        if k and k not in VALID_KIND:
            warnings.append(
                f"⚠ {label}: kind '{k}' は許可値外"
                f"（許可: {'/'.join(sorted(VALID_KIND))}）"
            )
        d = t.get("due", "")
        if d and parse_date(d) is None:
            warnings.append(f"⚠ {label}: due '{d}' は日付形式でない（YYYY-MM-DD の実在する日付。空でもよい）")

    return warnings


def validate_screens(screens: list[dict]) -> list[str]:
    """画面リストをバリデーションして警告メッセージのリストを返す。"""
    warnings = []
    seen: set[str] = set()
    for s in screens:
        label = s.get("id") or "[画面]"
        if s["id"] in seen:
            warnings.append(f"⚠ 画面ID重複: {s['id']}")
        seen.add(s["id"])
        if not s.get("name"):
            warnings.append(f"⚠ {label}: 必須欄 'name' が空")
        st = s.get("status", "")
        if not st:
            warnings.append(f"⚠ {label}: 必須欄 'status' が空")
        elif st not in VALID_SCREEN_STATUS:
            warnings.append(
                f"⚠ {label}: status '{st}' は許可値外"
                f"（許可: {'/'.join(sorted(VALID_SCREEN_STATUS))}）"
            )
    return warnings


def orphan_attachments() -> list[str]:
    """open/・closed/ の `<ID>_…` の付随資料で、同じフォルダに本体（その ID のタスク md）が無いもの。"""
    out = []
    for folder in (OPEN_DIR, CLOSED_DIR):
        if not folder.is_dir():
            continue
        ids = {fields.get("id", "").upper() for _, fields, _ in read_md_files(folder)}
        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.name.startswith("."):
                continue
            if f.suffix == ".md":
                try:
                    fields, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    fields = {}
                if fields.get("id"):
                    continue                    # 本体
            m = re.match(r"^([A-Za-z][A-Za-z0-9]*-\d+)_", f.name)
            if m and m.group(1).upper() not in ids:
                out.append(f"⚠ 孤児の添付: {folder.name}/{f.name}（同じフォルダに {m.group(1)} の本体が無い。"
                           "本体だけ動いた・ID の打ち間違いなら、本体と同じフォルダへ移すか名前を直す）")
    return out


# ---------------------------------------------------------------------------
# プロジェクト概要 HTML の自動欄
# ---------------------------------------------------------------------------

def open_items(tasks: list[dict]) -> list[dict]:
    return [t for t in tasks if t["state"] == "open"]


def due_cell(t: dict, now: datetime.date) -> str:
    d = parse_date(t.get("due", ""))
    if d is None:
        return html.escape(t.get("due", "") or "—")
    if d < now:
        return f"{d.isoformat()} <span class=\"chip hold\">期限切れ</span>"
    return d.isoformat()


def build_snapshot_html(tasks: list[dict], screens: list[dict]) -> str:
    """task-snapshot の断片（<p> と <table> のみ・外部依存なし）。課題は「決めてほしいこと」に出るので表から外す。"""
    now_s = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    now = today()
    opens = open_items(tasks)
    closed_count = sum(1 for t in tasks if t["state"] == "closed")
    issue_count = sum(1 for t in opens if t["kind"] == "課題")
    pending_count = sum(1 for t in opens if t["status"] == "確認待ち")
    active_count = sum(1 for t in opens if t["status"] == "進行中")
    overdue_count = sum(1 for t in opens if (parse_date(t.get("due", "")) or now) < now)
    scr_done = sum(1 for s in screens if s["status"] == "完了")

    top = sorted(
        [t for t in opens if t["kind"] != "課題"],
        key=lambda t: (PRIORITY_RANK.get(t["priority"], 9), id_sort_key(t)),
    )[:10]

    e = html.escape
    lines = [
        f"<p>生成: {now_s} ／ OPEN {len(opens)} 件（課題 {issue_count}・確認待ち {pending_count}・進行中 {active_count}"
        f"・期限切れ {overdue_count}）／ CLOSED {closed_count} 件</p>",
        f"<p>画面: 完了 {scr_done} / {len(screens)}</p>",
    ]
    if top:
        lines.append("<table>")
        lines.append("<tr><th>ID</th><th>タイトル</th><th>優先度</th><th>状態</th><th>期限</th></tr>")
        for t in top:
            lines.append(
                f"<tr><td>{e(t['id'])}</td><td>{e(t['title'])}</td>"
                f"<td>{e(t['priority'])}</td><td>{e(t['status'])}</td><td>{due_cell(t, now)}</td></tr>"
            )
        lines.append("</table>")
    else:
        lines.append("<p>OPEN のタスクはありません（課題は「決めてほしいこと」に出る）。</p>")
    return "\n".join(lines) + "\n"


def build_open_issues_html(tasks: list[dict]) -> str:
    """決めてほしいこと: open の課題。期限の近い順（期限なしは後ろ）→ 優先度 → ID。"""
    now = today()
    issues = [t for t in open_items(tasks) if t["kind"] == "課題"]
    far = datetime.date.max
    issues.sort(key=lambda t: (parse_date(t.get("due", "")) or far,
                               PRIORITY_RANK.get(t["priority"], 9), id_sort_key(t)))
    if not issues:
        return "<p class=\"muted\">いま決めてほしいことはありません。</p>\n"
    e = html.escape
    lines = ["<table>",
             "<tr><th class=\"id\">ID</th><th>問い</th><th>決める</th><th>期限</th><th>状態</th></tr>"]
    for t in issues[:OPEN_ISSUES_MAX]:
        lines.append(
            f"<tr><td class=\"id\">{e(t['id'])}</td><td>{e(t['title'])}</td>"
            f"<td>{e(t.get('decider', '') or '—')}</td><td>{due_cell(t, now)}</td><td>{e(t['status'])}</td></tr>"
        )
    lines.append("</table>")
    rest = len(issues) - OPEN_ISSUES_MAX
    if rest > 0:
        lines.append(f"<p class=\"note\">ほか {rest} 件（docs/案件/01_タスク管理/index.html）</p>")
    return "\n".join(lines) + "\n"


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def roadmap_milestones(text: str) -> list[dict]:
    """roadmap マーカー内の <tr> のうち、1 つ目の <td> が YYYY-MM-DD か YYYY-MM で始まり、状態が「完了」でない行。"""
    m = re.search(r"<!--\s*BEGIN:roadmap\s*-->(.*?)<!--\s*END:roadmap\s*-->", text, re.S)
    if not m:
        return []
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
        cells = [_strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if not cells:
            continue
        dm = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?", cells[0])
        if not dm:
            continue
        state = cells[2] if len(cells) >= 3 else " ".join(cells[1:])
        if "完了" in state:
            continue
        try:
            y, mo = int(dm.group(1)), int(dm.group(2))
            if dm.group(3):
                start = end = datetime.date(y, mo, int(dm.group(3)))
            else:
                start = datetime.date(y, mo, 1)
                end = (datetime.date(y + (mo == 12), mo % 12 + 1, 1) - datetime.timedelta(days=1))
        except ValueError:
            continue
        out.append({"label": cells[0], "start": start, "end": end,
                    "text": cells[1] if len(cells) >= 2 else "", "source": "ロードマップ"})
    return out


def build_milestones_html(tasks: list[dict], overview_text: str) -> str:
    """次の節目: 期限切れを先頭に（古い順）、続いて今日以降の近い順。合わせて 5 件。"""
    now = today()
    rows = roadmap_milestones(overview_text)
    for t in open_items(tasks):
        d = parse_date(t.get("due", ""))
        if d:
            rows.append({"label": d.isoformat(), "start": d, "end": d, "text": t["title"], "source": t["id"]})
    if not rows:
        return ("<p class=\"muted\">節目はまだありません（ロードマップの時期に日付を書くか、"
                "タスクに due を付けると出ます）。</p>\n")
    overdue = sorted([r for r in rows if r["end"] < now], key=lambda r: (r["start"], r["source"]))
    upcoming = sorted([r for r in rows if r["end"] >= now], key=lambda r: (r["start"], r["source"]))
    shown = (overdue + upcoming)[:MILESTONES_MAX]
    e = html.escape
    lines = ["<table>", "<tr><th style=\"width:9em\">日付</th><th>内容</th><th class=\"id\">出典</th></tr>"]
    for r in shown:
        mark = " <span class=\"chip hold\">期限切れ</span>" if r["end"] < now else ""
        lines.append(f"<tr><td>{e(r['label'])}{mark}</td><td>{e(r['text'])}</td><td class=\"id\">{e(r['source'])}</td></tr>")
    lines.append("</table>")
    rest = len(rows) - len(shown)
    if rest > 0:
        lines.append(f"<p class=\"note\">ほか {rest} 件</p>")
    return "\n".join(lines) + "\n"


def load_drops():
    """.claude/hooks/drops.py を import する。できなければ None。"""
    try:
        if str(HOOKS_DIR) not in sys.path:
            sys.path.insert(0, str(HOOKS_DIR))
        import drops  # type: ignore
        return drops
    except Exception:
        return None


def build_recent_decisions_html(drops) -> str:
    """直近の決定: 打合せ記録の決定行 + 閉じた課題の `## 決定`。新しい順に 5 件。"""
    found = drops.recent_decisions(str(ROOT), DECISIONS_MAX)
    if not found:
        return "<p class=\"muted\">まだ決定はありません。</p>\n"
    e = html.escape
    lines = ["<ul class=\"decisions\">"]
    for d in found:
        text = d["text"]
        if drops.looks_secret(text):
            text = "（秘密らしき文字列を含む行。出典を参照）"
        lines.append(f"<li><span class=\"d\">{e(d['date'])}</span><span>{e(text)}</span>"
                     f"<span class=\"ref\">{e(d['source'])}</span></li>")
    lines.append("</ul>")
    return "\n".join(lines) + "\n"


def replace_marker(text: str, name: str, fragment: str) -> str | None:
    """BEGIN:name 〜 END:name の内側を fragment に置き換える。マーカーの対が無ければ None。"""
    begin, end = f"<!-- BEGIN:{name} -->", f"<!-- END:{name} -->"
    b = text.find(begin)
    e = text.find(end, b + len(begin)) if b >= 0 else -1
    if b < 0 or e < 0:
        return None
    # END マーカーの行頭のインデントは保つ
    line_start = text.rfind("\n", 0, e) + 1
    indent = text[line_start:e] if text[line_start:e].strip() == "" else ""
    head = text[:b + len(begin)]
    tail = text[line_start:] if indent else text[e:]
    return head + "\n" + fragment + tail


def update_overview(tasks: list[dict], screens: list[dict], check: bool) -> None:
    """
    docs/プロジェクト概要.html の自動欄（マーカーの内側）を置換して書き戻す。
    ファイルやマーカーが無ければ注記のみで続行する（検証の警告数には数えない）。
    check=True のときは書き込まない。
    """
    if not SNAPSHOT_HTML.exists():
        print(f"注記: {SNAPSHOT_HTML} が無いため概要 HTML の自動欄はスキップ", file=sys.stderr)
        return
    text = SNAPSHOT_HTML.read_text(encoding="utf-8")
    drops = load_drops()
    sections = [
        ("task-snapshot", lambda: build_snapshot_html(tasks, screens)),
        ("open-issues", lambda: build_open_issues_html(tasks)),
        ("milestones", lambda: build_milestones_html(tasks, text)),
        ("recent-decisions", (lambda: build_recent_decisions_html(drops)) if drops else None),
    ]
    done, skipped = [], []
    new_text = text
    for name, make in sections:
        if f"<!-- BEGIN:{name} -->" not in new_text or f"<!-- END:{name} -->" not in new_text:
            skipped.append(f"{name}（マーカーなし）")
            continue
        if make is None:
            skipped.append(f"{name}（.claude/hooks/drops.py を読めない）")
            continue
        replaced = replace_marker(new_text, name, make())
        if replaced is None:
            skipped.append(f"{name}（マーカーの順が不正）")
            continue
        new_text = replaced
        done.append(name)
    for s in skipped:
        print(f"注記: {SNAPSHOT_HTML.name} の自動欄 {s} はスキップ", file=sys.stderr)
    if check:
        print(f"検証: {SNAPSHOT_HTML.name} の自動欄 {len(done)} 件（{'・'.join(done) or 'なし'}。--check のため未更新）")
        return
    if new_text != text:
        SNAPSHOT_HTML.write_bytes(new_text.encode("utf-8"))
    print(f"更新: {SNAPSHOT_HTML.name} の自動欄（{'・'.join(done) or 'なし'}）")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    check = "--check" in sys.argv[1:]

    tasks: list[dict] = []
    tasks.extend(scan_folder(OPEN_DIR, "open"))
    tasks.extend(scan_folder(CLOSED_DIR, "closed"))
    # ID 順（プレフィックス → 数値）で安定ソート
    tasks.sort(key=id_sort_key)

    screens = scan_screens(SCREENS_DIR)
    screens.sort(key=id_sort_key)

    # バリデーション警告を stderr に出力（処理は継続）
    warnings = validate_tasks(tasks) + validate_screens(screens) + link_screens(tasks, screens)
    for w in warnings:
        print(w, file=sys.stderr)
    # 孤児の添付は警告行だけ（exit は変えない）
    orphans = orphan_attachments()
    for w in orphans:
        print(w, file=sys.stderr)

    open_count = sum(1 for t in tasks if t["state"] == "open")
    closed_count = sum(1 for t in tasks if t["state"] == "closed")
    issue_open = sum(1 for t in tasks if t["state"] == "open" and t["kind"] == "課題")
    scr_done = sum(1 for s in screens if s["status"] == "完了")
    summary = (
        f"{len(tasks)}件（open {open_count}〔うち課題 {issue_open}〕 / closed {closed_count}）"
        f"、画面 {len(screens)}件（完了 {scr_done}）"
    )

    if check:
        extra = f"・孤児の添付 {len(orphans)} 件（exit に数えない）" if orphans else ""
        print(f"検証: {summary}、警告 {len(warnings)} 件{extra}")
        update_overview(tasks, screens, check=True)
        return 1 if warnings else 0

    # data.js 書き出し
    content = (
        "window.TASKS = "
        + json.dumps(tasks, ensure_ascii=False, indent=2)
        + ";\n"
        "window.SCREENS = "
        + json.dumps(screens, ensure_ascii=False, indent=2)
        + ";\n"
    )
    OUT_PATH.write_bytes(content.encode("utf-8"))
    print(f"生成: {summary}")

    update_overview(tasks, screens, check=False)
    write_work_log()
    return 0


def write_work_log() -> None:
    """作業ログ（docs/案件/作業ログ/）を正本から作り直す。scripts/work_log.py が無い・失敗しても止めない。"""
    script = ROOT / "scripts/work_log.py"
    if not script.is_file():
        return
    import subprocess
    try:
        r = subprocess.run([sys.executable, str(script)], cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        if r.stdout.strip():
            print(r.stdout.strip())
    except (OSError, subprocess.SubprocessError) as e:
        print(f"作業ログを生成できなかった: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
