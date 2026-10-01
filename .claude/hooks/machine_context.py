#!/usr/bin/env python3
"""マシン側（ユーザー設定）の plugin・hook の混入と、ワークスペース信頼の状態を 1 行で出す。

session_context.sh（SessionStart）から 1 回呼ばれる。出すものが無ければ無出力。常に exit 0。

  - ユーザー設定 settings.json（$CLAUDE_CONFIG_DIR/settings.json、無ければ ~/.claude/settings.json）の
    enabledPlugins で有効かつ、案件の .claude/settings.json・settings.local.json で false にされていない plugin の名前
  - ユーザー設定の hooks の本数（イベント別）。案件の hook と合算されて動くもの
  - ~/.claude.json の projects.<案件のパス>.hasTrustDialogAccepted が読めて、案件と祖先のどれも true でなければ「未信頼」
    （案件の項目が無いときは判定できないので出さない）
値・パスは出さない。名前と件数だけ。厳しさは phase.py の global_leak（全フェーズ「情報」）。
抑え方は harness スキルの「グローバルとの干渉」。
出力の形（先頭の「- 」は付けない。session_context.sh が行にまとめる）:
  マシン側: plugin 2 個（a・b）・hook 1 本（Stop 1）が有効。干渉したら harness スキル（グローバルとの干渉）。ワークスペース未信頼: …
"""
from __future__ import annotations

import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAX_NAMES = 4


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _user_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def plugins(user: dict, root: str) -> list[str]:
    enabled = [k for k, v in (user.get("enabledPlugins") or {}).items() if v is True]
    off: set[str] = set()
    for name in ("settings.json", "settings.local.json"):
        proj = _load(os.path.join(root, ".claude", name))
        off |= {k for k, v in (proj.get("enabledPlugins") or {}).items() if v is False}
    return sorted(k for k in enabled if k not in off)


def hooks(user: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for event, groups in (user.get("hooks") or {}).items():
        n = 0
        for g in groups if isinstance(groups, list) else []:
            n += len(g.get("hooks") or []) if isinstance(g, dict) else 0
        if n:
            out[event] = n
    return out


def _norm(p: str) -> str:
    p = p.replace("\\", "/").rstrip("/")
    return p.lower() if len(p) > 1 and p[1] == ":" else p


def untrusted(root: str) -> bool:
    """案件の項目があり、案件と祖先のどれも信頼済みでなければ True。読めない・項目が無ければ False。"""
    cfg = None
    for d in (os.environ.get("CLAUDE_CONFIG_DIR"), os.path.expanduser("~")):
        if d and os.path.isfile(os.path.join(d, ".claude.json")):
            cfg = _load(os.path.join(d, ".claude.json"))
            break
    projects = (cfg or {}).get("projects")
    if not isinstance(projects, dict):
        return False
    table = {_norm(k): v for k, v in projects.items() if isinstance(v, dict)}
    target = _norm(os.path.abspath(root))
    if target not in table:
        return False
    p = target
    while True:
        if table.get(p, {}).get("hasTrustDialogAccepted") is True:
            return False
        parent = p.rsplit("/", 1)[0] if "/" in p.strip("/") else ""
        if not parent or parent == p:
            return True
        p = parent


def summary(root: str) -> str:
    try:
        import phase
        if phase.level("global_leak", phase.read_phase(root)) == "none":
            return ""
    except Exception:
        pass
    user = _load(os.path.join(_user_dir(), "settings.json"))
    parts = []
    names = plugins(user, root)
    if names:
        # 表示は「@」より前だけ（無効にするときの設定キーは settings.json の enabledPlugins にある完全な名前）
        shown = "・".join(n.split("@", 1)[0] for n in names[:MAX_NAMES]) + ("…" if len(names) > MAX_NAMES else "")
        parts.append(f"plugin {len(names)} 個（{shown}）")
    counts = hooks(user)
    if counts:
        detail = "・".join(f"{k} {v}" for k, v in sorted(counts.items()))
        parts.append(f"hook {sum(counts.values())} 本（{detail}）")
    out = []
    if parts:
        out.append(f"マシン側: {'・'.join(parts)}が有効。干渉したら harness スキル（グローバルとの干渉）")
    if untrusted(root):
        out.append("ワークスペース未信頼: 案件の permissions が効かない可能性。対話起動（claude）で開いて信頼する"
                   "（README.md「Claude Code で開く前に」）")
    return "。".join(out)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        line = summary(root)
        if line:
            print(line)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
