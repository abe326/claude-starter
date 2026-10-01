#!/usr/bin/env python3
"""
close.py — タスクを open/ から closed/ へ移動（またはその逆）

Usage:
  python3 close.py <ID>             # クローズ: open/ → closed/
  python3 close.py --reopen <ID>    # 再オープン: closed/ → open/

例:
  python3 close.py QA-03
  python3 close.py --reopen QA-03

課題（kind: 課題）を閉じるときだけ、次を確かめて満たさなければ閉じずに止まる（exit 1）:
  1. `## 決定` の 1 行目（決定の内容）が空でない（HTML コメントは除く）
  2. `## 決定` に落ち先の行（→ 反映済: 01 §3 / → APP-03 / → 未決 QA-02 / → 取り下げ: 理由）が 1 行以上ある
  3. 落ち先の ID・文書が実在する（.claude/hooks/drops.py で確かめる。読めないときは 1・2 だけ）
タスクは従来どおり（決定を見ない）。決定日は closed 欄。

フロントマター書き換えユーティリティ（split_frontmatter / set_field / rewrite_md /
find_md）は screen.py からも import して使う。
"""
import datetime
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
OPEN_DIR = BASE_DIR / "open"
CLOSED_DIR = BASE_DIR / "closed"
ROOT = BASE_DIR.parent.parent.parent          # docs/案件/01_タスク管理 → 案件ルート
HOOKS_DIR = ROOT / ".claude" / "hooks"

DECISION_EXAMPLE = """書き方の例（課題 md の `## 決定`）:
  ## 決定
  対象は本社の正社員のみ（2026-09-30 打合せ / SH-02）
  → 反映済: 01 §3
  → APP-03
取り下げるときは 1 行目に理由、2 行目に `→ 取り下げ: 重複（QA-02 で扱う）`。
落ち先の書き方: docs/案件/02_打合せ/README.md。ID は new.py の出力から写す"""


# ---------------------------------------------------------------------------
# フロントマター書き換えユーティリティ
# ---------------------------------------------------------------------------

