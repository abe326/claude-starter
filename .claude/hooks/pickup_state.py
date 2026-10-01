#!/usr/bin/env python3
"""「拾って流す」hook のセッション状態（標準ライブラリのみ）。

並列のツール呼び出しで JSON を壊さないよう、2 つのファイルに分ける。
  - 出来事ログ claude_pickup_<sid>.jsonl … PostToolUse・UserPromptSubmit が 1 行追記するだけ（O_APPEND）
      {"k":"turn","ts":…} 依頼ごとに 1 行 / {"k":"touch","v":"<rel>","ts":…} / {"k":"cue","v":"あとで","t":"later","x":"<前後>","ts":…}
  - 既出集合 claude_pickup_seen_<sid>.json … Stop（pickup_check.py）だけが書く。{"seen":[…],"blocks":N,"turn_ts":…}
置き場は環境変数 CLAUDE_DOCS_REMINDER_STATE_DIR、無ければ tempfile.gettempdir()。
session_id が無ければ何も記録しない（Stop は判定材料なしで黙る）。

design_docs_reminder.py の「同じ候補は 1 回」（already_seen）もここに置く（state ファイル名は v1.1.0 と同じ）。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time


def state_dir() -> str:
    return os.environ.get("CLAUDE_DOCS_REMINDER_STATE_DIR") or tempfile.gettempdir()


def _safe(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", session_id)[:128]


def log_path(session_id: str) -> str:
    return os.path.join(state_dir(), f"claude_pickup_{_safe(session_id)}.jsonl")


def seen_path(session_id: str) -> str:
    return os.path.join(state_dir(), f"claude_pickup_seen_{_safe(session_id)}.json")


def append(session_id: str | None, kind: str, value: str | None = None, **extra) -> None:
    """出来事を 1 行追記する。session_id が無い・書けないときは何もしない。"""
    if not session_id or not isinstance(session_id, str):
        return
    rec = {"k": kind, "ts": time.time()}
    if value is not None:
        rec["v"] = value
    rec.update(extra)
    line = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        fd = os.open(log_path(session_id), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError:
        pass


def drain(session_id: str | None) -> list[dict]:
    """ログを退避してから読み、消す（読んでいる間の追記は次のターンに回る）。"""
    if not session_id or not isinstance(session_id, str):
        return []
    src = log_path(session_id)
    tmp = f"{src}.{os.getpid()}.drain"
    try:
        os.replace(src, tmp)
    except OSError:
        return []
    out: list[dict] = []
    try:
        with open(tmp, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        out.append(rec)
                except ValueError:
                    continue
    except OSError:
        pass
    try:
        os.remove(tmp)
    except OSError:
        pass
    return out


def load_seen(session_id: str) -> dict:
    try:
        with open(seen_path(session_id), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            out = dict(data)                       # turn_ts など他のキーは残す（Stop が持ち越す）
            out["seen"] = list(data.get("seen", []))
            out["blocks"] = int(data.get("blocks", 0))
            return out
    except Exception:
        pass
    return {"seen": [], "blocks": 0}


def save_seen(session_id: str, data: dict) -> None:
    path = seen_path(session_id)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


# --- design_docs_reminder.py 用（v1.1.0 からの据え置き）---------------------------

def reminder_state_path(session_id: str) -> str:
    return os.path.join(state_dir(), f"claude_docs_reminder_{_safe(session_id)}.json")


def already_seen(session_id: str, key: str) -> bool:
    """既出なら True。未出なら記録して False。"""
    path = reminder_state_path(session_id)
    seen: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            seen = list(json.load(f).get("seen", []))
    except Exception:
        pass
    if key in seen:
        return True
    seen.append(key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"seen": seen}, f, ensure_ascii=False)
    except Exception:
        pass
    return False
