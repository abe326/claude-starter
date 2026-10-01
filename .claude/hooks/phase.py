#!/usr/bin/env python3
"""フェーズ（Sketch / Build）の読み書きと、フェーズ × 仕組みの厳しさの表の共有モジュール。

hook（design_docs_reminder.py・pickup_*・session_context.sh）とスクリプト（check_skeleton.py・
docs_freshness.py・check_drops.py）が同じ表を同じ解釈で読むために置く。scripts/ 側からは
`sys.path.insert(0, ROOT / ".claude/hooks")` で import する。標準ライブラリのみ。

フェーズの正本: docs/プロジェクト概要.html の `<!-- BEGIN:phase -->`〜`<!-- END:phase -->` 内の
最初の `data-phase="…"` 属性。属性が無い・読めない・読み替えても分からないときは「Sketch」として扱う
（止めない）。旧い値（立ち上げ・開発・運用）と大小文字違い（sketch・build）は ALIASES で読み替える。
環境変数 CLAUDE_SKELETON_PHASE があればそれを優先する（テスト用。読み替えても分からない値は無視）。

厳しさの表（STRICTNESS）はここが唯一の正本。文書に表を複製しない。人が見るときは `--table`。
仕組みの側はフェーズ名で分岐せず、level(<キー>, read_phase(root)) の値だけを見る。

使い方:
  python3 .claude/hooks/phase.py              フェーズ名を 1 行
  python3 .claude/hooks/phase.py --table      厳しさの表を Markdown で出す
  python3 .claude/hooks/phase.py --set Build  フェーズを切り替える（旧 → 新を 1 行。読めない値は exit 2）
  python3 .claude/hooks/phase.py --json       {"phase": …, "problem": …, "suggest": …}
フェーズの切り替えは AI が判断して行う（確認は挟まない。update-overview スキル）。切り替えたら
報告の中で 1 行伝える。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True

PHASES = ("Sketch", "Build")
DEFAULT_PHASE = "Sketch"
# 旧い値の読み替え。大小文字違い（sketch・build）は normalize() が別途吸収する
ALIASES = {"立ち上げ": "Sketch", "開発": "Build", "運用": "Build"}
LEVELS = ("block", "warn", "info", "none")  # 止める / 警告 / 情報 / 何もしない
LEVEL_JA = {"block": "止める", "warn": "警告", "info": "情報", "none": "何もしない"}
OVERVIEW = "docs/プロジェクト概要.html"
ENV_PHASE = "CLAUDE_SKELETON_PHASE"


def normalize(value: str | None) -> str | None:
    """フェーズ名を正規化する（新値そのまま／旧い値／大小文字違いを吸収）。該当しなければ None。"""
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if v in PHASES:
        return v
    if v in ALIASES:
        return ALIASES[v]
    low = v.lower()
    for p in PHASES:
        if low == p.lower():
            return p
    return None


def _row(sketch: str, build: str) -> dict[str, str]:
    return {"Sketch": sketch, "Build": build}


# 仕組みキー → {フェーズ: レベル}。止めるのは「形」と「秘密」だけ。内容の空欄・未記入・未決の多さでは止めない
STRICTNESS: dict[str, dict[str, str]] = {
    "work_area_guard": _row("block", "block"),
    "secret_scan": _row("block", "block"),
    "skeleton_shape": _row("block", "block"),
    "design_docs_shape": _row("block", "block"),
    "harness_shape": _row("block", "block"),
    "harness_unlisted": _row("info", "warn"),
    "design_docs_reminder": _row("info", "warn"),
    "docs_unfilled": _row("info", "warn"),
    "docs_stale_days": _row("none", "warn"),
    "docs_source_drift": _row("info", "warn"),
    "pickup": _row("warn", "warn"),
    "pickup_orphans": _row("info", "warn"),
    "harness_candidates": _row("info", "info"),
    "global_leak": _row("info", "info"),
    "phase_suggest": _row("info", "none"),
}

# --table 用の説明（表の中身は STRICTNESS だけが持つ）
LABELS: dict[str, str] = {
    "work_area_guard": "置き場ガード（PreToolUse）",
    "secret_scan": "秘密検出",
    "skeleton_shape": "構成の検査（必須ファイル・hooks 実在・マーカー・data-phase など）",
    "design_docs_shape": "設計書の形（鮮度メタ行・改訂履歴・索引・影響マップ）",
    "harness_shape": "ハーネスの形（agents の model・台帳の定義先・05 §9 と deny）",
    "harness_unlisted": "台帳に無いハーネス",
    "design_docs_reminder": "設計書追随 hook（PostToolUse・Stop の実装判定）",
    "docs_unfilled": "雛形のままの設計書（未記入）",
    "docs_stale_days": "鮮度: 最終更新から N 日",
    "docs_source_drift": "鮮度: ソース変更あり",
    "pickup": "拾って流す（区切りで促す）",
    "pickup_orphans": "落ち先の無い行・未決参照・確認依頼の ID",
    "harness_candidates": "ハーネス候補の件数（SessionStart）",
    "global_leak": "マシン側の plugin・hook の混入表示",
    "phase_suggest": "フェーズ切り替えの提案",
}

_BLOCK_RE = re.compile(r"<!--\s*BEGIN:phase\s*-->(.*?)<!--\s*END:phase\s*-->", re.S)
_ATTR_RE = re.compile(r'data-phase\s*=\s*"([^"]*)"')
_PHASE_DIV_RE = re.compile(r'<div\s+class="phase"')
_NAME_RE = re.compile(r'(<div\s+class="name"\s*>)(.*?)(</div>)', re.S)

# phase_suggest: git log でこれ以外への変更を「ソースの変更」と数える
_NON_SOURCE_DIRS = ("docs", ".claude", "scripts", ".work")
_NON_SOURCE_FILES = {
    "CLAUDE.md", "README.md", "CHANGELOG.md", ".gitignore", ".gitattributes",
    ".editorconfig", ".env.example",
}


def _overview_path(root) -> str:
    return os.path.join(os.fspath(root), *OVERVIEW.split("/"))


def _read_block(root) -> tuple[str | None, str | None]:
    """(phase ブロックの中身, 問題)。読めない → (None, "読めない")、ブロックが無い → (None, "phase ブロックなし")。"""
    try:
        with open(_overview_path(root), encoding="utf-8") as f:
            html = f.read()
    except (OSError, UnicodeDecodeError):
        return None, "読めない"
    m = _BLOCK_RE.search(html)
    if not m:
        return None, "phase ブロックなし"
    return m.group(1), None


def _file_phase(root) -> tuple[str, str | None]:
    """概要 HTML から (フェーズ, 問題)。環境変数は見ない。旧い値・大小文字違いは読み替えて返す。"""
    block, problem = _read_block(root)
    if block is None:
        return DEFAULT_PHASE, problem
    m = _ATTR_RE.search(block)
    if not m:
        return DEFAULT_PHASE, "属性なし"
    value = m.group(1).strip()
    normalized = normalize(value)
    if normalized is None:
        return DEFAULT_PHASE, f"不正な値: {value}"
    return normalized, None


def read_phase(root) -> str:
    """フェーズ名。何が起きても例外を出さず、分からなければ DEFAULT_PHASE。"""
    try:
        env = normalize(os.environ.get(ENV_PHASE, ""))
        if env is not None:
            return env
        return _file_phase(root)[0]
    except Exception:
        return DEFAULT_PHASE


def phase_status(root) -> tuple[str, str | None]:
    """(フェーズ, 問題)。問題は概要 HTML の状態（"属性なし" / "不正な値: X" / "読めない" /
    "phase ブロックなし" / None）。フェーズは read_phase と同じ（環境変数が優先）。check_skeleton 用。"""
    try:
        _, problem = _file_phase(root)
    except Exception:
        problem = "読めない"
    return read_phase(root), problem


def level(mechanism: str, phase: str) -> str:
    """仕組みのレベル（block / warn / info / none）。表に無いキー・フェーズは "none"（未知の仕組みで止めない）。
    phase は旧い値・大小文字違いでもよい（読み替えて引く）。"""
    canonical = normalize(phase) or phase
    return STRICTNESS.get(mechanism, {}).get(canonical, "none")


def set_phase(root, new: str) -> str:
    """data-phase 属性と .name の中身だけを書き換える。戻り値は旧フェーズ（属性が無かった・不正なら DEFAULT_PHASE）。

    new は旧い値・大小文字違いでもよく、読み替えた新しい値（Sketch／Build）で書く。
    マーカー外・.word には触らない。属性が無ければ `<div class="phase"` に足す。
    phase ブロックが無い・読めない・new が読み替えても分からないなら ValueError。改行コードは元のまま保つ。
    """
    normalized_new = normalize(new)
    if normalized_new is None:
        raise ValueError(f"フェーズは {' / '.join(PHASES)} のどれか: {new!r}")
    new = normalized_new
    path = _overview_path(root)
    try:
        with open(path, "rb") as f:
            html = f.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"{OVERVIEW} を読めない: {e}") from e
    m = _BLOCK_RE.search(html)
    if not m:
        raise ValueError(f"{OVERVIEW} に <!-- BEGIN:phase --> 〜 <!-- END:phase --> が無い")
    block = m.group(1)
    a = _ATTR_RE.search(block)
    old = normalize(a.group(1).strip()) if a else None
    old = old if old is not None else DEFAULT_PHASE
    if a:
        block = block[:a.start(1)] + new + block[a.end(1):]
    else:
        d = _PHASE_DIV_RE.search(block)
        if not d:
            raise ValueError(f'{OVERVIEW} の phase ブロックに <div class="phase"> が無い')
        block = block[:d.end()] + f' data-phase="{new}"' + block[d.end():]
    block = _NAME_RE.sub(lambda n: n.group(1) + new + n.group(3), block, count=1)
    html = html[:m.start(1)] + block + html[m.end(1):]
    with open(path, "wb") as f:
        f.write(html.encode("utf-8"))
    return old


def _source_commits(root) -> int | None:
    """docs/・.claude/・scripts/・.work/ と生成時のルート直下ファイル以外を変えたコミット数。git が無ければ None。"""
    try:
        r = subprocess.run(["git", "-c", "core.quotePath=false", "log", "-n", "300",
                            "--pretty=format:@", "--name-only", "--relative"],
                           cwd=os.fspath(root), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    count, hit = 0, False
    for line in r.stdout.splitlines() + ["@"]:
        line = line.strip()
        if line == "@":
            count += hit
            hit = False
        elif line:
            parts = line.split("/")
            if parts[0] not in _NON_SOURCE_DIRS and not (len(parts) == 1 and line in _NON_SOURCE_FILES):
                hit = True
    return count


def suggest(root, phase: str) -> str | None:
    """フェーズ切り替えの提案文（SessionStart 用）。提案が無い・git が無い・判定できない → None。

    機械で見るのは「Sketch の間に、ソースの変更コミットが 1 件以上ある」だけ。切り替えは AI が判断して
    行う（確認は挟まない）。関係者向けの資料・確認依頼を出し始めた／設計書（01 以外）を足した／実装や
    設定変更を始めたと Claude が会話中に気づいたときも Build へ切り替えてよい。
    """
    try:
        if level("phase_suggest", phase) == "none" or normalize(phase) != "Sketch":
            return None
        n = _source_commits(root)
        if not n:
            return None
        return (f"Build の目安に当たる（ソースの変更 {n} 件）。AI が判断して "
                f"python3 .claude/hooks/phase.py --set Build で切り替え、報告で 1 行伝える")
    except Exception:
        return None


def table_markdown() -> str:
    head = ["| キー | 仕組み | " + " | ".join(PHASES) + " |", "|---|---|" + "---|" * len(PHASES)]
    rows = [f"| `{k}` | {LABELS.get(k, '')} | " + " | ".join(LEVEL_JA[v[p]] for p in PHASES) + " |"
            for k, v in STRICTNESS.items()]
    notes = ["", "止める: hook は exit 2・検査は NG ／ 警告: 検査は WARN（fail に数えない）・hook は同じ作業の中で直す促し",
             "／ 情報: 件数だけ・検査は -v のとき INFO ／ 何もしない: 出さない"]
    return "\n".join(head + rows + notes)


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # CLI は自分の置き場からルートを求める（CLAUDE_PROJECT_DIR が別の案件を指していても取り違えない）
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if "--table" in argv:
        print(table_markdown())
        return 0
    if "--set" in argv:
        i = argv.index("--set")
        new = argv[i + 1] if i + 1 < len(argv) else ""
        if normalize(new) is None:
            print(f"エラー: フェーズは {' / '.join(PHASES)} のどれか（指定: {new!r}）", file=sys.stderr)
            return 2
        try:
            old = set_phase(root, new)
        except ValueError as e:
            print(f"エラー: {e}", file=sys.stderr)
            return 2
        print(f"フェーズ: {old} → {normalize(new)}（{OVERVIEW}。表は python3 .claude/hooks/phase.py --table）")
        return 0
    if "--json" in argv:
        phase, problem = phase_status(root)
        print(json.dumps({"phase": phase, "problem": problem, "suggest": suggest(root, phase)}, ensure_ascii=False))
        return 0
    print(read_phase(root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
