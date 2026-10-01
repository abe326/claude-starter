#!/usr/bin/env python3
"""案件ごとの設定 `.claude/project.json` を読む共有モジュール。標準ライブラリのみ。

テンプレのコード（hook・scripts）を案件で書き換えずに、案件の形の違いをここで受ける。
work_area_guard.py・impact_map.py・scripts/docs_freshness.py・scripts/check_skeleton.py が import する。

  work_area_allow  ルート相対の glob のリスト。置き場ガードが止めずに通す（仕組みの固定パス。例
                   `playwright.config.ts`・`.work/依存監査ログ.md`・`.work/一時/tldv同期/**`）。glob の解釈は impact_map.glob_matches
  nested_repos     ルート相対のフォルダのリスト。中に別の git リポがある（例 `repos/sub-repo`）。
                   影響マップの正本の解決と、鮮度メタの `<リポ名>@<sha>` の突き合わせに使う
  save_cues        保存を起点にした促し。`{"glob": "<glob か glob のリスト>", "cue": "<促す 1 文>"}` のリスト。
                   Claude が当たるファイルを書いたら、design_docs_reminder.py がファイルごとにセッション 1 回 cue を返す
                   （load() は {"globs": [...], "cue": "..."} に揃えて返す）

`_` で始まるキーは説明用として無視する。読めない・壊れている・型が違うときは既定値（空）にして止めない。
形の誤りは `problems()` が返し、check_skeleton.py が NG にする。
"""
from __future__ import annotations

import json
import os

CONFIG = ".claude/project.json"
DEFAULTS: dict[str, list] = {"work_area_allow": [], "nested_repos": [], "save_cues": []}
# ルート相対のパスのリストを持つキー
PATH_KEYS = ("work_area_allow", "nested_repos")


def _norm(p: str) -> str:
    p = p.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/") if p != "/" else p


def _read(root: str):
    """(中身, 読めなかった理由)。ファイルが無ければ ({}, None)。"""
    path = os.path.join(root, CONFIG)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return {}, None
    except OSError as e:
        return None, f"読めない（{e}）"
    try:
        return json.loads(text), None
    except ValueError as e:
        return None, f"JSON として読めない（{e}）"


def _cue_globs(g) -> list[str]:
    """save_cues の glob（文字列か文字列のリスト）→ 正規化した glob のリスト。形が違えば空。"""
    items = [g] if isinstance(g, str) else g if isinstance(g, list) else []
    return [_norm(x) for x in items if isinstance(x, str) and _norm(x)]


def load(root: str) -> dict[str, list]:
    """設定を返す。無い・壊れているキーは既定値。リストの中の形の違う要素は捨てる。"""
    data, _ = _read(root)
    out = {k: list(v) for k, v in DEFAULTS.items()}
    if not isinstance(data, dict):
        return out
    for key in PATH_KEYS:
        v = data.get(key)
        if isinstance(v, list):
            out[key] = [_norm(x) for x in v if isinstance(x, str) and _norm(x)]
    cues = data.get("save_cues")
    if isinstance(cues, list):
        for c in cues:
            if isinstance(c, dict) and isinstance(c.get("cue"), str) and c["cue"].strip() and _cue_globs(c.get("glob")):
                out["save_cues"].append({"globs": _cue_globs(c.get("glob")), "cue": c["cue"].strip()})
    return out


def problems(root: str) -> list[str]:
    """形の誤り（check_skeleton.py 用）。無ければ空。"""
    data, err = _read(root)
    if err:
        return [f"{CONFIG}: {err}"]
    if not isinstance(data, dict):
        return [f"{CONFIG}: 最上位が JSON のオブジェクトでない"]
    out: list[str] = []
    for key, v in data.items():
        if key.startswith("_"):
            continue
        if key not in DEFAULTS:
            out.append(f"{CONFIG}: 知らないキー {key!r}（使えるのは {' / '.join(DEFAULTS)}。説明は `_` で始まるキーに）")
            continue
        if key == "save_cues":
            out += _cue_problems(v)
            continue
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            out.append(f"{CONFIG}: {key} は文字列のリスト")
            continue
        for x in v:
            n = _norm(x)
            if _bad_path(n):
                out.append(f"{CONFIG}: {key} の {x!r} はルート相対のパスにする（絶対パス・.. は不可）")
            elif key == "nested_repos" and not os.path.isdir(os.path.join(root, n)):
                out.append(f"{CONFIG}: nested_repos の {x!r} がフォルダとして実在しない")
    return out


def _bad_path(n: str) -> bool:
    return not n or n.startswith("/") or ":" in n or ".." in n.split("/")


def _cue_problems(v) -> list[str]:
    if not isinstance(v, list):
        return [f"{CONFIG}: save_cues は glob と cue を持つオブジェクトのリスト"]
    out: list[str] = []
    for i, c in enumerate(v, 1):
        if not isinstance(c, dict):
            out.append(f"{CONFIG}: save_cues の {i} 件目が glob と cue を持つオブジェクトでない")
            continue
        g = c.get("glob")
        items = [g] if isinstance(g, str) else g if isinstance(g, list) else None
        if not items or not all(isinstance(x, str) for x in items):
            out.append(f"{CONFIG}: save_cues の {i} 件目の glob は文字列か文字列のリスト")
        elif any(_bad_path(_norm(x)) for x in items):
            out.append(f"{CONFIG}: save_cues の {i} 件目の glob はルート相対にする（絶対パス・.. は不可）")
        if not isinstance(c.get("cue"), str) or not c["cue"].strip():
            out.append(f"{CONFIG}: save_cues の {i} 件目の cue（促す 1 文）が空")
    return out


def nested_repo_of(rel: str, repos: list[str]) -> str | None:
    """rel（ルート相対 posix）を含む入れ子リポ（最長一致）。無ければ None。"""
    hits = [r for r in repos if rel == r or rel.startswith(r + "/")]
    return max(hits, key=len) if hits else None
