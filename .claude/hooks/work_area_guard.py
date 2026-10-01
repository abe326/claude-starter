#!/usr/bin/env python3
"""PreToolUse hook (Write|Edit|MultiEdit): ファイルの置き場違反を止める。

stdin の JSON から tool_input.file_path を読み、$CLAUDE_PROJECT_DIR（無ければ cwd）からの
相対パスで判定する。ブロックするときは exit 2 + stderr にメッセージ（Claude に見える）。
通すときは exit 0。判定できない入力（file_path 無し・JSON 不正）は通す。

ブロックする条件:
  1. プロジェクトルート直下で、許可リストに無いファイル
  2. .work/ 直下のファイル（README.md 以外）
  3. .work/一時/ 直下のファイル（サブフォルダ必須）
  4. .work/一時/<サブ>/ のサブフォルダ名が YYYYMMDD_ で始まらない

.claude/project.json の work_area_allow（ルート相対の glob）に当たるパスは、上の条件より先に通す（案件の仕組みの
固定パス。テンプレの許可リストは書き換えない）。設定が読めないときは許可リストなしで判定する。
ルート外・ディレクトリ配下（src/ docs/ 等）は通す。Windows パス（C:\\…、/c/…、/mnt/c/…）も正規化して扱う。
ルールの正本: .claude/rules/work-area.md
"""
import fnmatch
import json
import os
import posixpath
import re
import sys

# ルート直下に置いてよいファイル（完全一致）
ROOT_ALLOW_EXACT = {
    "CLAUDE.md", "README.md", "CHANGELOG.md", "LICENSE", "LICENSE.md",
    ".gitignore", ".gitattributes", ".editorconfig", ".env", ".env.example",
    "環境情報.md", "案件情報.md",
    ".mcp.json", "Makefile", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "requirements.txt", "requirements-dev.txt", "uv.lock", "poetry.lock", "setup.py", "setup.cfg",
    "tsconfig.json", "next.config.js", "next.config.mjs", "next.config.ts", "vite.config.ts", "vite.config.js",
    "tailwind.config.js", "tailwind.config.ts", "postcss.config.js", "postcss.config.mjs",
    "eslint.config.js", "eslint.config.mjs", ".eslintrc.json", ".prettierrc", ".prettierrc.json",
    "Dockerfile", ".dockerignore", "railway.json", "railway.toml", "vercel.json", "fly.toml",
    "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Gemfile", "Gemfile.lock",
    ".python-version", ".node-version", ".nvmrc", ".tool-versions", ".ruff.toml", "ruff.toml", "mypy.ini", "pytest.ini", "tox.ini",
}
# ルート直下に置いてよいファイル（glob）
ROOT_ALLOW_GLOB = [
    ".env.*", "docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml",
    "Makefile.*", "*.code-workspace",
]


def normalize(path: str) -> str:
    """Windows / Git Bash / WSL のパス表記を 1 つの形（小文字ドライブ + posix 区切り）に寄せる。"""
    p = path.strip().replace("\\", "/")
    m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", p)          # WSL: /mnt/c/...
    if m:
        p = f"{m.group(1).lower()}:/{m.group(2)}"
    m = re.match(r"^/([a-zA-Z])/(.*)$", p)               # Git Bash: /c/...
    if m and not os.path.isdir("/" + m.group(1)):        # Linux の /home 等と区別（実在する 1 文字ディレクトリは除外）
        p = f"{m.group(1).lower()}:/{m.group(2)}"
    m = re.match(r"^([a-zA-Z]):/(.*)$", p)               # Windows: C:/...
    if m:
        p = f"{m.group(1).lower()}:/{m.group(2)}"
    return posixpath.normpath(p)


def is_abs(p: str) -> bool:
    return p.startswith("/") or re.match(r"^[a-z]:/", p) is not None


def relative_to_root(file_path: str, root: str):
    fp = normalize(file_path)
    rt = normalize(root)
    if not is_abs(fp):
        fp = posixpath.normpath(posixpath.join(rt, fp))
    if fp == rt:
        return None
    prefix = rt.rstrip("/") + "/"
    if not fp.startswith(prefix):
        return None                                      # ルート外
    return fp[len(prefix):]


def root_allowed(name: str) -> bool:
    if name in ROOT_ALLOW_EXACT:
        return True
    return any(fnmatch.fnmatch(name, g) for g in ROOT_ALLOW_GLOB)


GUIDE = ("scratch skill（.work/一時/YYYYMMDD_用途/）か work-placement skill で置き場を決めてから書いてください"
         "（.claude/rules/work-area.md）")


def load_allow(root: str) -> list[str]:
    """.claude/project.json の work_area_allow。読めない・import できないときは空（テンプレの判定だけにする）。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import project_config  # noqa: WPS433
        return project_config.load(root)["work_area_allow"]
    except Exception:
        return []


def allowed_by_project(rel: str, allow) -> bool:
    if not allow:
        return False
    try:
        from impact_map import glob_matches  # noqa: WPS433
    except Exception:
        return False
    return any(rel == g or glob_matches(rel, g) for g in allow)


def judge(rel: str, allow=None):
    """違反ならメッセージ、通すなら None。allow は project.json の work_area_allow。"""
    if allowed_by_project(rel, allow):
        return None
    parts = rel.split("/")
    if len(parts) == 1:
        if root_allowed(parts[0]):
            return None
        return f"プロジェクトルート直下にファイルを置けません: {rel}\n{GUIDE}"
    if parts[0] == ".work":
        if len(parts) == 2:
            if parts[1] == "README.md":
                return None
            return f".work/ 直下にファイルを置けません: {rel}\n{GUIDE}"
        if parts[1] == "一時":
            if len(parts) == 3:
                return f".work/一時/ 直下にファイルを置けません（YYYYMMDD_用途/ のサブフォルダが必要）: {rel}\n{GUIDE}"
            if not re.match(r"^\d{8}_.+", parts[2]):
                return (f".work/一時/ のサブフォルダ名は YYYYMMDD_用途 の形にしてください（例: 20260101_比較表）: {rel}\n"
                        f"{GUIDE}")
    return None


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path")
    if not file_path or not isinstance(file_path, str):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    rel = relative_to_root(file_path, root)
    if rel is None:
        return 0
    msg = judge(rel)
    if msg is not None:
        msg = judge(rel, load_allow(root))
    if msg is None:
        return 0
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.stderr.write("[work_area_guard] " + msg + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
