#!/usr/bin/env python3
"""check_drops.py・close.py・new.py・build.py の異常系を模擬プロジェクトで流す（付録 A §6.2 の表）。

使い方: python3 .claude/hooks/tests/run_drops_cases.py [-v]
出力: NG の行（-v なら OK も）+ 最後に `pass=N fail=M`。fail>0 なら exit 1。標準ライブラリのみ。
run-all.sh から呼ばれる。

ケースごとに tempfile.mkdtemp() へ drops-cases/project/ を複製し（dot-claude/ → .claude/）、案件の実物の
スクリプト（.claude/hooks/drops.py・phase.py、scripts/check_drops.py、docs/案件/01_タスク管理/new.py・close.py・build.py）
を入れてから、ケースの表の files を足して cmd を流す。フェーズは CLAUDE_SKELETON_PHASE、今日は CLAUDE_SKELETON_TODAY で固定。
一時ディレクトリは消さない（OS の一時領域に残る）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
BASE = os.path.join(HERE, "drops-cases", "project")
TODAY = "2026-09-23"

TM = "docs/案件/01_タスク管理"
MTG = "docs/案件/02_打合せ"
OV = "docs/プロジェクト概要.html"
SCRIPTS = [
    ".claude/hooks/drops.py", ".claude/hooks/phase.py", "scripts/check_drops.py",
    f"{TM}/new.py", f"{TM}/close.py", f"{TM}/build.py",
]
HW = "| 誰が | 何を | 期限 | 落ち先 |\n|:--|:--|:--|:--|\n"


def meeting(decisions: str = "", undecided: str = "", homework: str = "") -> str:
    return (f"# 2026-09-23 模擬\n\n- 出席: 当方・発注側\n\n## 決定\n{decisions}\n\n## 未決\n{undecided}\n\n"
            f"## 宿題\n{HW}{homework}\n\n## 議論の要点\n- 落ち先の要らない話\n")


def meeting_h3(decisions: str = "", homework: str = "") -> str:
    """tl;dv 型: `## 要約` の下に `### 決定事項` `### 宿題`。関係の無い H3 の箇条は拾わない。"""
    return (f"# 2026-09-23 模擬（H3）\n\n## 要約\n\n### 概要\n- 落ち先の要らない話\n\n### 決定事項\n{decisions}\n\n"
            f"### 宿題\n{HW}{homework}\n\n### 次回\n- 次回も同じ時間\n\n## 文字起こし\n- 話した内容\n")


def issue(iid: str, decision: str, state_closed: bool = False, due: str = "") -> str:
    closed = TODAY if state_closed else ""
    return (f"---\nid: {iid}\ntitle: {iid} の問い\narea: 横断\nkind: 課題\nstatus: {'完了' if closed else '未着手'}\n"
            f"priority: 中\ndecider: SH-02\nepic: \nowner: \ndue: {due}\ntags: []\nscreens: []\nsource: \n"
            f"created: 2026-09-20\nupdated: 2026-09-20\nclosed: {closed}\n---\n\n## 概要\n問い\n\n## 決定\n{decision}\n\n## 過去の経緯\n")


def task(iid: str, due: str = "", title: str = "作業") -> str:
    return (f"---\nid: {iid}\ntitle: {title}\narea: アプリ\nkind: タスク\nstatus: 未着手\npriority: 中\nepic: \nowner: \n"
            f"due: {due}\ntags: []\nscreens: []\nsource: \ncreated: 2026-09-20\nupdated: 2026-09-20\nclosed: \n---\n\n## 概要\n{title}\n")


QA01_OPEN = f"{TM}/open/QA-01_派遣を含めるか.md"
QA01_CLOSED = f"{TM}/closed/QA-01_派遣を含めるか.md"
CD = ["python", "scripts/check_drops.py"]

# 各ケース: id・phase・files（足す／上書きするファイル。bytes も可）・skip（複製しないファイル）・cmd・期待
#   exit / out（stdout に含む）/ out_not / err（stderr に含む）/ quiet（stdout の完全一致）/ exists / absent / has（{パス: [含む]}）
CASES: list[dict] = [
    dict(id="1", note="模擬プロジェクトそのまま（課題 QA-01 が open）", cmd=CD + ["--quiet"], quiet="0 0 0 1 0"),
    dict(id="1b", note="Build でも同じ", phase="Build", cmd=CD + ["--strict"], exit=0, out=["警告 0 件・情報 0 件"]),
    dict(id="2", note="落ち先なしの決定 1 行（Sketch）→ 情報", files={f"{MTG}/20260923_a.md": meeting("- 対象は本社のみ")},
         cmd=CD + ["--strict"], exit=0, out=["情報 docs/案件/02_打合せ/20260923_a.md:", "落ち先なし", "警告 0 件・情報 1 件"]),
    dict(id="2q", note="--quiet の 3 つ目は落ち先なし数", files={f"{MTG}/20260923_a.md": meeting("- 対象は本社のみ")},
         cmd=CD + ["--quiet"], quiet="0 1 1 1 0"),
    dict(id="2h", note="H3 の ### 決定事項 も読む（落ち先なし 1 行。概要・次回・文字起こしの箇条は数えない）",
         files={f"{MTG}/20260923_h.md": meeting_h3("- 対象は本社のみ")},
         cmd=CD + ["--quiet"], quiet="0 1 1 1 0"),
    dict(id="2h2", note="H3 の決定・宿題に落ち先あり → 何も出さない",
         files={f"{MTG}/20260923_h.md": meeting_h3("- 対象は本社のみ → 反映済: 01 §3", "| 当方 | 見積もり | 9/30 | → APP-01 |\n")},
         cmd=CD + ["--strict"], exit=0, out=["警告 0 件・情報 0 件"]),
    dict(id="3", note="同（Build）→ 警告・--strict で exit 1", phase="Build",
         files={f"{MTG}/20260923_a.md": meeting("- 対象は本社のみ")}, cmd=CD + ["--strict"], exit=1, out=["警告 1 件・情報 0 件"]),
    dict(id="4", note="→ APP-1 は Sketch でも警告", files={f"{MTG}/20260923_a.md": meeting("- ログインを作る → APP-1")},
         cmd=CD + ["--strict"], exit=1, out=["書式違反の ID「APP-1」"]),
    dict(id="5", note="→ APP-09 は ID 不在", files={f"{MTG}/20260923_a.md": meeting("- ログインを作る → APP-09")},
         cmd=CD, out=["ID 不在「APP-09」"]),
    dict(id="6", note="→ 未決 APP-01（タスク）は課題でない", files={f"{MTG}/20260923_a.md": meeting("", "- 派遣を含めるか → 未決 APP-01")},
         cmd=CD, out=["課題でない「APP-01」"]),
    dict(id="7", note="文書不在 2（10 §1・ADR-099）",
         files={f"{MTG}/20260923_a.md": meeting("- 甲 → 反映済: 10 §1\n- 乙 → 反映済: ADR-099\n- 丙 → 反映済: ADR-003、01 §3")},
         cmd=CD, out=["文書不在「10」", "文書不在「ADR-099」", "警告 2 件"]),
    dict(id="8", note="記録のみ（理由なし）は書式違反",
         files={f"{MTG}/20260923_a.md": meeting("- 甲 → 反映済: 記録のみ\n- 乙 → 反映済: 記録のみ（議事の共有だけ）")},
         cmd=CD, out=["記録のみ", "警告 1 件"]),
    dict(id="8b-1", note="候補: 05 §3 は Sketch で何も出さない", files={f"{MTG}/20260923_a.md": meeting("- 方式 → 候補: 05 §3")},
         cmd=CD, out=["警告 0 件・情報 0 件"]),
    dict(id="8b-2", note="候補: 05 §3 は Build で情報「候補のまま」", phase="Build",
         files={f"{MTG}/20260923_a.md": meeting("- 方式 → 候補: 05 §3")}, cmd=CD, out=["候補のまま", "警告 0 件・情報 1 件"]),
    dict(id="8b-3", note="候補: 07 §4 は、07 がまだ無くても template/ にあれば正しい落ち先（文書を育てる）",
         files={f"{MTG}/20260923_a.md": meeting("- 反映の手順 → 候補: 07 §4"), "docs/設計書/template/07-変更と反映.md": "# 07\n"},
         cmd=CD, out=["警告 0 件"]),
    dict(id="8b-4", note="候補: 07 §4 で template/ にも無ければ文書不在", files={f"{MTG}/20260923_a.md": meeting("- 反映の手順 → 候補: 07 §4")},
         cmd=CD, out=["文書不在「07」"]),
    dict(id="8b-5", note="反映済: 07 §4 は template/ にあっても文書不在（反映済は実在する文書だけ）",
         files={f"{MTG}/20260923_a.md": meeting("- 反映の手順 → 反映済: 07 §4"), "docs/設計書/template/07-変更と反映.md": "# 07\n"},
         cmd=CD, out=["文書不在「07」"]),
    dict(id="8c", note="台帳に無い HN-07", files={f"{MTG}/20260923_a.md": meeting("- 今後 rm -rf を使わない → ハーネス候補 HN-07\n- 同 → ハーネス候補 HN-01")},
         cmd=CD, out=["ID 不在「HN-07」", "警告 1 件"]),
    dict(id="9", note="closed/ に決定が空の課題（手で移した）", files={f"{TM}/closed/QA-02_x.md": issue("QA-02", "", True)},
         cmd=CD, out=["閉じた課題 QA-02", "1 行目", "落ち先の行"]),
    dict(id="10-1", note="設計書の（未決 QA-01）が閉じた課題（Sketch → 情報）",
         files={QA01_CLOSED: issue("QA-01", "含めない\n→ 反映済: 01 §3", True)}, skip=[QA01_OPEN],
         cmd=CD, out=["情報 docs/設計書/05-セキュリティ設計.md:", "決着済みの未決を参照", "警告 0 件"]),
    dict(id="10-2", note="同（Build → 警告）", phase="Build",
         files={QA01_CLOSED: issue("QA-01", "含めない\n→ 反映済: 01 §3", True)}, skip=[QA01_OPEN],
         cmd=CD, out=["警告 docs/設計書/05-セキュリティ設計.md:", "警告 1 件"]),
    dict(id="10-3", note="設計書の（未決 QA-9）は書式違反、（未決 QA-07）は ID 不在",
         files={"docs/設計書/01-overview.md": "# 01\n\n## 3. スコープ\n- 範囲（未決 QA-9）\n- 期間（未決 QA-07）\n"},
         cmd=CD, out=["（未決 QA-9）: 書式違反", "（未決 QA-07）: ID 不在"]),
    dict(id="11-1", note="確認依頼の [ ] 行に ID なし（Sketch → 情報）",
         files={"docs/案件/確認依頼一覧.md": "# 確認依頼一覧\n\n## 1. お願い\n\n- [ ] **文言を変えました** — 開く場所: ログイン画面\n"},
         cmd=CD, out=["情報 docs/案件/確認依頼一覧.md:5", "ID が無い"]),
    dict(id="11-2", note="同（Build → 警告）", phase="Build",
         files={"docs/案件/確認依頼一覧.md": "# 確認依頼一覧\n\n## 1. お願い\n\n- [ ] **文言を変えました** — 開く場所: ログイン画面\n"},
         cmd=CD + ["--strict"], exit=1, out=["警告 docs/案件/確認依頼一覧.md:5"]),
    dict(id="11-3", note="確認依頼の ID 不在は Sketch でも警告・閉じた課題は情報",
         files={"docs/案件/確認依頼一覧.md": "# 確認依頼一覧\n\n## 1. お願い\n\n- [ ] **甲**（2026-09-23 / APP-09）\n- [ ] **乙**（2026-09-23 / QA-02）\n",
                f"{TM}/closed/QA-02_x.md": issue("QA-02", "決めた\n→ 反映済: 01 §3", True)},
         cmd=CD, out=["警告 docs/案件/確認依頼一覧.md:5", "ID 不在「APP-09」", "課題は閉じたのに [ ] のまま"]),
    dict(id="12", note="due: 2026-13-01 は build.py 警告・--check exit 1",
         files={f"{TM}/open/APP-02_x.md": task("APP-02", "2026-13-01")},
         cmd=["python", f"{TM}/build.py", "--check"], exit=1, err=["due '2026-13-01'"]),
    dict(id="13-1", note="due が昨日の open タスク → 情報（期限切れ）",
         files={f"{TM}/open/APP-02_x.md": task("APP-02", "2026-09-22", "移行範囲の案を出す")},
         cmd=CD + ["--quiet"], quiet="0 1 0 1 1"),
    dict(id="13-2", note="同 → 概要 HTML「次の節目」の先頭に期限切れ",
         files={f"{TM}/open/APP-02_x.md": task("APP-02", "2026-09-22", "移行範囲の案を出す")},
         cmd=["python", f"{TM}/build.py"], exit=0,
         has={OV: [re.compile(r"BEGIN:milestones -->\s*<table>\s*<tr>.*?</tr>\s*<tr><td>2026-09-22 <span class=\"chip hold\">期限切れ</span></td><td>移行範囲の案を出す</td>", re.S)]}),
    dict(id="14", note="設計書に旧形式 U-01 → 情報", files={"docs/設計書/01-overview.md": "# 01\n\n## 3. スコープ\n- 範囲（未決 U-01）\n"},
         cmd=CD, out=["旧形式の未決 ID U-01", "警告 0 件・情報 1 件"]),
    dict(id="15", note="見出しも表も無い打合せ記録・UTF-8 でないファイルは 0 件扱い",
         files={f"{MTG}/20260923_a.md": "ただのメモ。→ も見出しも無い\n", f"{MTG}/20260923_b.md": "## 決定\n- 対象は本社のみ\n".encode("cp932")},
         cmd=CD + ["--strict"], exit=0, out=["警告 0 件・情報 0 件"]),
    dict(id="16", note="close.py QA-01（決定が空）→ exit 1・open/ のまま・足りないものと例",
         cmd=["python", f"{TM}/close.py", "QA-01"], exit=1, err=["1 行目", "落ち先の行", "書き方の例"],
         exists=[QA01_OPEN], absent=[QA01_CLOSED]),
    dict(id="17", note="close.py QA-01（決定 + 反映済: 01 §3）→ closed/ へ",
         files={QA01_OPEN: issue("QA-01", "含めない（2026-09-23 打合せ / SH-02）\n→ 反映済: 01 §3")},
         cmd=["python", f"{TM}/close.py", "QA-01"], exit=0, exists=[QA01_CLOSED], absent=[QA01_OPEN],
         has={QA01_CLOSED: ["status: 完了"]}),
    dict(id="17b", note="close.py QA-01（落ち先の ID 不在）→ 閉じない",
         files={QA01_OPEN: issue("QA-01", "含めない\n→ APP-09")},
         cmd=["python", f"{TM}/close.py", "QA-01"], exit=1, err=["ID 不在「APP-09」"], exists=[QA01_OPEN]),
    dict(id="17c", note="close.py QA-01（雛形の案内「（…）」だけ）→ 閉じない",
         files={QA01_OPEN: issue("QA-01", "（未決の間は空欄のまま。決着したら 1 行目に決定内容）")},
         cmd=["python", f"{TM}/close.py", "QA-01"], exit=1, err=["1 行目"], exists=[QA01_OPEN]),
    dict(id="18", note="close.py QA-01（取り下げ: 重複）→ closed/ へ",
         files={QA01_OPEN: issue("QA-01", "QA-02 と重複のため取り下げ\n→ 取り下げ: 重複")},
         cmd=["python", f"{TM}/close.py", "QA-01"], exit=0, exists=[QA01_CLOSED]),
    dict(id="19", note="close.py APP-01（タスク）は決定を見ない",
         cmd=["python", f"{TM}/close.py", "APP-01"], exit=0, exists=[f"{TM}/closed/APP-01_ログイン.md"]),
    dict(id="19b", note="drops.py が無いとき close.py は決定の 1 行目と → だけを見て閉じる（ID の実在は見ない）",
         skip=[".claude/hooks/drops.py"], files={QA01_OPEN: issue("QA-01", "含めない\n→ APP-09")},
         cmd=["python", f"{TM}/close.py", "QA-01"], exit=0, err=["ID の実在は確かめていません"], exists=[QA01_CLOSED]),
    dict(id="19c", note="drops.py が無いときも決定が空なら閉じない", skip=[".claude/hooks/drops.py"],
         cmd=["python", f"{TM}/close.py", "QA-01"], exit=1, exists=[QA01_OPEN]),
    dict(id="20", note="new.py --decided だけ（--to なし）→ exit 2・何も作らない",
         cmd=["python", f"{TM}/new.py", "横断", "対象範囲", "--decided", "本社のみ"], exit=2, err=["--to"],
         absent=[f"{TM}/open/QA-02_対象範囲.md", f"{TM}/closed/QA-02_対象範囲.md"]),
    dict(id="21", note="new.py --decided --to → closed/ に課題、決定 2 行、直近の決定の先頭",
         cmd=["python", f"{TM}/new.py", "横断", "対象範囲", "--decided", "本社のみ", "--to", "反映済: 01 §3"], exit=0,
         out=["QA-02\n"], exists=[f"{TM}/closed/QA-02_対象範囲.md"], absent=[f"{TM}/open/QA-02_対象範囲.md"],
         has={f"{TM}/closed/QA-02_対象範囲.md": ["## 決定\n本社のみ\n→ 反映済: 01 §3\n", "kind: 課題"],
              OV: [re.compile(r"BEGIN:recent-decisions -->\s*<ul class=\"decisions\">\s*<li><span class=\"d\">[0-9-]+</span><span>本社のみ</span><span class=\"ref\">QA-02</span>")]}),
    dict(id="21b", note="new.py --decided --to（ID 不在）→ exit 2・何も作らない",
         cmd=["python", f"{TM}/new.py", "横断", "対象範囲", "--decided", "本社のみ", "--to", "APP-09"], exit=2,
         err=["ID 不在「APP-09」"], absent=[f"{TM}/open/QA-02_対象範囲.md", f"{TM}/closed/QA-02_対象範囲.md"]),
    dict(id="22", note="new.py --due 10/7 → exit 2", cmd=["python", f"{TM}/new.py", "横断", "x", "--due", "10/7"], exit=2,
         absent=[f"{TM}/open/QA-02_x.md"]),
    dict(id="23", note="概要 HTML に open-issues マーカーが無い → 注記だけ・--check は exit 0",
         files={OV: "<html><body>\n<!-- BEGIN:task-snapshot -->\n<!-- END:task-snapshot -->\n</body></html>\n"},
         cmd=["python", f"{TM}/build.py", "--check"], exit=0, err=["open-issues（マーカーなし）"]),
    dict(id="24", note="ロードマップの 2027-04（未着手）だけが次の節目に出る（例示・完了は出ない）",
         cmd=["python", f"{TM}/build.py"], exit=0,
         has={OV: ["<td>2027-04</td><td>新システムへ切り替え</td><td class=\"id\">ロードマップ</td>"]},
         has_not={OV: ["例示の行は出ない</td><td class=\"id\">", "完了した節目は出ない</td><td class=\"id\">"]}),
    dict(id="25", note="決めてほしいこと: open の課題が決める人つきで出る・課題は task-snapshot の表から外れる",
         cmd=["python", f"{TM}/build.py"], exit=0,
         has={OV: [re.compile(r"BEGIN:open-issues -->\s*<table>.*<td class=\"id\">QA-01</td><td>派遣社員を対象に含めるか</td><td>SH-02</td>", re.S)]},
         has_not={OV: ["<tr><td>QA-01</td>"]}),
    dict(id="26", note="孤児の添付は build.py --check で警告行（exit は変えない）",
         files={f"{TM}/open/APP-07_比較_20260923.md": "# 比較\n"},
         cmd=["python", f"{TM}/build.py", "--check"], exit=0, err=["孤児の添付: open/APP-07_比較_20260923.md"]),
    dict(id="27", note="--file は 1 ファイルだけ", files={f"{MTG}/20260923_a.md": meeting("- 甲"), f"{MTG}/20260923_b.md": meeting("- 乙 → APP-09")},
         cmd=CD + ["--file", f"{MTG}/20260923_a.md"], out=["20260923_a.md", "警告 0 件・情報 1 件"], out_not=["20260923_b.md"]),
    dict(id="28", note="--refs 05 は 05 が参照する未決の一覧", cmd=CD + ["--refs", "05"],
         out=["docs/設計書/05-セキュリティ設計.md:7 QA-01（未決）「派遣社員を対象に含めるか」 ／ 決める: SH-02"]),
    dict(id="29", note="--json は機械向け", files={f"{MTG}/20260923_a.md": meeting("- 甲 → APP-1")},
         cmd=CD + ["--json"], json_counts={"warn": 1, "info": 0}),
    dict(id="30", note="宿題の表: 落ち先列の → と旧列「関連タスク ID」",
         files={f"{MTG}/20260923_a.md": meeting("", "", "| 当方 | 案を出す | 2026-10-07 | → APP-01 |\n| 当方 | 見積もる | 2026-10-07 | |"),
                f"{MTG}/20260901_old.md": "# 旧\n\n## 決定事項\n- 甲 → 反映済: 01 §3\n\n## 宿題\n| 誰が | 何を | 期限 | 関連タスク ID |\n|:--|:--|:--|:--|\n| 当方 | 案 | 2026-10-07 | APP-01 |\n"},
         cmd=CD, out=["宿題「見積もる」: 落ち先なし", "警告 0 件・情報 1 件"]),
]


def build_project(case: dict) -> str:
    tmp = tempfile.mkdtemp(prefix="drops-case-")
    skip = set(case.get("skip", []))
    for dirpath, _dirs, files in os.walk(BASE):
        for fn in files:
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, BASE).replace("\\", "/")
            if rel == "README.md":
                continue
            if rel.startswith("dot-claude/"):
                rel = ".claude/" + rel[len("dot-claude/"):]
            if rel in skip:
                continue
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
    for rel in SCRIPTS:
        if rel in skip:
            continue
        dst = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, rel), dst)
    for rel, content in case.get("files", {}).items():
        dst = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(content if isinstance(content, bytes) else content.encode("utf-8"))
    return tmp


def run_case(case: dict) -> list[str]:
    tmp = build_project(case)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               CLAUDE_SKELETON_TODAY=TODAY, CLAUDE_SKELETON_PHASE=case.get("phase", "Sketch"))
    cmd = [sys.executable if c == "python" else c for c in case["cmd"]]
    r = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    bad = []
    if "exit" in case and r.returncode != case["exit"]:
        bad.append(f"exit {r.returncode}（期待 {case['exit']}）")
    if "quiet" in case and r.stdout.strip() != case["quiet"]:
        bad.append(f"stdout {r.stdout.strip()!r}（期待 {case['quiet']!r}）")
    for s in case.get("out", []):
        if s not in r.stdout:
            bad.append(f"stdout に {s!r} が無い")
    for s in case.get("out_not", []):
        if s in r.stdout:
            bad.append(f"stdout に {s!r} がある")
    for s in case.get("err", []):
        if s not in r.stderr:
            bad.append(f"stderr に {s!r} が無い")
    for rel in case.get("exists", []):
        if not os.path.isfile(os.path.join(tmp, rel)):
            bad.append(f"{rel} が無い")
    for rel in case.get("absent", []):
        if os.path.exists(os.path.join(tmp, rel)):
            bad.append(f"{rel} がある")
    for key, want in (("has", True), ("has_not", False)):
        for rel, pats in case.get(key, {}).items():
            try:
                text = open(os.path.join(tmp, rel), encoding="utf-8").read()
            except OSError:
                bad.append(f"{rel} を読めない")
                continue
            for p in pats:
                hit = bool(p.search(text)) if hasattr(p, "search") else (p in text)
                if hit != want:
                    shown = p.pattern if hasattr(p, "pattern") else p
                    bad.append(f"{rel} に {shown[:60]!r} が{'無い' if want else 'ある'}")
    if "json_counts" in case:
        try:
            counts = json.loads(r.stdout)["counts"]
            for k, v in case["json_counts"].items():
                if counts.get(k) != v:
                    bad.append(f"json counts[{k}]={counts.get(k)}（期待 {v}）")
        except (ValueError, KeyError) as e:
            bad.append(f"JSON を読めない: {e}")
    if bad:
        tail = (r.stdout.strip().splitlines() or [""])[-1][:120]
        bad.append(f"（場所: {tmp} ／ stdout 末尾: {tail!r} ／ stderr: {r.stderr.strip()[:200]!r}）")
    return bad


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    verbose = "-v" in argv
    npass = nfail = 0
    for case in CASES:
        try:
            bad = run_case(case)
        except Exception as e:                      # ランナー自体の失敗も NG に数える
            bad = [f"{type(e).__name__}: {e}"]
        label = f"drops #{case['id']} {case['note']}"
        if bad:
            nfail += 1
            print(f"NG  {label}")
            for b in bad:
                print(f"      {b}")
        else:
            npass += 1
            if verbose:
                print(f"OK  {label}")
    print(f"pass={npass} fail={nfail}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
