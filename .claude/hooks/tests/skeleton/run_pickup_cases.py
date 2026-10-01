#!/usr/bin/env python3
"""hook-cases-pickup.txt を読み、模擬プロジェクトで pickup_cue / design_docs_reminder / pickup_check を順に流す。

使い方: python3 .claude/hooks/tests/run_pickup_cases.py [-v]
出力: NG の行 + 最後に `pass=N fail=M`。fail>0 なら exit 1。標準ライブラリのみ。
run-all.sh から呼ばれる。手順の書式は hook-cases-pickup.txt の冒頭。

ケースごとに tempfile.mkdtemp() で模擬プロジェクト（打合せ記録・タスク・課題・設計書 01/05・影響マップ・
概要 HTML・ハーネス台帳）と state の置き場を作る。模擬プロジェクトはこのファイルの中で作るので、
案件側で影響マップや設計書を書き換えてもケースは崩れない。一時ディレクトリは消さない（OS の一時領域に残る）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.dirname(os.path.dirname(HERE))
CASES = os.path.join(HERE, "hook-cases-pickup.txt")

MEETING = "docs/案件/02_打合せ"
OPEN = "docs/案件/01_タスク管理/open"

HOMEWORK_HEAD = "| 誰が | 何を | 期限 | 落ち先 |\n|:--|:--|:--|:--|\n"


def meeting(decisions: str, undecided: str = "", homework: str = "", heading: str = "決定") -> str:
    return (f"# 2026-09-23 模擬\n\n- 出席: 当方・発注側\n\n## {heading}\n{decisions}\n\n## 未決\n{undecided}\n\n"
            f"## 宿題\n{HOMEWORK_HEAD}{homework}\n\n## 議論の要点\n- 落ち先の要らない話\n")


def task_md(iid: str, title: str, kind: str = "タスク", state: str = "open") -> str:
    return (f"---\nid: {iid}\ntitle: {title}\narea: 横断\nkind: {kind}\nstatus: 未着手\npriority: 中\n"
            f"created: 2026-09-23\nupdated: 2026-09-23\nclosed:\n---\n\n## 概要\n{title}\n")


def overview(phase: str) -> str:
    if phase == "なし":
        block = "<div class=\"phase\"><div class=\"name\">着手</div></div>"
        return f"<html><body>{block}</body></html>\n"
    return ("<html><body>\n<!-- BEGIN:phase -->\n"
            f"<div class=\"phase\" data-phase=\"{phase}\">\n  <div class=\"name\">{phase}</div>\n</div>\n"
            "<!-- END:phase -->\n</body></html>\n")


FIXTURE_BASE = {
    "docs/設計書/README.md": (
        "# 設計書\n\n## 変えたもの → 一緒に直す正本\n\n| 変えたもの | 一緒に直す正本 | 備考 |\n|:--|:--|:--|\n"
        "| `src/auth/**`・`**/auth*` | `05-セキュリティ設計.md` | 認証 |\n"
        "| `tests/**` | `06-品質設計.md` | テスト |\n"
        "| 打合せ記録 | 人向けの行 | |\n"),
    "docs/設計書/01-overview.md": "# 01 概要\n\n## 1. 目的\n\n## 3. スコープ\n",
    "docs/設計書/05-セキュリティ設計.md": "# 05 セキュリティ設計\n\n## 3. 認証\n",
    "docs/設計書/06-品質設計.md": "# 06 品質設計\n",
    f"{OPEN}/APP-01_ログイン.md": task_md("APP-01", "ログイン"),
    f"{OPEN}/QA-01_派遣を含めるか.md": task_md("QA-01", "派遣社員を対象に含めるか", kind="課題"),
    "docs/案件/01_タスク管理/closed/.keep": "",
    "docs/ハーネス台帳.md": "# ハーネス台帳\n\n| ID | 状態 | 内容 | 定義先 |\n|:--|:--|:--|:--|\n",
    "docs/案件/確認依頼一覧.md": "# 確認依頼一覧\n",
    f"{MEETING}/README.md": "# 打合せ記録\n",
    f"{MEETING}/ok.md": meeting("- 対象は本社のみ → 反映済: 01 §3\n- 方式は後で → 候補: 05 §3",
                                "- 派遣を含めるか → 未決 QA-01",
                                "| 当方 | 案を出す | 2026-10-07 | → APP-01 |"),
    f"{MEETING}/nodrop.md": meeting("- 対象は本社のみ\n- 承認は 1 段階 → 反映済: 01 §3",
                                    "- 派遣を含めるか → 未決 QA-01",
                                    "| 当方 | 案を出す | 2026-10-07 | → APP-01 |"),
    f"{MEETING}/guess.md": meeting("- ログインを作る → APP-1"),
    f"{MEETING}/missing.md": meeting("- ログインを作る → APP-09"),
    f"{MEETING}/notissue.md": meeting("- 対象は本社のみ → 反映済: 01 §3", "- 派遣を含めるか → 未決 APP-01"),
    f"{MEETING}/old.md": meeting("- 対象は本社のみ", heading="決定事項"),
    f"{MEETING}/oldcol.md": ("# 2026-09-01 旧形式\n\n## 決定事項\n- 対象は本社のみ → 反映済: 01 §3\n\n## 宿題\n"
                             "| 誰が | 何を | 期限 | 関連タスク ID |\n|:--|:--|:--|:--|\n| 当方 | 案を出す | 2026-10-07 | APP-01 |\n"),
}


def expand(rel: str) -> str:
    if rel.startswith("02_打合せ/"):
        return f"{MEETING}/{rel[len('02_打合せ/'):]}"
    if rel.startswith("open/"):
        return f"{OPEN}/{rel[len('open/'):]}"
    return rel


def write(root: str, rel: str, text: str) -> None:
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def make_project(phase: str) -> str:
    root = tempfile.mkdtemp(prefix="pickup-case-")
    files = dict(FIXTURE_BASE)
    files["docs/プロジェクト概要.html"] = overview(phase)
    old = time.time() - 3600
    for rel, text in files.items():
        write(root, rel, text)
        os.utime(os.path.join(root, *rel.split("/")), (old, old))
    return root


def touch_file(root: str, rel: str) -> str:
    """ファイルがあれば mtime だけ今に、無ければ作る。絶対パスを返す。"""
    path = os.path.join(root, *rel.split("/"))
    if os.path.isfile(path):
        os.utime(path, None)
    else:
        base = os.path.basename(rel)
        if rel.startswith(OPEN + "/") and "_" in base:
            iid = base.split("_", 1)[0]
            write(root, rel, task_md(iid, os.path.splitext(base.split("_", 1)[1])[0]))
        else:
            write(root, rel, "x\n")
    return path


def run_hook(name: str, payload: str, env: dict) -> str:
    try:
        r = subprocess.run(["bash", os.path.join(HOOKS, name)], input=payload.encode("utf-8"),
                           capture_output=True, env=env, timeout=30)
        return r.stdout.decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return f"<実行できない: {e}>"


def long_text(n: int) -> str:
    unit = "議事: 対象範囲を確認した。移行はあとでやる。決定事項は次回に持ち越し。"
    return (unit * (n // len(unit) + 1))[:n]


def run_case(steps: list[str], phase: str, idx: int) -> str:
    root = make_project(phase)
    env = dict(os.environ)
    env.pop("CLAUDE_SKELETON_PHASE", None)
    env.pop("CLAUDE_PICKUP", None)
    env.pop("CLAUDE_PICKUP_MAX_BLOCKS", None)
    env["CLAUDE_PROJECT_DIR"] = root
    env["CLAUDE_DOCS_REMINDER_STATE_DIR"] = tempfile.mkdtemp(prefix="pickup-state-")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    sid: str | None = f"case-{idx}"
    out = ""
    for step in steps:
        op, _, arg = step.partition(":")
        base = {"session_id": sid} if sid else {}
        if op == "nosid":
            sid = None
            out = ""
        elif op.startswith("env"):
            k, _, v = arg.partition("=")
            env[k] = v
            out = ""
        elif op in ("prompt", "prompt-raw", "prompt-long"):
            text = long_text(int(arg)) if op == "prompt-long" else arg.replace("\\n", "\n")
            out = run_hook("pickup_cue.sh", json.dumps({**base, "hook_event_name": "UserPromptSubmit",
                                                        "prompt": text, "cwd": root}, ensure_ascii=False), env)
        elif op == "touch":
            path = touch_file(root, expand(arg))
            out = run_hook("design_docs_reminder.sh", json.dumps(
                {**base, "tool_name": "Write", "tool_input": {"file_path": path}}, ensure_ascii=False), env)
        elif op == "bash":
            touch_file(root, expand(arg))
            out = ""
        elif op in ("stop", "stop-active"):
            out = run_hook("pickup_check.sh", json.dumps({**base, "hook_event_name": "Stop", "cwd": root,
                                                          "stop_hook_active": op == "stop-active"},
                                                         ensure_ascii=False), env)
        elif op == "stopraw":
            out = run_hook("pickup_check.sh", arg, env)
        else:
            return f"<不明な手順: {step}>"
        time.sleep(0.01)
    return out


def classify(out: str) -> str:
    if not out:
        return "none"
    try:
        data = json.loads(out)
    except ValueError:
        return "invalid"
    if isinstance(data, dict) and data.get("decision") == "block":
        return "block"
    if isinstance(data, dict) and (data.get("hookSpecificOutput") or {}).get("additionalContext"):
        return "context"
    return "invalid"


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    verbose = "-v" in argv
    passed = failed = 0
    with open(CASES, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for n, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            failed += 1
            print(f"NG pickup {n}行目: 列が足りない: {line}")
            continue
        expect, steps = cols[0].strip(), cols[1].split(";")
        want = cols[2].strip() if len(cols) > 2 and cols[2].strip() != "-" else ""
        phase = cols[3].strip() if len(cols) > 3 and cols[3].strip() != "-" else "Sketch"
        note = cols[4].strip() if len(cols) > 4 else ""
        out = run_case(steps, phase, n)
        got = classify(out)
        ok = got == expect and (not want or want in out)
        if ok:
            passed += 1
            if verbose:
                print(f"ok pickup {n}行目 {expect} {note}")
        else:
            failed += 1
            print(f"NG pickup {n}行目 expect={expect} got={got} want={want or '-'} phase={phase} : {note}\n"
                  f"    手順: {cols[1]}\n    出力: {out[:400]}")
    print(f"pass={passed} fail={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
