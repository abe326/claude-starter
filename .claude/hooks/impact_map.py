#!/usr/bin/env python3
"""影響マップ（docs/設計書/README.md の「## 変えたもの → 一緒に直す正本」表）の共有モジュール。

design_docs_reminder.py（PostToolUse hook）と scripts/check_skeleton.py が同じ表を同じ解釈で読むために置く。
scripts/ 側からは `sys.path.insert(0, ROOT / ".claude/hooks")` で import する。標準ライブラリのみ。

表の読み方:
  - 「## 変えたもの」で始まる見出しの直後にある表だけを読む
  - 1 列目のバッククォート内 = glob（複数は `・` 区切り）。バッククォートが無い行は人向けの注記として無視
  - 2 列目のバッククォート内 = 一緒に直す文書（`docs/設計書/` 相対、ルート相対、または .claude/project.json の
    nested_repos に書いた入れ子リポの中の相対パス。` §n` 等の末尾注記は捨てる。複数は `→` や `・` で並ぶ）

表で書きにくい判定（先勝ち・除外・フォールバック）は、任意の差し込み口 `.claude/hooks/impact_map_local.py` の
`targets(rel_path) -> list[str]` に書ける（local_targets()）。置いたら表にそれを指す行を 1 行書く（check_skeleton.py が見る）。
"""
from __future__ import annotations

import glob as globmod
import os
import re
from dataclasses import dataclass

DESIGN_DIR = "docs/設計書"
LOCAL_MODULE = "impact_map_local"
_BACKTICK = re.compile(r"`([^`]+)`")


@dataclass
class Row:
    globs: list[str]
    targets: list[str]
    line_no: int


def load_impact_map(readme_path: str) -> list[Row]:
    """README から影響マップの機械行だけを返す。読めない・表が無いときは空リスト。"""
    try:
        with open(readme_path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    rows: list[Row] = []
    in_section = False
    for i, line in enumerate(lines, 1):
        if line.startswith("## "):
            in_section = line.startswith("## 変えたもの")
            continue
        if not in_section or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set(":- "):
            continue                                        # ヘッダ区切り行
        globs = [g.strip() for tok in _BACKTICK.findall(cells[0]) for g in re.split(r"[・,、\s]+", tok) if g.strip()]
        if not globs:
            continue                                        # glob 無し = 人向けの行
        targets = [_strip_note(t) for t in _BACKTICK.findall(cells[1])]
        targets = [t for t in targets if t and ("/" in t or "." in t)]   # ファイル名らしいものだけ
        rows.append(Row(globs, targets, i))
    return rows


def _strip_note(token: str) -> str:
    """`CLAUDE.md §5` → `CLAUDE.md`。先頭の空白区切り 1 語だけを残す。"""
    return re.sub(r"§.*$", "", token.strip().split()[0]).strip() if token.strip() else ""


def _glob_to_regex(pattern: str) -> re.Pattern:
    out = ""
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
            continue
        out += "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
        i += 1
    return re.compile(out)


def glob_matches(rel_path: str, pattern: str) -> bool:
    """rel_path（posix・ルート相対）が pattern に当たるか。`**/x*` は任意の深さのディレクトリ名・ファイル名にも当たる。"""
    rx = _glob_to_regex(pattern)
    parts = rel_path.split("/")
    return any(rx.fullmatch("/".join(parts[:n])) for n in range(1, len(parts) + 1))


def match_rows(rel_path: str, rows: list[Row]) -> list[Row]:
    return [r for r in rows if any(glob_matches(rel_path, g) for g in r.globs)]


def resolve_target(target: str, root: str) -> list[str]:
    """target を実ファイル（ルート相対 posix）へ展開する。見つからなければ空。"""
    found: list[str] = []
    for base in (os.path.join(root, DESIGN_DIR), root, *_nested_bases(root)):
        # base 側は glob.escape する（ルートのパスに [ ] 等が含まれると文字クラスと解釈されて何も見つからない）
        for hit in globmod.glob(os.path.join(globmod.escape(base), target), recursive=True):
            if os.path.isfile(hit):
                found.append(os.path.relpath(hit, root).replace("\\", "/"))
        if found:
            break
    return sorted(set(found))


def _nested_bases(root: str) -> list[str]:
    try:
        import project_config  # noqa: WPS433
        return [os.path.join(root, r) for r in project_config.load(root)["nested_repos"]]
    except Exception:
        return []


def local_targets(rel_path: str, root: str) -> list[str]:
    """差し込み口 .claude/hooks/impact_map_local.py の targets(rel_path)。無い・壊れているときは空。"""
    hooks_dir = os.path.join(root, ".claude", "hooks")
    if not os.path.isfile(os.path.join(hooks_dir, LOCAL_MODULE + ".py")):
        return []
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(LOCAL_MODULE, os.path.join(hooks_dir, LOCAL_MODULE + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        got = mod.targets(rel_path)
        return [t for t in got if isinstance(t, str) and t] if isinstance(got, (list, tuple)) else []
    except Exception:
        return []


def addable_docs(rel_path: str, root: str) -> list[str]:
    """まだ足していない設計書のうち、rel_path が当たるもの（docs/設計書/template/catalog.json の影響マップの行で判定）。

    文書を育てる方式では、足していない文書の行は README の影響マップに無い。ここで「足す候補」として拾う。
    読めない・壊れているときは空。戻り値は catalog のファイル名（例 `05-セキュリティ.md`）。
    """
    import json
    try:
        with open(os.path.join(root, DESIGN_DIR, "template", "catalog.json"), encoding="utf-8") as f:
            docs = json.load(f).get("docs", {})
    except (OSError, ValueError):
        return []
    out: list[str] = []
    for no, entry in sorted(docs.items()):
        if globmod.glob(os.path.join(globmod.escape(os.path.join(root, DESIGN_DIR)), f"{no}-*")):
            continue                                        # 足してある（旧い名前・別の拡張子も含む）
        for row in entry.get("rows", {}).get("## 変えたもの → 一緒に直す正本", []):
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            globs = [g.strip() for tok in _BACKTICK.findall(cells[0]) for g in re.split(r"[・,、\s]+", tok) if g.strip()]
            if any(glob_matches(rel_path, g) for g in globs) and entry.get("file") not in out:
                out.append(entry.get("file"))
    return out


def resolve_targets(targets: list[str], root: str) -> list[str]:
    """複数 target をまとめて展開する。解決できないものは生の文字列のまま残す。"""
    out: list[str] = []
    for t in targets:
        for p in resolve_target(t, root) or [t]:
            if p not in out:
                out.append(p)
    return out
