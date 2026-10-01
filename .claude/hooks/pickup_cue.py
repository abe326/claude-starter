#!/usr/bin/env python3
"""UserPromptSubmit hook: 依頼文の手がかり（あとで・決めた・未定・今後〜しないで…）を記録し、1 行だけ文脈に足す。

Stop hook（pickup_check.py）が、このターンに拾いものが落ちたかを判定する材料を残す。ブロックはしない（常に exit 0）。

  - 依頼ごとに pickup_state へ {"k":"turn"} を 1 行（ターン開始時刻。Stop が mtime で触ったファイルを探す起点）
  - 手がかりの語ごとに {"k":"cue","v":<語>,"t":<種類>,"x":<前後 20 字>}。当たったときだけ
    additionalContext に「[拾う候補] …」を 1 行返す。当たらなければ無出力
  - 見ないもの: 先頭が `/`（スラッシュコマンド）、10 字未満、コードブロック（```）と引用（> 行）の中
  - 先頭が `<` の依頼（<task-notification> などシステム由来）は turn も記録しない（直前の依頼のターンが続く扱い）
  - 1500 字を超える依頼は語を数えず paste を 1 件だけ記録（打合せの貼り付けの可能性）
  - 環境変数 CLAUDE_PICKUP=off で何もしない。session_id が無ければ記録しない（文脈の 1 行は返す）
  - 例外は握りつぶして exit 0

語の表は下の CUES 1 か所。案件で足してよい（ハーネス語の追加・削除は harness スキルの担当が決める）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MIN_LEN = 10
PASTE_LEN = 1500
CONTEXT_CHARS = 20

# 種類 → 表示名
KINDS = {"later": "あとでやる", "decision": "決定", "issue": "未決", "harness": "ハーネス候補"}

# (種類, 正規表現)。語は「意図を表す形」だけにする（「後の」「以後」「いずれか」「決定的」は当てない）
CUES: list[tuple[str, str]] = [
    ("later", r"あとで|後で(?!は)|後回し|次回|今度(?:やる|対応|確認|まとめ|にし)|いずれ(?![かも])|(?<![A-Za-z])TODO(?![A-Za-z])|忘れずに"),
    ("issue", r"未定|保留|決まって(?:い)?ない|要確認|持ち帰り|未確定|未決"),
    ("decision", r"決めた|(?<!未)決定(?!的|打|版|稿|力)|(?<!未)確定(?!申告|的)|で(?:行|い)こう|合意"),
]
# ハーネス候補: 同じ文に「今後・毎回・二度と・必ず・いつも」と「しないで・やめて・禁止…」が両方あるとき
HARNESS_WHEN = r"今後|毎回|二度と|必ず|いつも|常に"
HARNESS_DO = r"ないで|ないように|ないこと|やめて|禁止|するように|すること|してください"
HARNESS_AGAIN = r"前にも言った|前も言った|また同じ"
# 語の前に消しておく言い回し（誤発火の除外語）
EXCLUDE = r"心配しないで|気にしないで|遠慮しないで|無理しないで|焦らないで|今後とも|今後ともよろしく"


def normalize(text: str) -> str:
    """全角英数を半角に（NFKC）。改行は文の区切りとして残す。"""
    return unicodedata.normalize("NFKC", text or "")


def strip_code_and_quote(text: str) -> str:
    out, in_code = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or s.startswith(">"):
            continue
        out.append(line)
    return "\n".join(out)


def around(flat: str, start: int, end: int) -> str:
    return flat[max(0, start - CONTEXT_CHARS):end + CONTEXT_CHARS].strip()


def find_cues(prompt: str) -> list[dict]:
    """[{v, t, x}]。同じ種類・同じ語は 1 回だけ。"""
    text = re.sub(EXCLUDE, lambda m: "＿" * len(m.group(0)), strip_code_and_quote(normalize(prompt)))
    flat = re.sub(r"\s+", " ", text)
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, word: str, x: str) -> None:
        if (kind, word) in seen:
            return
        seen.add((kind, word))
        found.append({"v": word, "t": kind, "x": x})

    for kind, pattern in CUES:
        for m in re.finditer(pattern, flat):
            add(kind, m.group(0), around(flat, m.start(), m.end()))
    for sentence in re.split(r"[。!?！？\n]", text):
        s = re.sub(r"\s+", " ", sentence).strip()
        if not s:
            continue
        w = re.search(HARNESS_WHEN, s)
        d = re.search(HARNESS_DO, s)
        if w and d:
            add("harness", f"{w.group(0)}…{d.group(0)}", s[:CONTEXT_CHARS * 2])
        a = re.search(HARNESS_AGAIN, s)
        if a:
            add("harness", a.group(0), s[:CONTEXT_CHARS * 2])
    return found


def emit(msg: str) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}},
                     ensure_ascii=False))


def main() -> int:
    try:
        if os.environ.get("CLAUDE_PICKUP", "").strip().lower() == "off":
            return 0
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        prompt = data.get("prompt")
        if not isinstance(prompt, str):
            return 0
        sid = data.get("session_id") if isinstance(data.get("session_id"), str) else None
        head = prompt.lstrip()
        if head.startswith("<"):
            return 0                                   # システム由来（サブエージェントの完了通知など）
        try:
            import pickup_state as ps  # noqa: WPS433
        except Exception:
            ps = None
        if ps is not None:
            ps.append(sid, "turn")
        if head.startswith("/") or len(head.strip()) < MIN_LEN:
            return 0
        if len(prompt) > PASTE_LEN:
            if ps is not None:
                ps.append(sid, "paste", str(len(prompt)))
            emit("[拾う候補] 長文の貼り付け: 打合せ記録にするなら docs/案件/02_打合せ/ へ置き、"
                 "決定・未決・宿題の各行に落ち先を書く（pickup スキル）")
            return 0
        cues = find_cues(prompt)
        if not cues:
            return 0
        if ps is not None:
            for c in cues:
                ps.append(sid, "cue", c["v"], t=c["t"], x=c["x"])
        words = "・".join(f"「{c['v']}」（{KINDS[c['t']]}）" for c in cues[:4])
        tail = "。ハーネス候補は harness スキルで台帳に「候補」として 1 行" if any(c["t"] == "harness" for c in cues) else ""
        emit(f"[拾う候補] 依頼文に{words}。区切りで反映済・タスク・未決のどれかに落とす（pickup スキル）{tail}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
