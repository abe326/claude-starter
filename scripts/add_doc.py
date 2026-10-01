#!/usr/bin/env python3
"""設計書を 1 本ずつ足す（文書を育てる）。

使い方:
  python3 scripts/add_doc.py --list          足せる文書と、足したかどうかの一覧
  python3 scripts/add_doc.py 05 [06 …]       足す（template の写し・索引の行・影響マップの行をまとめて入れる）
  python3 scripts/add_doc.py 05 --dry-run    何をするかだけ出す

生成時の設計書は `01-概要.md` と索引（docs/設計書/README.md）だけ。02〜09 の元は docs/設計書/template/ にあり、
どの表にどの行を足すかは template/catalog.json が持つ。足すかどうかは Claude が候補を出し、利用者の承認を得てから
（sync-design-docs スキル）。

- 同じ番号の文書（NN-*。旧い名前・.md 以外も含む）が既にあれば足さない
- 写した文書の鮮度メタ行と作成日は今日の日付にする（「雛形のまま」は残す。節を埋めたら外れる）
- README の各表には、同じ行がまだ無いときだけ末尾に足す（利用者が直した行は触らない）
標準ライブラリのみ。プロジェクトルートはこのファイルの親の親。exit 0 = 成功、1 = 足せなかったものがある、2 = 使い方の誤り。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "docs/設計書"
TEMPLATE = DESIGN / "template"
CATALOG = TEMPLATE / "catalog.json"
README = DESIGN / "README.md"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def load_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8")).get("docs", {})


def existing(no: str) -> Path | None:
    """同じ番号の文書（拡張子・名前は問わない。旧い名前や .html の案件もある）。"""
    hits = sorted(p for p in DESIGN.glob(f"{no}-*") if p.is_file())
    return hits[0] if hits else None


def stamp(text: str, today: str) -> str:
    """冒頭の引用ブロックの「最終更新」「作成」の日付を今日にする。"""
    out = []
    for i, line in enumerate(text.splitlines(keepends=True)):
        if i < 10 and line.startswith(">") and ("最終更新" in line or "作成" in line):
            line = DATE_RE.sub(today, line, count=1)
        out.append(line)
    return "".join(out)


def add_rows(readme: str, heading: str, rows: list[str]) -> tuple[str, int]:
    """heading の直後の表の末尾に、まだ無い行を足す。(新しい本文, 足した行数)。表が無ければ足さない。"""
    lines = readme.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if l.rstrip("\n").startswith(heading)), None)
    if start is None:
        return readme, 0
    i = start + 1
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        if lines[i].startswith("## "):
            return readme, 0
        i += 1
    end = i
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    have = {l.strip() for l in lines[i:end]}
    new = [r for r in rows if r.strip() not in have]
    if not new:
        return readme, 0
    nl = "\r\n" if lines[end - 1].endswith("\r\n") else "\n"
    if not lines[end - 1].endswith(("\n", "\r\n")):
        lines[end - 1] += nl
    lines[end:end] = [r + nl for r in new]
    return "".join(lines), len(new)


def add(no: str, catalog: dict, dry: bool, today: str) -> tuple[bool, list[str]]:
    """(成功, 報告の行)。"""
    entry = catalog.get(no)
    if not entry:
        return False, [f"{no}: 一覧に無い番号（--list で確かめる）"]
    have = existing(no)
    if have:
        return False, [f"{no}: 既にある（{have.relative_to(ROOT).as_posix()}）。足さない"]
    src = TEMPLATE / entry["file"]
    if not src.is_file():
        return False, [f"{no}: 元の文書が無い（{src.relative_to(ROOT).as_posix()}）"]
    dst = DESIGN / entry["file"]
    report = [f"{no}: {dst.relative_to(ROOT).as_posix()} を足す"]
    readme = README.read_text(encoding="utf-8") if README.is_file() else ""
    for heading, rows in entry.get("rows", {}).items():
        readme, n = add_rows(readme, heading, rows)
        if n:
            report.append(f"    README「{heading.lstrip('# ')}」に {n} 行")
    if not dry:
        dst.write_bytes(stamp(src.read_text(encoding="utf-8"), today).encode("utf-8"))
        if README.is_file():
            README.write_bytes(readme.encode("utf-8"))
    return True, report


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    unknown = flags - {"--list", "--dry-run", "-h", "--help"}
    if unknown or "-h" in argv or "--help" in argv or (not args and "--list" not in flags):
        print(__doc__.strip())
        return 2 if unknown or not ("-h" in argv or "--help" in argv) else 0
    try:
        catalog = load_catalog()
    except (OSError, ValueError) as e:
        print(f"{CATALOG.relative_to(ROOT).as_posix()} を読めない: {e}")
        return 2
    if "--list" in flags:
        for no in sorted(catalog):
            have = existing(no)
            state = f"あり（{have.name}）" if have else "なし"
            print(f"{no}  {catalog[no]['file']:<20}  {state}")
        return 0
    today = date.today().isoformat()
    ok_all = True
    for no in args:
        no = no.zfill(2)
        ok, report = add(no, catalog, "--dry-run" in flags, today)
        ok_all &= ok
        print("\n".join(report))
    if "--dry-run" in flags:
        print("（--dry-run: 書き込んでいない）")
    else:
        print("次: python3 scripts/check_skeleton.py --docs で形を確かめる。節を埋めたら鮮度メタ行の「雛形のまま」を外す")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
