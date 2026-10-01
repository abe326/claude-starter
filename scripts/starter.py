#!/usr/bin/env python3
"""claude-starter を ~/.claude に展開し、使いながら同期・育てるための入口。標準ライブラリのみ。

使い方:
  python3 scripts/starter.py install [--no-auto-pull] [--dry-run]
      ~/.claude/starter → このリポ、skills・rules をリンク（Windows はジャンクション）、
      CLAUDE.md を読み込み用の短いファイルにし、settings.json を base＋personal から合成する。
      置き換えるものは ~/.claude/backups/starter-YYYYmmdd-HHMMSS/ へ退避する
  python3 scripts/starter.py sync [--hook]
      リンクと settings を最新に揃える（SessionStart hook から毎回呼ばれる）。auto_pull なら 1 日 1 回 git pull
  python3 scripts/starter.py cue
      Stop hook。作業中のプロジェクトの skill・rules・agents・CLAUDE.md の変更を候補として記録する
  python3 scripts/starter.py candidates [--all] [--close ID --as 取り込み|個人|スケルトン|却下 [--note 文]]
      候補の一覧と判定（promote スキルが使う）

個人の部分（リポの外）:
  ~/.claude/CLAUDE.personal.md      個人の決めごと（CLAUDE.md から読み込む）
  ~/.claude/settings.personal.json  個人の設定（base に重ねる。UI で変えた設定も自動でここへ移る）
  ~/.claude/starter.json            このマシンでの動き（auto_pull）
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from typing import Any

sys.dont_write_bytecode = True

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME_SRC = os.path.join(REPO, "home")
STUB_MARK = "<!-- claude-starter:"
CUE_TARGETS = (".claude/skills", ".claude/rules", ".claude/agents")
CUE_FILES = ("CLAUDE.md",)
CUE_SKIP_DIRS = {"node_modules", "__pycache__", ".git"}
PULL_INTERVAL_SEC = 20 * 3600


# ---------- 場所 ----------

def claude_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude")


def state_dir() -> str:
    return os.path.join(claude_dir(), "starter-state")


def paths() -> dict:
    c = claude_dir()
    return {
        "link": os.path.join(c, "starter"),
        "skills": os.path.join(c, "skills"),
        "rules_link": os.path.join(c, "rules", "starter"),
        "claude_md": os.path.join(c, "CLAUDE.md"),
        "personal_md": os.path.join(c, "CLAUDE.personal.md"),
        "settings": os.path.join(c, "settings.json"),
        "personal_settings": os.path.join(c, "settings.personal.json"),
        "config": os.path.join(c, "starter.json"),
        "last_settings": os.path.join(state_dir(), "settings.last.json"),
        "base_settings": os.path.join(HOME_SRC, "settings.base.json"),
        "candidates": os.path.join(REPO, ".work", "promote", "candidates.jsonl"),
    }


def now() -> dt.datetime:
    return dt.datetime.now()


class Backup:
    """置き換える前のものを 1 回の実行につき 1 つのフォルダへ退避する。"""

    def __init__(self) -> None:
        self.dir = None

    def keep(self, path: str, rel: str) -> str:
        if self.dir is None:
            self.dir = os.path.join(claude_dir(), "backups", "starter-" + now().strftime("%Y%m%d-%H%M%S"))
        dst = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if is_link(path):
            with open(dst + ".link.txt", "w", encoding="utf-8") as f:
                f.write(os.path.realpath(path) + "\n")
            unlink_link(path)
        else:
            shutil.move(path, dst)
        return dst


# ---------- リンク（Windows はジャンクション） ----------

def is_link(p: str) -> bool:
    if os.path.islink(p):
        return True
    isj = getattr(os.path, "isjunction", None)
    return bool(isj and isj(p))


def unlink_link(p: str) -> None:
    try:
        os.unlink(p)
    except (IsADirectoryError, PermissionError, OSError):
        os.rmdir(p)  # Windows のジャンクション・ディレクトリへのリンクは rmdir で外す（中身は消えない）


def make_link(target: str, link: str) -> None:
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if os.name == "nt":
        import _winapi  # 標準ライブラリ。ジャンクションは管理者権限が要らない
        _winapi.CreateJunction(target, link)
    else:
        os.symlink(target, link, target_is_directory=True)


def same_place(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def inside(path: str, root: str) -> bool:
    p = os.path.normcase(os.path.realpath(path))
    r = os.path.normcase(os.path.realpath(root))
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def ensure_link(target: str, link: str, rel: str, backup: Backup | None, log: list, dry: bool) -> None:
    """link を target へのリンクにする。別物があれば backup があるときだけ退避して置き換える。"""
    if is_link(link):
        if same_place(link, target):
            return
        if not dry:
            unlink_link(link)
    elif os.path.exists(link):
        if backup is None:
            log.append(f"skip {rel}: 同じ名前の自分のものがある（install で退避して置き換え）")
            return
        if not dry:
            backup.keep(link, rel)
        log.append(f"backup {rel}")
    if not dry:
        make_link(target, link)
    log.append(f"link {rel}")


def sync_links(backup: Backup | None, log: list, dry: bool = False) -> None:
    p = paths()
    ensure_link(REPO, p["link"], "starter", backup, log, dry)
    ensure_link(os.path.join(HOME_SRC, "rules"), p["rules_link"], "rules/starter", backup, log, dry)
    src_skills = os.path.join(HOME_SRC, "skills")
    names = sorted(n for n in os.listdir(src_skills) if os.path.isfile(os.path.join(src_skills, n, "SKILL.md")))
    for n in names:
        ensure_link(os.path.join(src_skills, n), os.path.join(p["skills"], n), f"skills/{n}", backup, log, dry)
    # リポから消えた skill のリンクを外す（自分のものには触らない）
    if os.path.isdir(p["skills"]):
        for n in sorted(os.listdir(p["skills"])):
            lp = os.path.join(p["skills"], n)
            if is_link(lp) and n not in names and inside(os.path.realpath(lp), src_skills):
                if not dry:
                    unlink_link(lp)
                log.append(f"unlink skills/{n}")


def ensure_npm(log: list, dry: bool) -> None:
    """package.json がある skill に node_modules を入れる（npm が無ければ案内だけ）。"""
    src_skills = os.path.join(HOME_SRC, "skills")
    for n in sorted(os.listdir(src_skills)):
        d = os.path.join(src_skills, n)
        if not os.path.isfile(os.path.join(d, "package.json")) or os.path.isdir(os.path.join(d, "node_modules")):
            continue
        npm = shutil.which("npm")
        if not npm:
            log.append(f"note skills/{n}: npm が無いので node_modules を入れていない（そのフォルダで npm install）")
            continue
        if not dry:
            r = subprocess.run([npm, "install", "--no-audit", "--no-fund", "--silent"], cwd=d,
                               capture_output=True, text=True)
            if r.returncode != 0:
                log.append(f"note skills/{n}: npm install に失敗（{r.stderr.strip()[:200]}）")
                continue
        log.append(f"npm skills/{n}")


# ---------- CLAUDE.md ----------

STUB = """<!-- claude-starter: このファイルは starter.py install が作る。直すのは読み込み先 -->
<!-- 汎用の決めごと（公開）: ~/.claude/starter/home/CLAUDE.md -->
<!-- 個人の決めごと（このマシンだけ）: ~/.claude/CLAUDE.personal.md -->
@~/.claude/starter/home/CLAUDE.md
@~/.claude/CLAUDE.personal.md
"""


def ensure_claude_md(backup: Backup | None, log: list, dry: bool) -> None:
    p = paths()
    cur = read_text(p["claude_md"])
    if cur == STUB:
        return
    if cur is not None and not cur.startswith(STUB_MARK):
        if backup is None:
            log.append("skip CLAUDE.md: 自分の CLAUDE.md がある（install で個人の部分へ移す）")
            return
        if not dry:
            backup.keep(p["claude_md"], "CLAUDE.md")
            if not os.path.exists(p["personal_md"]):
                with open(p["personal_md"], "w", encoding="utf-8") as f:
                    f.write(cur)
                log.append("move CLAUDE.md → CLAUDE.personal.md（汎用部と重なる記述は消してよい）")
    if not dry:
        write_text(p["claude_md"], STUB)
    log.append("write CLAUDE.md（読み込み用）")


# ---------- settings ----------

def deep_merge(base, over):
    """dict は再帰、list は和（順序を保ち重複なし）、それ以外は over が勝つ。"""
    if isinstance(base, dict) and isinstance(over, dict):
        out = copy.deepcopy(base)
        for k, v in over.items():
            out[k] = deep_merge(out[k], v) if k in out else copy.deepcopy(v)
        return out
    if isinstance(base, list) and isinstance(over, list):
        out = copy.deepcopy(base)
        for v in over:
            if v not in out:
                out.append(copy.deepcopy(v))
        return out
    return copy.deepcopy(over)


def settings_delta(old, new):
    """old → new で足された・変わった分だけを返す（消された分は数えて返す）。"""
    removed = 0
    if isinstance(old, dict) and isinstance(new, dict):
        out = {}
        for k, v in new.items():
            if k not in old:
                out[k] = copy.deepcopy(v)
                continue
            d, r = settings_delta(old[k], v)
            removed += r
            if d is not None:
                out[k] = d
        removed += sum(1 for k in old if k not in new)
        return (out or None), removed
    if isinstance(old, list) and isinstance(new, list):
        add = [copy.deepcopy(v) for v in new if v not in old]
        removed += sum(1 for v in old if v not in new)
        return (add or None), removed
    return (None if old == new else copy.deepcopy(new)), removed


def _mkdir_backup(backup: Backup) -> str:
    backup.dir = os.path.join(claude_dir(), "backups", "starter-" + now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(backup.dir, exist_ok=True)
    return backup.dir


def py_cmd() -> str:
    return "python3" if shutil.which("python3") else "python"


def render_base() -> dict:
    text = read_text(paths()["base_settings"]) or "{}"
    return json.loads(text.replace("@PY@", py_cmd()))


def sync_settings(log: list, dry: bool = False, backup: Backup | None = None) -> None:
    """settings.json = base ＋ personal。前回書いた後に UI などで変わった分は personal へ移してから作り直す。

    初めて（前回の記録が無い）で personal が無ければ、今の settings.json の base に無い分を personal にする。
    personal を先に用意してあれば、それを正として今の settings.json は退避だけする。
    """
    p = paths()
    base = render_base()
    has_personal = os.path.exists(p["personal_settings"])
    personal = load_json(p["personal_settings"]) or {}
    current = load_json(p["settings"])
    last = load_json(p["last_settings"])
    if current is not None and last is None and backup is not None and not dry:
        shutil.copy2(p["settings"], os.path.join(backup.dir or _mkdir_backup(backup), "settings.json"))
        log.append("backup settings.json")
    if current is not None and not (last is None and has_personal):
        ref = last if last is not None else deep_merge(base, personal)
        delta, removed = settings_delta(ref, current)
        if delta:
            personal = deep_merge(personal, delta)
            if not dry:
                dump_json(p["personal_settings"], personal)
            log.append("settings: 手で変えた分を settings.personal.json へ移した（" + ", ".join(sorted(delta)) + "）")
        if removed and last is not None:
            log.append(f"settings: 消された項目が {removed} 件ある。base 由来なら settings.personal.json では消せない（必要なら base を直す）")
    merged = deep_merge(base, personal)
    if merged == current and merged == last:
        return
    if not dry:
        dump_json(p["settings"], merged)
        os.makedirs(state_dir(), exist_ok=True)
        dump_json(p["last_settings"], merged)
    if merged != current:
        log.append("settings: settings.json を作り直した")


# ---------- 設定と pull ----------

def load_config() -> dict:
    return load_json(paths()["config"]) or {"auto_pull": True}


def maybe_pull(log: list) -> None:
    cfg = load_config()
    if not cfg.get("auto_pull", True) or not os.path.isdir(os.path.join(REPO, ".git")):
        return
    stamp = os.path.join(state_dir(), "last_pull")
    try:
        if now().timestamp() - os.path.getmtime(stamp) < PULL_INTERVAL_SEC:
            return
    except OSError:
        pass
    os.makedirs(state_dir(), exist_ok=True)
    with open(stamp, "w", encoding="utf-8") as f:
        f.write(now().isoformat() + "\n")
    # 待たない。取り込んだ分は次のセッションの sync で効く
    kw: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008  # DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen(["git", "-C", REPO, "pull", "--ff-only", "-q"], **kw)
        log.append("pull: 裏で git pull を始めた")
    except OSError:
        pass


# ---------- 候補（cue / candidates） ----------

def project_root(cwd: str) -> str:
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return os.path.normpath(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.normpath(cwd)


def watched_files(root: str) -> dict:
    out = {}
    for rel in CUE_FILES:
        f = os.path.join(root, rel)
        if os.path.isfile(f) and not is_link(f):
            out[rel] = sha_file(f)
    for t in CUE_TARGETS:
        top = os.path.join(root, t)
        if not os.path.isdir(top) or inside(top, REPO):
            continue
        for d, dirs, files in os.walk(top):
            dirs[:] = [x for x in dirs if x not in CUE_SKIP_DIRS and not (is_link(os.path.join(d, x)) and inside(os.path.join(d, x), REPO))]
            for fn in files:
                f = os.path.join(d, fn)
                if is_link(f) and inside(f, REPO):
                    continue
                out[os.path.relpath(f, root).replace(os.sep, "/")] = sha_file(f)
    return out


def skeleton_files(root: str) -> set:
    d = load_json(os.path.join(root, ".claude", "skeleton.json")) or {}
    return set((d.get("files") or {}).keys())


def load_candidates() -> list:
    out = []
    text = read_text(paths()["candidates"]) or ""
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def save_candidates(items: list) -> None:
    f = paths()["candidates"]
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w", encoding="utf-8", newline="\n") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")


def cue(stdin_text: str) -> dict | None:
    """Stop hook の本体。増えた候補があれば systemMessage を返す。"""
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except ValueError:
        data = {}
    cwd = data.get("cwd") or os.getcwd()
    root = project_root(cwd)
    if inside(root, REPO) or inside(root, claude_dir()):
        return None
    cur = watched_files(root)
    key = hashlib.sha1(os.path.normcase(os.path.realpath(root)).encode("utf-8")).hexdigest()[:16]
    sf = os.path.join(state_dir(), "cue", key + ".json")
    prev = load_json(sf)
    os.makedirs(os.path.dirname(sf), exist_ok=True)
    dump_json(sf, {"root": root, "files": cur})
    if prev is None:  # 初めて見るプロジェクトは基準を取るだけ
        return None
    changed = sorted(k for k, v in cur.items() if prev.get("files", {}).get(k) != v)
    if not changed:
        return None
    items = load_candidates()
    skel = skeleton_files(root)
    stamp = now().strftime("%Y-%m-%d %H:%M")
    added = 0
    for rel in changed:
        hit = next((it for it in items if it["root"] == root and it["file"] == rel and it["status"] == "未判定"), None)
        if hit:
            hit["updated"] = stamp
            continue
        n = max([it.get("id", 0) for it in items] + [0]) + 1
        items.append({"id": n, "created": stamp, "updated": stamp, "root": root,
                      "project": os.path.basename(root), "file": rel,
                      "origin": "skeleton" if rel in skel else "project", "status": "未判定", "note": ""})
        added += 1
    save_candidates(items)
    if not added:
        return None
    return {"systemMessage": f"claude-starter: 共通化の候補が {added} 件増えた（取り込むなら promote スキル）"}


def cmd_candidates(args) -> int:
    items = load_candidates()
    if args.close:
        hit = [it for it in items if it.get("id") == args.close]
        if not hit:
            print(f"候補 {args.close} は無い", file=sys.stderr)
            return 1
        hit[0]["status"] = args.as_
        hit[0]["note"] = args.note or hit[0].get("note", "")
        hit[0]["updated"] = now().strftime("%Y-%m-%d %H:%M")
        save_candidates(items)
        print(f"候補 {args.close} → {args.as_}")
        return 0
    shown = [it for it in items if args.all or it["status"] == "未判定"]
    if not shown:
        print("候補なし")
        return 0
    print("| ID | 更新 | プロジェクト | ファイル | 由来 | 状態 | 場所 |")
    print("|---|---|---|---|---|---|---|")
    for it in shown:
        print(f"| {it['id']} | {it['updated']} | {it['project']} | {it['file']} | {it['origin']} | {it['status']} | {os.path.join(it['root'], it['file'])} |")
    return 0


# ---------- 入口 ----------

def cmd_install(args) -> int:
    log: list = []
    backup = Backup()
    sync_links(backup, log, args.dry_run)
    ensure_claude_md(backup, log, args.dry_run)
    if not args.dry_run and not os.path.exists(paths()["personal_md"]):
        write_text(paths()["personal_md"], read_text(os.path.join(REPO, "personal.example", "CLAUDE.personal.md")) or "")
        log.append("write CLAUDE.personal.md（雛形）")
    sync_settings(log, args.dry_run, backup)
    ensure_npm(log, args.dry_run)
    if not args.dry_run:
        cfg = load_config()
        cfg["auto_pull"] = not args.no_auto_pull
        dump_json(paths()["config"], cfg)
    log.append(f"auto_pull={'off' if args.no_auto_pull else 'on'}")
    for line in log:
        print(line)
    if backup.dir:
        print(f"退避先: {backup.dir}")
    if args.dry_run:
        print("dry-run のため書き込んでいない")
    return 0


def cmd_sync(args) -> int:
    log: list = []
    try:
        if args.hook:
            maybe_pull(log)
        sync_links(None, log)
        if os.path.exists(paths()["claude_md"]) or not args.hook:
            ensure_claude_md(None, log, False)
        sync_settings(log)
        ensure_npm(log, False)
        n = sum(1 for it in load_candidates() if it["status"] == "未判定")
        if n:
            log.append(f"共通化の候補 {n} 件（promote スキルで取り込む）")
    except Exception as e:  # hook はセッションを止めない
        log.append(f"sync に失敗: {e}")
    shown = [x for x in log if not x.startswith("pull:")] if args.hook else log
    if shown:
        print("claude-starter: " + " / ".join(shown))
    return 0


def cmd_cue(_args) -> int:
    try:
        out = cue(sys.stdin.read())
    except Exception:
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


# ---------- 小物 ----------

def read_text(p: str):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def write_text(p: str, text: str) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_json(p: str):
    t = read_text(p)
    if t is None:
        return None
    try:
        return json.loads(t)
    except ValueError:
        return None


def dump_json(p: str, obj) -> None:
    tmp = p + ".tmp"
    write_text(tmp, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, p)


def sha_file(p: str) -> str:
    h = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="claude-starter の展開・同期・候補集め")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("install", help="~/.claude に展開する")
    a.add_argument("--no-auto-pull", action="store_true", help="git pull を自動でしない（同期フォルダ・編集の中心の機）")
    a.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("sync", help="リンクと settings を揃える")
    a.add_argument("--hook", action="store_true", help="SessionStart hook から呼ぶ（pull もする・失敗しても止めない）")
    sub.add_parser("cue", help="Stop hook: 候補を記録する")
    a = sub.add_parser("candidates", help="候補の一覧と判定")
    a.add_argument("--all", action="store_true")
    a.add_argument("--close", type=int)
    a.add_argument("--as", dest="as_", choices=["取り込み", "個人", "スケルトン", "却下"], default="取り込み")
    a.add_argument("--note")
    args = ap.parse_args(argv)
    return {"install": cmd_install, "sync": cmd_sync, "cue": cmd_cue, "candidates": cmd_candidates}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
