#!/usr/bin/env python3
"""check_drops.py — 落ち先・ID・未決参照・確認依頼・期限の検査（標準ライブラリのみ）。

作業中に出たもの（決定・未決・あとでやること・ハーネス候補）が「反映済・タスク・未決」のどれかに
落ちているかを数える。どのフェーズでも止めない（--strict を付けたときだけ警告で exit 1）。
解析は .claude/hooks/drops.py、フェーズと厳しさは .claude/hooks/phase.py（level のキー pickup・pickup_orphans）。

使い方:
  python3 scripts/check_drops.py                 # 全体。1 行 1 件「<重さ> <ファイル>:<行> <内容>」、最後に件数
  python3 scripts/check_drops.py --file <パス>   # 1 ファイルだけ（打合せ記録・課題 md・設計書・確認依頼一覧）
  python3 scripts/check_drops.py --refs 05       # 設計書 05 が本文で参照している未決（課題）の一覧
  python3 scripts/check_drops.py --quiet         # 「警告数 情報数 落ち先なし数 決めてほしいこと数 期限切れ数」を 1 行（異常時は無出力 exit 0）
  python3 scripts/check_drops.py --strict        # 警告が 1 件以上なら exit 1
  python3 scripts/check_drops.py --json          # 機械向け

重さ（括弧は phase.level のキー。無いものは固定）:
  打合せ記録の落ち先なし（pickup_orphans）                          Sketch 情報 ／ Build 警告
  書式違反（1 桁 ID など）・ID 不在・未決なのに課題でない・台帳に無い HN（pickup） 全フェーズ 警告
  閉じた課題に `## 決定` か落ち先が無い・落ち先が壊れている（pickup）              全フェーズ 警告
  設計書の（未決 ID）が閉じた課題を指している（pickup_orphans）       Sketch 情報 ／ Build 警告
  確認依頼一覧の [ ] 行に ID が無い（pickup_orphans）。ID 不在は（pickup）
  確認依頼一覧の [ ] 行の課題が閉じている・期限切れの open・旧形式 U-NN   情報（固定）
  `→ 候補: NN §n` のままの決定                                         Sketch 出さない ／ Build 情報
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.dont_write_bytecode = True

ROOT_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEVEL_JA = {"warn": "警告", "info": "情報"}
FALLBACK_LEVELS = {"pickup": "warn", "pickup_orphans": "info"}


class Finding:
    def __init__(self, level: str, file: str, line: int, code: str, message: str):
        self.level, self.file, self.line, self.code, self.message = level, file, line, code, message

    def as_dict(self) -> dict:
        return {"level": self.level, "file": self.file, "line": self.line, "code": self.code, "message": self.message}

    def text(self) -> str:
        return f"{LEVEL_JA[self.level]} {self.file}:{self.line} {self.message}"


def load_modules(root: str):
    hooks = os.path.join(root, ".claude", "hooks")
    if hooks not in sys.path:
        sys.path.insert(0, hooks)
    import drops  # type: ignore   # 無ければ呼び出し側で異常扱い
    try:
        import phase  # type: ignore
    except Exception:
        phase = None
    return drops, phase


class Checker:
    def __init__(self, root: str):
        self.root = root
        self.drops, self.phase_mod = load_modules(root)
        self.phase = "Sketch"
        if self.phase_mod is not None:
            try:
                self.phase = self.phase_mod.read_phase(root)
            except Exception:
                pass
        d = self.drops
        self.items = d.load_items(root)
        self.ledger = d.ledger_ids(root)
        self.today = d.today()
        self.findings: list[Finding] = []
        self.orphan_rows = 0

    # --- 重さ ---------------------------------------------------------------
    def level(self, key: str) -> str:
        lv = None
        if self.phase_mod is not None:
            try:
                lv = self.phase_mod.level(key, self.phase)
            except Exception:
                lv = None
        lv = lv or FALLBACK_LEVELS.get(key, "none")
        return "warn" if lv == "block" else lv          # 止めない（block は警告として扱う）

    def add(self, key_or_level: str, file: str, line: int, code: str, message: str) -> None:
        lv = key_or_level if key_or_level in ("warn", "info", "none") else self.level(key_or_level)
        if lv in ("warn", "info"):
            self.findings.append(Finding(lv, file, line, code, message))

    # --- 打合せ記録 -----------------------------------------------------------
    def check_meeting(self, rel: str) -> None:
        d = self.drops
        for row in d.parse_meeting(os.path.join(self.root, rel)):
            label = f"{row.kind}「{d.short(row.text, 30)}」"
            for drop in d.parse_drops(row.drop_raw):
                if drop.kind == "candidate" and self.phase != "Sketch":
                    p = d.resolve(drop, self.items, self.root, self.ledger)
                    if p is None:
                        self.add("info", rel, row.line_no, "candidate",
                                 f"{label}: 候補のまま（{d.short(drop.raw, 20)}）。正本に入れるか棚卸しする（audit-design-docs）")
                        continue
                p = d.resolve(drop, self.items, self.root, self.ledger)
                if p is None:
                    continue
                if p.code == "orphan":
                    self.orphan_rows += 1
                    self.add("pickup_orphans", rel, row.line_no, "orphan",
                             f"{label}: 落ち先なし（→ 反映済: 01 §3 / → APP-03 / → 未決 QA-01。pickup スキル）")
                else:
                    self.add("pickup", rel, row.line_no, p.code, f"{label}: {p.message}")

    # --- 課題 md ---------------------------------------------------------------
    def check_issue(self, item) -> None:
        d = self.drops
        text = d.read_text(os.path.join(self.root, item.path))
        if text is None:
            return
        line = _heading_line(text, "決定") or 1
        if item.state == "closed":
            for msg in d.issue_problems(text, self.items, self.root, self.ledger):
                self.add("pickup", item.path, line, "issue",
                         f"閉じた課題 {item.id}: {msg}（close.py を通さずに移した？ `## 決定` を書く）")
            if self.phase != "Sketch":
                _, drops_raw = d.issue_decision(text)
                for raw in drops_raw:
                    if d.has_candidate(raw):
                        self.add("info", item.path, line, "candidate",
                                 f"課題 {item.id} の決定が候補のまま（{d.short(raw, 20)}）。正本に入れるか棚卸しする")
        else:
            due = d.parse_date(item.fields.get("due", ""))
            if due is not None and due < self.today:
                self.add("info", item.path, _field_line(text, "due") or 1, "overdue",
                         f"期限切れ: {item.id}（due {due.isoformat()}）「{d.short(item.fields.get('title', ''), 30)}」")

    # --- 設計書 ---------------------------------------------------------------
    def check_doc_refs(self, only: str | None = None) -> None:
        d = self.drops
        for rel, line, iid in d.doc_refs(self.root):
            if only and rel != only:
                continue
            if iid.split("-")[0] == "U":
                continue                                  # 旧形式の未決 ID は下の old_u_refs が情報で出す
            if not d.ID_OK.match(iid):
                self.add("pickup", rel, line, "format", f"（未決 {iid}）: 書式違反の ID（2 桁以上。new.py の出力を写す）")
            elif iid not in self.items:
                self.add("pickup", rel, line, "missing", f"（未決 {iid}）: ID 不在（課題を起票してから書く）")
            elif self.items[iid].kind != "課題":
                self.add("pickup", rel, line, "notissue", f"（未決 {iid}）: 課題でない（未決の参照は kind: 課題 の ID）")
            elif self.items[iid].state == "closed":
                self.add("pickup_orphans", rel, line, "closedref",
                         f"（未決 {iid}）: 決着済みの未決を参照（{iid} は閉じている。決定を本文に書き、参照を外す）")
        for rel, line, uid in d.old_u_refs(self.root):
            if only and rel != only:
                continue
            self.add("info", rel, line, "oldu", f"旧形式の未決 ID {uid}（課題に起票して「（未決 <課題ID>）」に置き換える）")

    # --- 確認依頼一覧 -----------------------------------------------------------
    def check_confirm(self) -> None:
        d = self.drops
        rel = d.CONFIRM_MD
        for line, body, ids in d.confirm_rows(self.root):
            label = f"確認依頼「{d.short(body, 30)}」"
            if not ids:
                self.add("pickup_orphans", rel, line, "noid", f"{label}: 課題かタスクの ID が無い（課題を起票して ID を付ける）")
                continue
            closed_issue = False
            for iid in ids:
                if not d.ID_OK.match(iid):
                    self.add("pickup", rel, line, "format", f"{label}: 書式違反の ID「{iid}」")
                elif iid not in self.items:
                    self.add("pickup", rel, line, "missing", f"{label}: ID 不在「{iid}」")
                elif self.items[iid].kind == "課題" and self.items[iid].state == "closed":
                    closed_issue = True
            if closed_issue:
                self.add("info", rel, line, "closedconfirm", f"{label}: 課題は閉じたのに [ ] のまま（[x] にして履歴へ）")

    # --- 全体 -------------------------------------------------------------------
    def run(self, file_rel: str | None = None) -> None:
        d = self.drops
        if file_rel is None or d.is_meeting_path(file_rel):
            for rel in d.meeting_files(self.root):
                if file_rel is None or rel == file_rel:
                    self.check_meeting(rel)
        if file_rel is not None and d.is_meeting_path(file_rel) and file_rel not in d.meeting_files(self.root):
            self.check_meeting(file_rel)                     # README 以外の置き場外でも 1 ファイル指定なら見る
        for item in self.items.values():
            if item.state == "open" or (item.kind == "課題" and item.state == "closed"):
                if file_rel is None or item.path == file_rel:
                    self.check_issue(item)
        if file_rel is None or file_rel.startswith(d.DESIGN_DIR + "/"):
            self.check_doc_refs(only=file_rel)
        if file_rel is None or file_rel == d.CONFIRM_MD:
            self.check_confirm()

    def counts(self) -> dict:
        opens = [i for i in self.items.values() if i.state == "open"]
        overdue = 0
        for i in opens:
            due = self.drops.parse_date(i.fields.get("due", ""))
            if due is not None and due < self.today:
                overdue += 1
        return {
            "warn": sum(1 for f in self.findings if f.level == "warn"),
            "info": sum(1 for f in self.findings if f.level == "info"),
            "orphans": self.orphan_rows,
            "open_issues": sum(1 for i in opens if i.kind == "課題"),
            "overdue": overdue,
        }


def _heading_line(text: str, title: str) -> int | None:
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(rf"^##\s+{re.escape(title)}\s*$", line.strip()):
            return i
    return None


def _field_line(text: str, name: str) -> int | None:
    for i, line in enumerate(text.splitlines()[:40], 1):
        if re.match(rf"^{re.escape(name)}\s*:", line):
            return i
    return None


def to_rel(root: str, path: str) -> str:
    p = path if os.path.isabs(path) else os.path.abspath(path)
    if not os.path.exists(p) and os.path.exists(os.path.join(root, path)):
        p = os.path.join(root, path)
    rel = os.path.relpath(p, root).replace("\\", "/")
    return rel


def print_refs(ck: Checker, nn: str) -> int:
    d = ck.drops
    refs = [(rel, line, iid) for rel, line, iid in d.doc_refs(ck.root)
            if os.path.basename(rel).startswith(f"{nn}-") and rel.count("/") == d.DESIGN_DIR.count("/") + 1]
    if not refs:
        print(f"設計書 {nn} が参照している未決はありません。")
        return 0
    for rel, line, iid in refs:
        it = ck.items.get(iid)
        if it is None:
            state = "ID 不在"
            title = ""
        else:
            state = "決着済み" if it.state == "closed" else "未決"
            title = it.fields.get("title", "")
            if it.kind != "課題":
                state += "・課題でない"
        extra = ""
        if it is not None:
            bits = [f"決める: {it.fields.get('decider')}" if it.fields.get("decider") else "",
                    f"期限: {it.fields.get('due')}" if it.fields.get("due") else ""]
            extra = "".join(f" ／ {b}" for b in bits if b)
        print(f"{rel}:{line} {iid}（{state}）「{d.short(title, 40)}」{extra}")
    return 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="check_drops.py", description="落ち先・ID・未決参照・確認依頼・期限の検査")
    ap.add_argument("--file", help="1 ファイルだけ見る（打合せ記録・課題 md・設計書・確認依頼一覧）")
    ap.add_argument("--refs", metavar="NN", help="設計書 NN が参照している未決の一覧")
    ap.add_argument("--quiet", action="store_true", help="5 つの整数だけを 1 行（警告 情報 落ち先なし 決めてほしいこと 期限切れ）")
    ap.add_argument("--strict", action="store_true", help="警告が 1 件以上なら exit 1")
    ap.add_argument("--json", action="store_true", help="JSON で出す")
    ap.add_argument("--root", default=ROOT_DEFAULT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    if args.quiet:
        try:
            ck = Checker(root)
            ck.run()
            c = ck.counts()
            print(f"{c['warn']} {c['info']} {c['orphans']} {c['open_issues']} {c['overdue']}")
        except Exception:
            pass
        return 0

    try:
        ck = Checker(root)
    except Exception as e:
        print(f"check_drops: .claude/hooks/drops.py を読めない（{type(e).__name__}: {e}）", file=sys.stderr)
        return 1 if args.strict else 0

    if args.refs:
        nn = args.refs.strip()
        if not re.fullmatch(r"\d{2}", nn):
            print("エラー: --refs には設計書の 2 桁の番号を渡す（例: --refs 05）", file=sys.stderr)
            return 2
        return print_refs(ck, nn)

    file_rel = None
    if args.file:
        file_rel = to_rel(root, args.file)
        if file_rel.startswith("../") or not os.path.isfile(os.path.join(root, file_rel)):
            print(f"エラー: 案件の中のファイルを渡す: {args.file}", file=sys.stderr)
            return 2
    ck.run(file_rel)
    ck.findings.sort(key=lambda f: (0 if f.level == "warn" else 1, f.file, f.line))
    c = ck.counts()
    if args.json:
        print(json.dumps({"phase": ck.phase, "counts": c, "findings": [f.as_dict() for f in ck.findings]},
                         ensure_ascii=False, indent=2))
    else:
        for f in ck.findings:
            print(f.text())
        tail = f"警告 {c['warn']} 件・情報 {c['info']} 件（フェーズ: {ck.phase}）"
        if file_rel is None and (c["open_issues"] or c["overdue"]):
            tail += f" ／ 決めてほしいこと {c['open_issues']} 件・期限切れ {c['overdue']} 件"
        print(tail)
    return 1 if args.strict and c["warn"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
