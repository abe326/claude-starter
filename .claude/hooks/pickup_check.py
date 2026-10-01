#!/usr/bin/env python3
"""Stop hook: ターンの終わりに「拾いもの」が落ちたかを機械で判定し、落ちていないものがあるときだけ 1 回促す。

LLM は呼ばない。材料はこのターンに起きたことだけ（pickup_state の出来事ログ + 見張る置き場の mtime）。

  S1 打合せ記録の落ち先: このターンに触った docs/案件/02_打合せ/*.md に、落ち先なし・書式違反・ID 不在・
     課題でない の行がある（phase.level("pickup") が none 以外）
  S2 依頼文の拾いもの: このターンに cue（paste は除く）があり、見張る置き場のファイルを 1 つも触っていない
     （level("pickup") が none 以外）
  S3 実装の区切り: このターンに触ったソース（docs/ と .work/ .claude/ 以外）が影響マップに当たり、
     その候補の設計書を 1 つも触っていない（level("design_docs_reminder") が warn のときだけ）

  - 促すときは {"decision":"block","reason":…} を stdout に 1 回（Claude は止まらず reason に従って続ける）
  - stop_hook_active が true なら何もしない（ループ防止。ログは drain して持ち越さない）
  - 同じものは二度と促さない（既出キーを block した時点で保存）。1 セッションの block は
    CLAUDE_PICKUP_MAX_BLOCKS（既定 6）回まで。CLAUDE_PICKUP=off で判定しない
  - 「触ったファイル」= PostToolUse の touch ∪ 見張る置き場のうち mtime がターン開始 − 2 秒以降のもの
    （new.py・close.py は Bash でファイルを作るので PostToolUse に載らない。これを拾うため）。
    ターン開始は最後の turn。無いターン（<task-notification> など）は前回の turn を持ち越す
  - session_id が無い・壊れた入力・例外 → 何もせず exit 0（終われなくなる事故を避ける）
手で確かめる: echo '{"session_id":"s1","stop_hook_active":false}' | bash .claude/hooks/pickup_check.sh
"""
from __future__ import annotations

import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAX_LINES = 8
MTIME_SLACK = 2.0
README = "docs/設計書/README.md"
MEETING_DIR = "docs/案件/02_打合せ"
TASK_DIR = "docs/案件/01_タスク管理"
DESIGN_DIR = "docs/設計書"
# 見張る置き場: (ディレクトリ, 深さ) か 単一ファイル
WATCH_DIRS = [(MEETING_DIR, 0), (f"{TASK_DIR}/open", 0), (f"{TASK_DIR}/closed", 0), (DESIGN_DIR, 1)]
WATCH_FILES = ["docs/案件/確認依頼一覧.md", "docs/プロジェクト概要.html", "docs/ハーネス台帳.md"]
SOURCE_SKIP = (".work/", ".claude/", "docs/")
PROBLEM_LABEL = {"orphan": "落ち先なし", "format": "書式違反", "missing": "ID 不在", "notissue": "課題でない"}
KIND_LABEL = {"later": "あとでやる", "decision": "決定", "issue": "未決", "harness": "ハーネス候補"}


def is_watched(rel: str) -> bool:
    if rel in WATCH_FILES:
        return True
    for d, depth in WATCH_DIRS:
        if rel.startswith(d + "/"):
            rest = rel[len(d) + 1:]
            if rest.count("/") <= depth:
                return True
    return False


def scan_mtime(root: str, since: float) -> set[str]:
    """見張る置き場のうち mtime が since 以降のファイル（ルート相対 posix）。"""
    out: set[str] = set()

    def check(rel: str) -> None:
        try:
            if os.path.getmtime(os.path.join(root, rel)) >= since:
                out.add(rel)
        except OSError:
            pass

    for rel in WATCH_FILES:
        check(rel)
    for d, depth in WATCH_DIRS:
        stack = [(d, 0)]
        while stack:
            cur, lv = stack.pop()
            try:
                entries = list(os.scandir(os.path.join(root, cur)))
            except OSError:
                continue
            for e in entries:
                rel = f"{cur}/{e.name}"
                try:
                    if e.is_file():
                        check(rel)
                    elif e.is_dir() and lv < depth and not e.name.startswith("."):
                        stack.append((rel, lv + 1))
                except OSError:
                    continue
    return out


def level_of(key: str, root: str) -> str:
    try:
        import phase as phase_mod  # noqa: WPS433
        return phase_mod.level(key, phase_mod.read_phase(root))
    except Exception:
        return {"pickup": "warn", "design_docs_reminder": "info"}.get(key, "none")


def meeting_signals(root: str, touched: set[str], seen: set[str]) -> tuple[list[str], list[str]]:
    """S1。(reason の行, 新しい既出キー)。"""
    import drops  # noqa: WPS433
    lines: list[str] = []
    keys: list[str] = []
    files = sorted(r for r in touched if drops.is_meeting_path(r) and os.path.isfile(os.path.join(root, r)))
    if not files:
        return lines, keys
    items = drops.load_items(root)
    ledger = drops.ledger_ids(root)
    for rel in files:
        per: dict[str, list[str]] = {}
        for row in drops.parse_meeting(os.path.join(root, rel)):
            probs = drops.row_problems(row.drop_raw, items, root, ledger)
            if not probs:
                continue
            codes = sorted({p.code for p in probs})
            key = f"m:{rel}:{drops.sha8(row.text)}:{','.join(codes)}"
            if key in seen or key in keys:
                continue
            keys.append(key)
            for code in codes:
                if code == "orphan":
                    label = f"{row.kind}「{drops.short(row.text, 30)}」"
                else:
                    label = drops.short(row.drop_raw or "", 20)
                per.setdefault(code, []).append(label)
        if per:
            parts = []
            for code in ("orphan", "format", "missing", "notissue"):
                if code in per:
                    parts.append(f"{PROBLEM_LABEL[code]} {len(per[code])} 行（{'、'.join(per[code][:3])}）")
            lines.append(f"- 打合せ {os.path.basename(rel)}: {' ／ '.join(parts)}")
    return lines, keys


