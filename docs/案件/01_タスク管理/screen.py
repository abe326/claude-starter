#!/usr/bin/env python3
"""
screen.py — 画面（screens/SCR-NN_<名前>.md）の作成と status 更新

Usage:
  python3 screen.py new "<名前>" [--path /x] [--owner 名前]   # 採番して作成
  python3 screen.py set <ID> <status>                          # status/updated を更新

例:
  python3 screen.py new "ログイン" --path /login
  python3 screen.py set SCR-01 実装中

status の許可値: 未着手 / 実装中 / 確認待ち / 完了 / 保留
どちらのサブコマンドも実行後に build.py を呼んで data.js を更新する。
フロントマター書き換えは close.py のユーティリティを流用する。
"""
import datetime
import re
import subprocess
import sys
from pathlib import Path

from close import find_md, rewrite_md

BASE_DIR = Path(__file__).parent
SCREENS_DIR = BASE_DIR / "screens"
PREFIX = "SCR"

VALID_SCREEN_STATUS = ("未着手", "実装中", "確認待ち", "完了", "保留")


def next_id() -> str:
    """screens/ 内の SCR-NN の最大連番 + 1 を採番する（2桁ゼロ埋め）。"""
    pattern = re.compile(r"^" + re.escape(PREFIX) + r"-(\d+)", re.IGNORECASE)
    max_num = 0
    for md in SCREENS_DIR.glob("*.md"):
        m = pattern.match(md.stem)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"{PREFIX}-{max_num + 1:02d}"


def slugify(name: str, id_: str) -> str:
    """画面名から安全なスラッグを生成する（最大40文字）。"""
    if not name:
        return id_
    slug = re.sub(r'[\s/\\:*?"<>|]+', "_", name)
    slug = slug[:40].strip("_")
    return slug if slug else id_


def make_template(id_: str, name: str, path: str, owner: str, today: str) -> str:
    """画面 md のフロントマター＋本文雛形を生成する。"""
    return (
        "---\n"
        f"id: {id_}\n"
        f"name: {name}\n"
        f"path: {path}\n"
        "status: 未着手\n"
        f"owner: {owner}\n"
        "tags: []\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "---\n"
        "\n"
        "## 概要\n"
        "（この画面の役割。誰が・何のために使うか）\n"
        "\n"
        "## 主要な操作\n"
        "- …\n"
        "\n"
        "## 参照（設計書・タスク）\n"
        "- 設計書: \n"
        "- 関連タスク: タスク側の frontmatter `screens:` にこの ID を書くと build.py が逆引きする\n"
    )


def take_option(args: list[str], name: str) -> str:
    """args から `--name 値` を取り出して値を返す（args は破壊的に更新）。無ければ空文字。"""
    if name not in args:
        return ""
    i = args.index(name)
    if i + 1 >= len(args):
        print(f"エラー: {name} には値が必要です", file=sys.stderr)
        sys.exit(1)
    val = args[i + 1]
    del args[i:i + 2]
    return val


def run_build() -> None:
    """data.js を更新する。"""
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "build.py")],
        capture_output=False,
    )
    if result.returncode != 0:
        print("警告: build.py の実行に失敗しました", file=sys.stderr)


def do_new(args: list[str]) -> None:
    args = list(args)
    path = take_option(args, "--path")
    owner = take_option(args, "--owner")
    if not args:
        print("Usage: python3 screen.py new \"<名前>\" [--path /x] [--owner 名前]", file=sys.stderr)
        sys.exit(1)
    name = args[0]

    SCREENS_DIR.mkdir(parents=True, exist_ok=True)
    id_ = next_id()
    today = datetime.date.today().isoformat()
    filename = f"{id_}_{slugify(name, id_)}.md"
    filepath = SCREENS_DIR / filename
    if filepath.exists():
        print(f"エラー: {filepath} はすでに存在します", file=sys.stderr)
        sys.exit(1)

    filepath.write_text(make_template(id_, name, path, owner, today), encoding="utf-8", newline="\n")
    print(f"作成: screens/{filename}")
    run_build()


def do_set(args: list[str]) -> None:
    if len(args) < 2:
        print("Usage: python3 screen.py set <ID> <status>", file=sys.stderr)
        print(f"status: {' / '.join(VALID_SCREEN_STATUS)}", file=sys.stderr)
        sys.exit(1)
    id_, status = args[0], args[1]
    if status not in VALID_SCREEN_STATUS:
        print(f"エラー: status '{status}' は許可値外（{' / '.join(VALID_SCREEN_STATUS)}）", file=sys.stderr)
        sys.exit(1)

    src = find_md(SCREENS_DIR, id_)
    if src is None:
        print(f"エラー: screens/ に ID '{id_}' が見つかりません", file=sys.stderr)
        sys.exit(1)

    today = datetime.date.today().isoformat()
    text = src.read_text(encoding="utf-8")
    src.write_text(rewrite_md(text, {"status": status, "updated": today}), encoding="utf-8", newline="\n")
    print(f"更新: {src.name}  status → {status}")
    run_build()


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in ("new", "set"):
        print("Usage: python3 screen.py new \"<名前>\" [--path /x] [--owner 名前]", file=sys.stderr)
        print("       python3 screen.py set <ID> <status>", file=sys.stderr)
        sys.exit(1)
    if args[0] == "new":
        do_new(args[1:])
    else:
        do_set(args[1:])


if __name__ == "__main__":
    main()
