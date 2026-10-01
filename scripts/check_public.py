#!/usr/bin/env python3
"""公開前の検査。public リポに秘密・個人情報が入っていないかを見る。標準ライブラリのみ。

使い方:
  python3 scripts/check_public.py              作業ツリー（追跡中＋未追跡で ignore されていないもの）
  python3 scripts/check_public.py --history    加えて git の全履歴（コミットメッセージと差分）
  python3 scripts/check_public.py --denylist F 個人語リストを指定（既定 ~/.claude/public-denylist.txt。無ければ形式検査だけ）

見るもの:
  - 形式: トークン・秘密鍵・Slack Webhook・メールアドレス・プライベート IP・ホームの絶対パス
  - 個人語: denylist の語（1 行 1 語。# はコメント。ASCII の語は単語境界で、`re:` で始まる行は正規表現）
    denylist はリポに入れない（それ自体が個人情報）
  - Office 文書（pptx/docx/xlsx/potx）は中の XML の文字と作成者も見る
例外: `.public-allow`（1 行 1 パス、タブの後に理由）にあるファイルは形式検査だけ外す（個人語は外さない）
出力: NG の行と最後に `pass=N fail=M`。fail>0 なら exit 1
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DENY = os.path.join(os.path.expanduser("~"), ".claude", "public-denylist.txt")
OFFICE = (".pptx", ".potx", ".docx", ".dotx", ".xlsx", ".xltx")
BINARY = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip")

PATTERNS = [
    ("トークン(AWS)", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("トークン(GitHub)", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("トークン(Anthropic)", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("トークン(OpenAI)", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("トークン(Slack)", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("Slack Webhook", re.compile(r"hooks\.slack\.com/services/[A-Za-z0-9/]+")),
    ("秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("メールアドレス", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    ("プライベート IP", re.compile(r"\b(?:192\.168|10\.(?:\d{1,3})|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
    # 「~/.claude/starter/home/」のような相対の途中は除く
    ("ホームの絶対パス", re.compile(r"(?:(?<![\w.~/-])/home/|(?<![\w.~/-])/Users/|\b[A-Za-z]:\\\\?Users\\\\?)(?!<)[A-Za-z0-9._-]+")),
]
# 公開してよいメールアドレス・例示用のドメイン
EMAIL_OK = re.compile(r"(?:@users\.noreply\.github\.com|noreply@anthropic\.com|[@.]example\.(?:com|org|net|jp|invalid)|\.(?:invalid|test|example))$", re.I)


def load_denylist(path: str) -> list:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if not t or t.startswith("#"):
                    continue
                if t.startswith("re:"):
                    out.append((t, re.compile(t[3:], re.I)))
                elif t.isascii():
                    out.append((t, re.compile(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", re.I)))
                else:
                    out.append((t, re.compile(re.escape(t))))
    except OSError:
        return []
    return out


def load_allow() -> set:
    out = set()
    try:
        with open(os.path.join(REPO, ".public-allow"), encoding="utf-8") as f:
            for line in f:
                t = line.split("\t", 1)[0].strip()
                if t and not t.startswith("#"):
                    out.add(t)
    except OSError:
        pass
    return out


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else ""


def repo_files() -> list:
    names = git("ls-files", "-z").split("\0") + git("ls-files", "-z", "--others", "--exclude-standard").split("\0")
    return sorted({n for n in names if n and os.path.isfile(os.path.join(REPO, n))})


def text_of(rel: str) -> str | None:
    p = os.path.join(REPO, rel)
    low = rel.lower()
    if low.endswith(OFFICE):
        try:
            with zipfile.ZipFile(p) as z:
                parts = [z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml")]
            return re.sub(r"<[^>]+>", " ", "\n".join(parts))
        except (OSError, zipfile.BadZipFile):
            return None
    if low.endswith(BINARY):
        return None
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", "replace")


def mask(s: str) -> str:
    s = s.strip()
    return s if len(s) <= 6 else s[:3] + "…" + s[-2:]


def scan(label: str, text: str, deny: list, formats: bool) -> list:
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if formats:
            for name, rx in PATTERNS:
                for m in rx.finditer(line):
                    if name == "メールアドレス" and EMAIL_OK.search(m.group(0)):
                        continue
                    hits.append(f"NG {label}:{i}: {name}: {mask(m.group(0))}")
        for term, rx in deny:
            if rx.search(line):
                hits.append(f"NG {label}:{i}: 個人語: {mask(term)}")
    return hits


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="公開前の検査")
    ap.add_argument("--history", action="store_true", help="git の全履歴も見る")
    ap.add_argument("--denylist", default=DEFAULT_DENY)
    args = ap.parse_args(argv)

    deny = load_denylist(args.denylist)
    allow = load_allow()
    if not deny:
        print(f"note: 個人語リストが無い（{args.denylist}）。形式の検査だけ行う")
    ok = ng = 0
    for rel in repo_files():
        text = text_of(rel)
        if text is None:
            continue
        hits = scan(rel + "(名前)", rel, deny, False) + scan(rel, text, deny, rel not in allow)
        for h in hits:
            print(h)
        ng += bool(hits)
        ok += not hits
    if args.history:
        log = git("log", "--all", "-p", "--no-color", "--format=commit %H%n%an <%ae>%n%B")
        # 作業ツリーで例外にしたファイルの差分は形式検査を外す（個人語は見る）
        chunks = re.split(r"(?m)^(?=commit [0-9a-f]{40}$|diff --git )", log)
        hist_hits = []
        for c in chunks:
            m = re.match(r"diff --git a/(\S+)", c)
            formats = not (m and m.group(1) in allow)
            hist_hits += scan("history", c, deny, formats)
        for h in sorted(set(hist_hits)):
            print(h)
        ng += bool(hist_hits)
        ok += not hist_hits
    print(f"pass={ok} fail={ng}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
