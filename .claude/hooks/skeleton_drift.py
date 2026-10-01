#!/usr/bin/env python3
"""スケルトンとのずれを 1 行にする（SessionStart の session_context.sh と check_skeleton.py が使う）。標準ライブラリのみ。

  - 前回入れた版: `.claude/skeleton.json`（init.py の記録）の version。無ければ CLAUDE.md 1 行目の刻印
  - スケルトンの今の版: 環境変数 PROJECT_SKELETON_DIR ＞ ~/.claude/skills/new-project の VERSION
  - 案件で直した仕組み: 記録の sha と今の中身が違う、仕組み（.claude/・scripts/・タスク管理の .py と index.html）のファイル数

使い方: python3 .claude/hooks/skeleton_drift.py [--json]
  出力は新しい版があるときだけ 1 行（無ければ何も出さない）。--json は状態をまとめて出す（検査用）。
スケルトンが見つからない・読めないときは何も出さない。常に exit 0。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

sys.dont_write_bytecode = True

RECORD = ".claude/skeleton.json"
STAMP_RE = re.compile(r"<!--\s*project-skeleton v(\d+\.\d+\.\d+)\s+generated\s+(\d{4}-\d{2}-\d{2})\s*-->")
MECHANISM_PREFIXES = (".claude/", "scripts/")
MECHANISM_TASK_DIR = "docs/案件/01_タスク管理/"


def version_tuple(v: str | None) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in (v or "").split("."))
    except ValueError:
        return (0,)


def is_mechanism(rel: str) -> bool:
    if rel.startswith(MECHANISM_PREFIXES):
        return True
    return rel.startswith(MECHANISM_TASK_DIR) and (rel.endswith(".py") or rel.endswith("/index.html"))


def read_record(root: str) -> dict | None:
    try:
        with open(os.path.join(root, RECORD), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def project_version(root: str) -> tuple[str | None, str]:
    """(前回入れた版, どこから読んだか: 記録 / 刻印 / 不明)。"""
    rec = read_record(root)
    if rec and isinstance(rec.get("version"), str):
        return rec["version"], "記録"
    try:
        with open(os.path.join(root, "CLAUDE.md"), encoding="utf-8") as f:
            head = "".join(f.readline() for _ in range(3))
    except (OSError, UnicodeDecodeError):
        return None, "不明"
    m = STAMP_RE.search(head)
    return (m.group(1), "刻印") if m else (None, "不明")


def skeleton_dir() -> str | None:
    env = os.environ.get("PROJECT_SKELETON_DIR")
    if env:
        return env
    home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "skills", "new-project") if home and home != "~" else None


def skeleton_version() -> str | None:
    d = skeleton_dir()
    if not d:
        return None
    try:
        with open(os.path.join(d, "VERSION"), encoding="utf-8") as f:
            v = f.read().strip()
    except OSError:
        return None
    return v if re.fullmatch(r"\d+\.\d+\.\d+", v) else None


def local_mechanisms(root: str) -> list[str]:
    """記録の sha と今の中身が違う仕組みのファイル（無いものは数えない）。記録が無ければ空。"""
    rec = read_record(root)
    files = rec.get("files") if rec else None
    if not isinstance(files, dict):
        return []
    out: list[str] = []
    for rel, entry in sorted(files.items()):
        if not is_mechanism(rel) or not isinstance(entry, dict) or not isinstance(entry.get("sha"), str):
            continue
        try:
            with open(os.path.join(root, rel), "rb") as f:
                data = f.read()
        except OSError:
            continue
        if hashlib.sha256(data).hexdigest() != entry["sha"]:
            out.append(rel)
    return out


def status(root: str) -> dict:
    cur, source = project_version(root)
    latest = skeleton_version()
    behind = bool(cur and latest and version_tuple(latest) > version_tuple(cur))
    return {"project": cur, "source": source, "skeleton": latest, "behind": behind,
            "local_mechanisms": local_mechanisms(root)}


def line(root: str) -> str:
    """新しい版があるときだけ 1 行（SessionStart 用）。"""
    s = status(root)
    if not s["behind"]:
        return ""
    msg = (f"スケルトン: v{s['project']} → v{s['skeleton']} が出ている。依頼された作業が一段落したら、利用者に 1 行で"
           "更新を提案し、了承されたら new-project スキルで更新する（手を入れていないファイルは自動で新しい版になる）")
    if s["local_mechanisms"]:
        msg += f"。案件で直した仕組み {len(s['local_mechanisms'])} 件は更新で混ぜる"
    return msg


def main() -> int:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        if "--json" in sys.argv[1:]:
            print(json.dumps(status(root), ensure_ascii=False))
        else:
            out = line(root)
            if out:
                print(out)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
