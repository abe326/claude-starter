#!/usr/bin/env python3
"""作業ログを正本から生成する（手で書かない）。

使い方: python3 scripts/work_log.py [--quiet]
  --quiet  書いたあと、直近 14 日の件数だけを 1 行で出す（SessionStart 用。異常時は無出力）

出力（docs/案件/作業ログ/。すべて生成物）:
  最新.md      直近 14 日。AI が最初に読む（日付ごと・1 行 1 件・新しい順）
  README.md    索引。月ごとに 1 行（件数・主な決定の題を 3 件まで）
  YYYY-MM.md   月ごとのアーカイブ（その月の全件）

材料は正本だけ: タスク・課題の frontmatter（created・closed）、閉じた課題の `## 決定` の 1 行目、
打合せ記録のファイル名の日付。git の履歴は読まない。本文は写さず、題と ID のリンクだけを書く。
AI の読み方: 最新.md → 無ければ README.md で月を絞る → その月 → 正本の ID。
中身が変わらないファイルは書き換えない。build.py と Stop hook（work_log.sh）から呼ばれる。標準ライブラリのみ。
"""
from __future__ import annotations

import datetime
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".claude/hooks"))

LOG_DIR = "docs/案件/作業ログ"
WINDOW_DAYS = 14
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ORDER = {"決定": 0, "完了": 1, "起票": 2, "打合せ": 3}
HEAD_LATEST = ("# 作業ログ（直近 14 日）\n\n"
               "> 生成物（`scripts/work_log.py`。手で書かない）。1 行 1 件。詳しくはリンク先の正本を読む。"
               "これより古いものは月ごとのファイル、一覧は [README.md](README.md)\n")
HEAD_INDEX = ("# 作業ログ — 索引\n\n"
              "> 生成物（`scripts/work_log.py`）。AI は [最新.md](最新.md) → ここで月を絞る → その月のファイル → 正本の ID の順に読む\n")


def _link(rel_from_root: str) -> str:
    return os.path.relpath(os.path.join(str(ROOT), rel_from_root), str(ROOT / LOG_DIR)).replace("\\", "/")


def collect(drops) -> list[dict]:
    """出来事の一覧。{date, kind, id, title, ref, note}。"""
    events: list[dict] = []
    for it in drops.load_items(str(ROOT)).values():
        title = (it.fields.get("title") or "").strip()
        created = (it.fields.get("created") or "").strip()
        closed = (it.fields.get("closed") or "").strip()
        same_day = it.state == "closed" and created == closed   # その場で決めた課題・すぐ終えたタスクは 1 行だけ
        if DATE_RE.match(created) and not same_day:
            events.append({"date": created, "kind": "起票", "id": it.id, "title": title, "ref": it.path,
                           "note": it.kind if it.kind == "課題" else ""})
        if it.state == "closed" and DATE_RE.match(closed):
            if it.kind == "課題":
                first, _ = drops.issue_decision(drops.read_text(str(ROOT / it.path)) or "")
                events.append({"date": closed, "kind": "決定", "id": it.id, "title": title, "ref": it.path,
                               "note": drops.short(first, 50) if first else ""})
            else:
                events.append({"date": closed, "kind": "完了", "id": it.id, "title": title, "ref": it.path, "note": ""})
    for rel in drops.meeting_files(str(ROOT)):
        date, title = drops._meeting_date(rel)
        if date and DATE_RE.match(date):
            events.append({"date": date, "kind": "打合せ", "id": "", "title": title or Path(rel).stem, "ref": rel,
                           "note": ""})
    for e in events:
        e["short"] = drops.short(e["title"], 24)
    events.sort(key=lambda e: (e["date"], -ORDER.get(e["kind"], 9), e["id"]), reverse=True)
    return events


def line(e: dict) -> str:
    label = e["id"] or e["title"]
    body = f"- {e['kind']} [{label}]({_link(e['ref'])})"
    if e["id"] and e["title"]:
        body += f" {e['title']}"
    if e["kind"] == "決定" and e["note"]:
        body += f" → {e['note']}"
    elif e["kind"] == "起票" and e["note"]:
        body += f"（{e['note']}）"
    return body


def by_date(events: list[dict]) -> str:
    out: list[str] = []
    current = None
    for e in events:
        if e["date"] != current:
            current = e["date"]
            out.append(f"\n## {current}\n")
        out.append(line(e) + "\n")
    return "".join(out)


def render(events: list[dict], today: datetime.date) -> dict[str, str]:
    """{ファイル名: 中身}。"""
    since = (today - datetime.timedelta(days=WINDOW_DAYS - 1)).isoformat()
    recent = [e for e in events if since <= e["date"] <= today.isoformat()]
    files = {"最新.md": HEAD_LATEST + (by_date(recent) if recent else "\n（直近 14 日の出来事はありません）\n")}
    months: dict[str, list[dict]] = {}
    for e in events:
        months.setdefault(e["date"][:7], []).append(e)
    rows = []
    for month in sorted(months, reverse=True):
        evs = months[month]
        files[f"{month}.md"] = f"# 作業ログ {month}\n\n> 生成物（`scripts/work_log.py`）。一覧は [README.md](README.md)\n" + by_date(evs)
        top = [f"{e['id']} {e['short']}" for e in evs if e["kind"] == "決定"][:3]
        rows.append(f"| [{month}]({month}.md) | {len(evs)} | {'、'.join(top) or '—'} |")
    table = "\n| 月 | 件数 | 主な決定 |\n|:--|--:|:--|\n" + ("\n".join(rows) + "\n" if rows else "| — | 0 | — |\n")
    files["README.md"] = HEAD_INDEX + table
    return files


def write(files: dict[str, str]) -> None:
    out = ROOT / LOG_DIR
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = out / name
        data = text.encode("utf-8")
        try:
            if path.read_bytes() == data:
                continue
        except OSError:
            pass
        path.write_bytes(data)


def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        import drops
        events = collect(drops)
        today = drops.today()
        files = render(events, today)
        write(files)
    except Exception as e:  # 生成物なので、失敗しても作業は止めない
        if not quiet:
            print(f"作業ログを生成できなかった: {e}")
        return 0 if quiet else 1
    since = (today - datetime.timedelta(days=WINDOW_DAYS - 1)).isoformat()
    n = sum(1 for e in events if since <= e["date"] <= today.isoformat())
    if quiet:
        print(n)
    else:
        print(f"作業ログ: {LOG_DIR}/最新.md（直近 {WINDOW_DAYS} 日 {n} 件）・月 {len(files) - 2} 本")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