def split_frontmatter(text: str) -> tuple[str, list[str], str]:
    """
    テキストを (open_delimiter, fm_lines, rest) に分割する。

    open_delimiter: "---\n"（先頭行）
    fm_lines:       フロントマター本体の行リスト（keepends=True）
    rest:           "---\n" + 本文（フロントマター終端以降）

    フロントマターが無ければ ("", [], text) を返す。
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", [], text

    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break

    if end is None:
        return "", [], text

    open_delim = lines[0]                     # "---\n"
    fm_lines = lines[1:end]                   # フロントマター行（改行付き）
    rest = "".join(lines[end:])               # "---\n" + 本文

    return open_delim, fm_lines, rest


def set_field(fm_lines: list[str], field: str, value: str) -> list[str]:
    """
    fm_lines 内の `field:` 行を `field: value` に書き換えて返す。
    該当行が無ければ末尾に追加する。
    """
    result = []
    found = False
    for line in fm_lines:
        # 行頭が `field:` で始まる行を対象にする
        if re.match(rf"^{re.escape(field)}\s*:", line):
            result.append(f"{field}: {value}\n")
            found = True
        else:
            result.append(line)
    if not found:
        result.append(f"{field}: {value}\n")
    return result


def rewrite_md(text: str, updates: dict[str, str]) -> str:
    """
    md テキストのフロントマター内の複数フィールドを一括書き換えて返す。
    """
    open_delim, fm_lines, rest = split_frontmatter(text)
    if not open_delim:
        # フロントマターが無い場合は変更しない
        return text

    for field, value in updates.items():
        fm_lines = set_field(fm_lines, field, value)

    return open_delim + "".join(fm_lines) + rest


# ---------------------------------------------------------------------------
# ファイル検索
# ---------------------------------------------------------------------------

def find_md(folder: Path, id_: str) -> Path | None:
    """
    フォルダ内で ID に対応する「本体」の md ファイルを返す。
    ファイル名は `<ID>.md` または `<ID>_<slug>.md` 形式を想定。

    同じ ID prefix の付随資料（`<ID>_内容_YYYYMMDD.md` 等・フロントマター無し）が
    併置されている場合があるため、候補が複数あるときはフロントマターに
    `id: <ID>` を持つファイルを本体として優先する。
    """
    id_upper = id_.upper()
    candidates = []
    for md in folder.glob("*.md"):
        stem_upper = md.stem.upper()
        # 完全一致 or `<ID>_` で始まる
        if stem_upper == id_upper or stem_upper.startswith(f"{id_upper}_"):
            candidates.append(md)

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    for md in candidates:
        _, fm_lines, _ = split_frontmatter(md.read_text(encoding="utf-8"))
        for line in fm_lines:
            if re.match(rf"^id\s*:\s*{re.escape(id_)}\s*$", line.strip(), re.IGNORECASE):
                return md
    return candidates[0]


def move_attachments(src_dir: Path, dst_dir: Path, id_: str, main_md: Path) -> None:
    """
    タスク本体と同じ ID prefix の付随資料（`<ID>_*.md` / `.png` / `.html` 等）を
    本体と同じフォルダへ随伴移動する（付随資料の併置ルールに追随）。
    """
    id_upper = id_.upper()
    for f in sorted(src_dir.glob("*")):
        if f.name == main_md.name or not f.is_file():
            continue
        if f.stem.upper().startswith(f"{id_upper}_"):
            (dst_dir / f.name).write_bytes(f.read_bytes())
            f.unlink()
            print(f"付随資料: {f.name}  {src_dir.name}/ → {dst_dir.name}/")


# ---------------------------------------------------------------------------
# 課題の決着条件
# ---------------------------------------------------------------------------

def field_value(text: str, name: str) -> str:
    _, fm_lines, _ = split_frontmatter(text)
    for line in fm_lines:
        m = re.match(rf"^{re.escape(name)}\s*:(.*)$", line.rstrip("\n"))
        if m:
            return m.group(1).strip().strip("\"'")
    return ""


def _fallback_issue_problems(text: str) -> list[str]:
    """drops.py を import できないときの代替: 決定の 1 行目と `→` の行だけを自前で確かめる。"""
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    m = re.search(r"^##\s+決定\s*$(.*?)(?=^##\s|\Z)", body, flags=re.M | re.S)
    lines = [re.sub(r"^[-*+]\s+", "", l.strip()) for l in (m.group(1).splitlines() if m else [])]
    lines = [l for l in lines if l and not re.fullmatch(r"[（(].*[）)]", l)]
    out = []
    if not any(not l.startswith("→") for l in lines):
        out.append("`## 決定` の 1 行目（決定の内容）が空")
    if not any("→" in l and l.split("→")[-1].strip() for l in lines):
        out.append("`## 決定` に落ち先の行（→ 反映済: 01 §3 / → APP-03 / → 未決 QA-02 / → 取り下げ: 理由）が無い")
    return out


def issue_problems(text: str) -> list[str]:
    """課題を閉じられない理由の一覧（空なら閉じてよい）。"""
    try:
        if str(HOOKS_DIR) not in sys.path:
            sys.path.insert(0, str(HOOKS_DIR))
        import drops  # type: ignore
    except Exception:
        print("注記: .claude/hooks/drops.py を読めないため、落ち先の ID の実在は確かめていません", file=sys.stderr)
        return _fallback_issue_problems(text)
    root = str(ROOT)
    return drops.issue_problems(text, drops.load_items(root), root, drops.ledger_ids(root))


# ---------------------------------------------------------------------------
# タスクの完了条件（警告だけ。閉じるのは止めない）
# ---------------------------------------------------------------------------

def unchecked_conditions(text: str) -> list[str]:
    """`## 完了条件…` 節に残っている `- [ ]` の行（HTML コメントの中は見ない）。番号付きの旧い形は見ない。"""
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    m = re.search(r"^##\s+完了条件[^\n]*$(.*?)(?=^##\s|\Z)", body, flags=re.M | re.S)
    if not m:
        return []
    return [l.strip()[len("- [ ]"):].strip() for l in m.group(1).splitlines()
            if re.match(r"^\s*[-*]\s+\[\s\]", l)]


# ---------------------------------------------------------------------------
# クローズ / 再オープン
# ---------------------------------------------------------------------------

def do_close(id_: str, today: str) -> None:
    """open/ → closed/ に移動し、status/closed/updated を更新する。"""
    src = find_md(OPEN_DIR, id_)
    if src is None:
        print(f"エラー: open/ に ID '{id_}' が見つかりません", file=sys.stderr)
        sys.exit(1)

    text = src.read_text(encoding="utf-8")
    if field_value(text, "kind") == "課題":
        problems = issue_problems(text)
        if problems:
            print(f"エラー: 課題 {id_} は決着の記録が揃っていないため閉じません（open/ のまま）:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            print(DECISION_EXAMPLE, file=sys.stderr)
            sys.exit(1)
    else:
        left = unchecked_conditions(text)
        if left:
            print(f"警告: {id_} の完了条件にチェックの無いものがある（閉じるのは止めない）:", file=sys.stderr)
            for c in left:
                print(f"  - [ ] {c}", file=sys.stderr)
            print("  揃っているなら [x] に、該当しないなら `- [x] 該当なし: 理由` に直す。"
                  "揃わないまま閉じるなら、理由と引き継ぎ先を本文に 1 行", file=sys.stderr)
    new_text = rewrite_md(text, {
        "status":  "完了",
        "closed":  today,
        "updated": today,
    })

    CLOSED_DIR.mkdir(parents=True, exist_ok=True)
    dst = CLOSED_DIR / src.name
    dst.write_text(new_text, encoding="utf-8", newline="\n")
    src.unlink()
    print(f"クローズ: {src.name}  open/ → closed/")
    move_attachments(OPEN_DIR, CLOSED_DIR, id_, src)


def do_reopen(id_: str, today: str) -> None:
    """closed/ → open/ に移動し、status をリセット・closed をクリアする。"""
    src = find_md(CLOSED_DIR, id_)
    if src is None:
        print(f"エラー: closed/ に ID '{id_}' が見つかりません", file=sys.stderr)
        sys.exit(1)

    text = src.read_text(encoding="utf-8")
    new_text = rewrite_md(text, {
        "status":  "未着手",
        "closed":  "",
        "updated": today,
    })

    OPEN_DIR.mkdir(parents=True, exist_ok=True)
    dst = OPEN_DIR / src.name
    dst.write_text(new_text, encoding="utf-8", newline="\n")
    src.unlink()
    print(f"再オープン: {src.name}  closed/ → open/")
    move_attachments(CLOSED_DIR, OPEN_DIR, id_, src)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return
    if not args:
        print("Usage: python3 close.py <ID>", file=sys.stderr)
        print("       python3 close.py --reopen <ID>", file=sys.stderr)
        sys.exit(1)

    today = datetime.date.today().isoformat()

    if args[0] == "--reopen":
        if len(args) < 2:
            print("エラー: --reopen には ID が必要です", file=sys.stderr)
            sys.exit(1)
        do_reopen(args[1], today)
    else:
        do_close(args[0], today)

    # data.js を更新（先に自分の出力を出し切る）
    sys.stdout.flush()
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "build.py")],
        capture_output=False,
    )
    if result.returncode != 0:
        print("警告: build.py の実行に失敗しました", file=sys.stderr)


if __name__ == "__main__":
    main()