def cue_signals(cues: list[dict], touched: set[str], seen: set[str]) -> tuple[list[str], list[str]]:
    """S2。見張る置き場を 1 つでも触っていれば、落とした扱いで何も出さない。"""
    import drops  # noqa: WPS433
    if not cues or any(is_watched(r) for r in touched):
        return [], []
    lines: list[str] = []
    keys: list[str] = []
    for c in cues:
        kind = c.get("t", "")
        key = f"c:{kind}:{drops.sha8(str(c.get('x', '')) + '|' + str(c.get('v', '')))}"
        if key in seen or key in keys:
            continue
        keys.append(key)
        label = KIND_LABEL.get(kind, kind)
        word = drops.short(str(c.get("v", "")), 20)
        if kind == "harness":
            lines.append(f"- 依頼文の「{word}」（{label}）: harness スキルで docs/ハーネス台帳.md に「候補」で 1 行")
        else:
            lines.append(f"- 依頼文の「{word}」（{label}）がまだどこにも落ちていない")
    return lines, keys


def source_signals(root: str, touch_log: list[str], touched: set[str], seen: set[str]) -> tuple[list[str], list[str]]:
    """S3。ソースごとに影響マップの候補を引き、候補を 1 つも触っていなければ候補の組み合わせ単位で 1 行。"""
    from impact_map import load_impact_map, match_rows, resolve_targets  # noqa: WPS433
    rows = load_impact_map(os.path.join(root, README))
    if not rows:
        return [], []
    groups: dict[str, list[str]] = {}
    cand_of: dict[str, list[str]] = {}
    for rel in touch_log:
        if rel.startswith(SOURCE_SKIP):
            continue
        targets: list[str] = []
        for r in match_rows(rel, rows):
            targets += [t for t in r.targets if t not in targets]
        cands = [t for t in resolve_targets(targets, root) if t != rel]
        if not cands or any(c in touched for c in cands):
            continue
        key = "s:" + "|".join(sorted(cands))
        if key in seen:
            continue
        groups.setdefault(key, [])
        if rel not in groups[key]:
            groups[key].append(rel)
        cand_of[key] = cands
    lines = []
    for key, srcs in groups.items():
        names = "、".join(os.path.basename(c) for c in cand_of[key])
        more = f" ほか {len(srcs) - 2} 件" if len(srcs) > 2 else ""
        lines.append(f"- 実装: {'、'.join(srcs[:2])}{more} → {names}。決まったことを 1 行。sync-design-docs スキルで 4 つの問い（方式・境界・仮置き・採らなかった案）を当てる。仮置きは課題にして（未決 ID）")
    return lines, list(groups)


def build_reason(lines: list[str]) -> str:
    head = ("[拾う] この区切りで落ち先の無いものがある。pickup スキルで「反映済・タスク・未決」のどれかに落としてから終える。"
            "不要と判断したら理由を 1 行書いて終えてよい（同じものは再度促さない）。")
    body = lines
    if len(lines) > MAX_LINES - 1:
        body = lines[:MAX_LINES - 2] + [f"- ほか {len(lines) - (MAX_LINES - 2)} 件（python3 scripts/check_drops.py で一覧）"]
    return "\n".join([head] + body)


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            return 0
        sid = data.get("session_id")
        if not isinstance(sid, str) or not sid:
            return 0
        import pickup_state as ps  # noqa: WPS433
        events = ps.drain(sid)
        if os.environ.get("CLAUDE_PICKUP", "").strip().lower() == "off":
            return 0
        if data.get("stop_hook_active"):
            return 0
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        state = ps.load_seen(sid)
        seen = set(state.get("seen", []))

        turn_ts = None
        touch_log: list[str] = []
        cues: list[dict] = []
        for ev in events:
            k = ev.get("k")
            if k == "turn":
                turn_ts = ev.get("ts")
            elif k == "touch" and isinstance(ev.get("v"), str):
                if ev["v"] not in touch_log:
                    touch_log.append(ev["v"])
            elif k == "cue":
                cues.append(ev)
        if isinstance(turn_ts, (int, float)):
            state["turn_ts"] = turn_ts
        else:
            turn_ts = state.get("turn_ts")
        touched = set(touch_log)
        if isinstance(turn_ts, (int, float)):
            touched |= scan_mtime(root, float(turn_ts) - MTIME_SLACK)

        lines: list[str] = []
        new_keys: list[str] = []
        if level_of("pickup", root) != "none":
            for fn in (lambda: meeting_signals(root, touched, seen), lambda: cue_signals(cues, touched, seen)):
                ls, ks = fn()
                lines += ls
                new_keys += ks
        if level_of("design_docs_reminder", root) == "warn":
            ls, ks = source_signals(root, touch_log, touched, seen)
            lines += ls
            new_keys += ks

        try:
            max_blocks = int(os.environ.get("CLAUDE_PICKUP_MAX_BLOCKS", "6"))
        except ValueError:
            max_blocks = 6
        if not lines or state.get("blocks", 0) >= max_blocks:
            ps.save_seen(sid, state)
            return 0
        state["seen"] = list(seen) + new_keys
        state["blocks"] = int(state.get("blocks", 0)) + 1
        ps.save_seen(sid, state)
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print(json.dumps({"decision": "block", "reason": build_reason(lines)}, ensure_ascii=False))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
