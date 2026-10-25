#!/usr/bin/env python3
"""自分のプロジェクトのフォルダの外へ書かせない PreToolUse hook（peer-request スキルの歯止め）。

プロジェクトごとのセッションは自分のフォルダだけを書き、ほかのプロジェクトの書き換えは
そのプロジェクトのセッションへ依頼する。Edit / Write / NotebookEdit の対象が
自分のプロジェクトの外で、通す場所のどれにも当たらなければ拒否する（exit 2）。

効かせるのはプロジェクトごと（既定は何もしない）:
  そのプロジェクトの .claude/settings.local.json か .claude/settings.json の env に
  "CC_OWN_FOLDER_GUARD": "1"
通す場所:
  - 自分のプロジェクト（CLAUDE_PROJECT_DIR。無ければ入力の cwd）
  - ~/.claude/（CLAUDE_CONFIG_DIR があればそこ）・一時フォルダ（scratchpad を含む）
  - 社内連絡の置き場（CC_OFFICE_DIR）
  - ~/.claude/own-folder-allow.txt に書いたパス（1 行 1 つ。# はコメント。~ と $変数 を展開。
    フォルダならその中すべて。* ? [ を含む行は glob として実体のパスに当てる）
リンク経由も実体のパスで判定する。
限界: Bash 経由の書き込みは見ていない（peer-request スキルの決まりで禁止している）。
入力や設定が読めないときは止めない（hook の不具合でセッションを止めない）。
"""
import fnmatch
import json
import os
import sys
import tempfile

FLAG = "CC_OWN_FOLDER_GUARD"
OFFICE = "CC_OFFICE_DIR"
ALLOW_FILE = "own-folder-allow.txt"


def claude_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def real(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.expandvars(os.path.expanduser(path))))


def inside(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def settings_env(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            env = json.load(f).get("env") or {}
        return env if isinstance(env, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def setting(name: str, project: str) -> str:
    """環境変数を優先し、無ければ settings の env を直接読む（hook に env が渡らない場合の備え）。"""
    if os.environ.get(name):
        return os.environ[name]
    for p in (
        os.path.join(project, ".claude", "settings.local.json"),
        os.path.join(project, ".claude", "settings.json"),
        os.path.join(claude_dir(), "settings.json"),
    ):
        v = settings_env(p).get(name)
        if v:
            return str(v)
    return ""


def enabled(project: str) -> bool:
    return setting(FLAG, project).strip().lower() in ("1", "true", "yes", "on")


def allow_entries() -> list:
    try:
        with open(os.path.join(claude_dir(), ALLOW_FILE), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    return [s.strip() for s in lines if s.strip() and not s.strip().startswith("#")]


def allowed_bases(project: str) -> list:
    bases = [project, claude_dir(), tempfile.gettempdir()]
    office = setting(OFFICE, project)
    if office:
        bases.append(office)
    return [real(b) for b in bases]


def matches_entry(path: str, entry: str) -> bool:
    expanded = os.path.expandvars(os.path.expanduser(entry))
    if any(c in expanded for c in "*?["):
        return fnmatch.fnmatch(path, os.path.normcase(expanded))
    if "$" in expanded:  # 展開できなかった変数は当てない（空のパスで広く通さない）
        return False
    return inside(path, real(expanded))


def judge(file_path, cwd=None, project=None):
    """拒否する理由を返す。通すなら None。"""
    if not file_path:
        return None
    project = project or os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    if not enabled(project):
        return None
    path = os.path.expanduser(file_path)
    if not os.path.isabs(path):
        path = os.path.join(cwd or project, path)
    target = real(path)
    if any(inside(target, b) for b in allowed_bases(project)):
        return None
    if any(matches_entry(target, e) for e in allow_entries()):
        return None
    return (
        f"自分のプロジェクト（{real(project)}）の外のファイルは書き換えない: {target}\n"
        "ほかのプロジェクトの作成・修正は、そのプロジェクトのセッションへ peer-request スキルの手順で依頼する。"
        "Bash など別の手段で書き換えて回避しない。"
        f"全員が書く台帳などの例外は {os.path.join(claude_dir(), ALLOW_FILE)} に、ユーザーの承認を得て足す。"
    )


def main() -> int:
    try:
        data = json.load(sys.stdin)
        tool_input = data.get("tool_input") or {}
        file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
        reason = judge(file_path, data.get("cwd"))
    except Exception:  # 入力が読めないときは止めない
        return 0
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
