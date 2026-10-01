#!/usr/bin/env python3
"""このプロジェクトがスケルトンの構成を保っているかを検査する。

使い方: python3 scripts/check_skeleton.py [--overview | --docs | --secrets | --harness | --drops] [-v]

出力: `NG <内容>` / `WARN <内容>` 行 + 最後に `pass=N fail=M warn=K`。fail>0 なら exit 1（WARN は fail に数えない）。
-v で OK 行と INFO 行も出す。
--overview は docs/プロジェクト概要.html、--docs は docs/設計書/、--secrets は秘密検出、--harness はハーネスの形、
--drops は scripts/check_drops.py --strict（落ち先の検査。警告があれば NG）だけを行う。
フェーズで厳しさが変わる検査は .claude/hooks/phase.py の表（STRICTNESS）を by_phase() で通す。
止めるのは「形」と「秘密」だけ。空欄・未記入・未決の多さでは止めない。
標準ライブラリのみ使用。プロジェクトルートはこのファイルの親の親。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/hooks"))

# 設計書は育てる: 生成時は 01 だけ。02〜09 の元は docs/設計書/template/（scripts/add_doc.py で足す。検査の対象外）
DESIGN_TEMPLATE_FILES = [
    "docs/設計書/template/catalog.json",
    "docs/設計書/template/02-構成.md",
    "docs/設計書/template/03-関係者.md",
    "docs/設計書/template/04-原則.md",
    "docs/設計書/template/05-セキュリティ.md",
    "docs/設計書/template/06-品質と確認.md",
    "docs/設計書/template/07-変更と反映.md",
    "docs/設計書/template/08-利用者の運用.md",
    "docs/設計書/template/09-非機能と障害時.md",
]

REQUIRED_FILES = [
    "CLAUDE.md", "README.md", "CHANGELOG.md", ".gitignore",
    ".gitattributes", ".editorconfig", ".env.example",
    ".claude/settings.json",
    ".claude/rules/work-area.md",
    ".claude/rules/docs-management.md",
    ".claude/rules/secrets.md",
    ".claude/skills/work-placement/SKILL.md",
    ".claude/skills/scratch/SKILL.md",
    ".claude/skills/update-overview/SKILL.md",
    ".claude/skills/update-env-info/SKILL.md",
    ".claude/skills/task/SKILL.md",
    ".claude/skills/sync-design-docs/SKILL.md",
    ".claude/skills/audit-design-docs/SKILL.md",
    ".claude/hooks/session_context.sh",
    ".claude/hooks/work_area_guard.sh",
    ".claude/hooks/work_area_guard.py",
    ".claude/hooks/design_docs_reminder.sh",
    ".claude/hooks/design_docs_reminder.py",
    ".claude/hooks/impact_map.py",
    ".claude/hooks/tests/skeleton/run-all.sh",
    ".claude/hooks/tests/skeleton/hook-cases-guard.txt",
    ".claude/hooks/tests/skeleton/hook-cases-reminder.txt",
    ".claude/hooks/project_config.py",
    ".claude/hooks/work_log.sh",
    ".claude/project.json",
    ".claude/hooks/phase.py",
    ".claude/hooks/machine_context.py",
    ".claude/skills/harness/SKILL.md",
    "docs/ハーネス台帳.md",
    ".work/README.md",
    "scripts/check_skeleton.py",
    "scripts/docs_freshness.py",
    "scripts/tests/run_tests.py",
    "scripts/tests/secret-cases.txt",
    "docs/README.md",
    "docs/プロジェクト概要.html",
    "docs/案件/README.md",
    "docs/案件/01_タスク管理/README.md",
    "docs/案件/01_タスク管理/詳細仕様.md",
    "docs/案件/01_タスク管理/new.py",
    "docs/案件/01_タスク管理/close.py",
    "docs/案件/01_タスク管理/screen.py",
    "docs/案件/01_タスク管理/build.py",
    "docs/案件/01_タスク管理/areas.json",
    "docs/案件/01_タスク管理/index.html",
    "docs/案件/01_タスク管理/data.js",
    "docs/案件/02_打合せ/README.md",
    "docs/案件/確認依頼一覧.md",
    "docs/設計書/README.md",
    *DESIGN_TEMPLATE_FILES,
    "scripts/add_doc.py",
    "scripts/work_log.py",
    "docs/設計書/decisions/README.md",
    "docs/設計書/runbook/README.md",
    # 情報の流れ（落ち先・拾って流す）
    ".claude/hooks/drops.py",
    ".claude/hooks/pickup_state.py",
    ".claude/hooks/pickup_cue.sh",
    ".claude/hooks/pickup_cue.py",
    ".claude/hooks/pickup_check.sh",
    ".claude/hooks/pickup_check.py",
    ".claude/skills/pickup/SKILL.md",
    "scripts/check_drops.py",
]
REQUIRED_DIRS = [
    ".work/証跡", ".work/機密", ".work/一時", ".work/_bk",
    "docs/案件/01_タスク管理/open",
    "docs/案件/01_タスク管理/closed",
    "docs/案件/01_タスク管理/screens",
]
RULES = ["work-area.md", "docs-management.md", "secrets.md"]

GITIGNORE_REQUIRED = [
    ".work/", "環境情報.md", "案件情報.md", ".env", ".mcp.json",
    ".claude/settings.local.json",
]

OVERVIEW_MARKERS = [
    "updated", "purpose", "principles", "phase", "open-issues", "milestones", "recent-decisions",
    "task-snapshot", "roadmap", "map", "history",
]

# スケルトンが最初から持つハーネス（台帳に書かない）。スケルトン側 scripts/check.py が template の実物と一致するかを見る
CORE_SKILLS = {
    "work-placement", "scratch", "update-overview", "update-env-info", "task",
    "sync-design-docs", "audit-design-docs", "pickup", "harness", "draft-from-existing",
}
CORE_RULES = {"work-area.md", "docs-management.md", "secrets.md"}
CORE_HOOKS = {
    "session_context.sh", "work_area_guard.sh", "work_area_guard.py",
    "design_docs_reminder.sh", "design_docs_reminder.py", "impact_map.py",
    "phase.py", "machine_context.py", "drops.py", "pickup_state.py",
    "pickup_cue.sh", "pickup_cue.py", "pickup_check.sh", "pickup_check.py",
    "project_config.py", "work_log.sh", "skeleton_drift.py",
}
# 案件が任意で置く差し込み口（台帳ではなく影響マップの表に行を書く。check_design_docs が見る）
IMPACT_LOCAL = ".claude/hooks/impact_map_local.py"
HARNESS_LEDGER = "docs/ハーネス台帳.md"
HARNESS_STATES = ("候補", "定義済", "見送り", "マシン依存")
AGENT_MODELS = ("inherit", "haiku", "sonnet", "opus", "fable")

# CLAUDE.md 内のパス記述のうち、実在チェックから除外するパターン
PATH_PATTERN_HINTS = ("YYYY", "MMDD", "NNN", "<", ">", "{", "}", "*", "…", "...", "xxx", "XXX", "用途", "例")
# CLAUDE.md が指してよい生成物（無くても NG にしない。scripts/work_log.py・build.py が作る）
GENERATED_PREFIXES = ("docs/案件/作業ログ/",)

TEXT_EXTS = {
    ".md", ".html", ".py", ".json", ".js", ".sh", ".yml", ".yaml", ".toml",
    ".txt", ".example", ".css",
}

VERBOSE = "-v" in sys.argv[1:]
PASS = 0
FAIL = 0
WARN = 0
_PHASE: str | None = None


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    if VERBOSE:
        print(f"OK {msg}")


def ng(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"NG {msg}")


def warn(msg: str) -> None:
    """fail に数えない指摘。末尾の warn=K に数える。"""
    global WARN
    WARN += 1
    print(f"WARN {msg}")


def info(msg: str) -> None:
    """件数だけの情報。-v のときだけ出す。"""
    if VERBOSE:
        print(f"INFO {msg}")


def check(cond: bool, msg: str) -> bool:
    (ok if cond else ng)(msg)
    return cond


def current_phase() -> str:
    global _PHASE
    if _PHASE is None:
        try:
            import phase
            _PHASE = phase.read_phase(ROOT)
        except Exception:
            _PHASE = "Sketch"
    return _PHASE


def phase_level(mechanism: str) -> str:
    try:
        import phase
        return phase.level(mechanism, current_phase())
    except Exception:
        return "info"


def by_phase(mechanism: str, cond: bool, msg: str) -> bool:
    """フェーズ依存の検査。cond が偽のとき、phase.py の表のレベルで NG / WARN / INFO / 何もしない に振り分ける。"""
    if cond:
        ok(msg)
        return True
    lv = phase_level(mechanism)
    if lv == "block":
        ng(msg)
    elif lv == "warn":
        warn(msg)
    elif lv == "info":
        info(msg)
    return False


def parse_frontmatter(path: Path) -> dict[str, str] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    fm: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fm
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return None


def walk_json_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_json_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_json_strings(v)


def check_overview() -> None:
    overview = ROOT / "docs/プロジェクト概要.html"
    try:
        html = overview.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        ng("docs/プロジェクト概要.html を読めない")
        return
    for name in OVERVIEW_MARKERS:
        b = len(re.findall(rf"<!--\s*BEGIN:{re.escape(name)}\s*-->", html))
        e = len(re.findall(rf"<!--\s*END:{re.escape(name)}\s*-->", html))
        check(b == 1 and e == 1, f"概要 HTML マーカー {name}: BEGIN={b} END={e}")
    check(not re.search(r"<script[^>]*\ssrc=", html, re.I), "概要 HTML に外部 <script src= が無い")
    check(not re.search(r"<link\s[^>]*href=", html, re.I), "概要 HTML に外部 <link href= が無い")
    check(bool(re.search(r'charset="utf-8"', html, re.I)), '概要 HTML に charset="UTF-8" がある')
    check_phase_attr()


def check_phase_attr() -> None:
    """phase ブロックの data-phase。不正な値は NG、属性が無い（v1.1.0 以前の案件）は WARN。"""
    try:
        import phase
    except ImportError:
        ng("フェーズ: .claude/hooks/phase.py を import できない")
        return
    _, problem = phase.phase_status(ROOT)
    if problem is None:
        ok("概要 HTML の phase ブロックに data-phase（Sketch / Build。旧い値は読み替え）がある")
    elif problem.startswith("不正な値"):
        ng(f"概要 HTML の data-phase が {' / '.join(phase.PHASES)} のどれでもない（{problem}）")
    elif problem == "属性なし":
        warn("概要 HTML の phase ブロックに data-phase が無い（Sketch 扱い）。"
             "python3 .claude/hooks/phase.py --set <Sketch|Build> で設定する")
    # 読めない・ブロックなしはマーカー検査が NG を出す

# 鮮度メタ行（2 行目付近）。template 検査では日付の代わりに 2026-10-01 プレースホルダも通す
META_RE = re.compile(r"^> 最終更新: \d{4}-\d{2}-\d{2}（.+）／ 対象: .+")
META_RE_TEMPLATE = re.compile(r"^> 最終更新: (?:\d{4}-\d{2}-\d{2}|\{\{CREATED\}\})（.+）／ 対象: .+")
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")
DESIGN_EXCLUDE_DIRS = {"decisions", "runbook", "template"}

# ---------------------------------------------------------------------------
# 秘密検出（secret_hits）。値そのものは NG 文言に出さない（ファイル: 行番号だけ）
#   1) 既知のトークン形式 2) スキームを問わない URL 資格情報 3) key = value / key: value（記号入りの値も）
#   当たった値が短い・非 ASCII・伏せ字・プレースホルダ・環境変数名・参照の書き方なら秘密とみなさない。
#   同じ行に `secret-scan: ok <理由>` があれば除外（HTML コメントで書く）。ケース表は scripts/tests/secret-cases.txt
# ---------------------------------------------------------------------------
SECRET_TOKEN_RES = [re.compile(p) for p in (
    r"\bAKIA[0-9A-Z]{16}\b", r"\bgh[pousr]_[A-Za-z0-9]{36,}", r"\bsk-[A-Za-z0-9_\-]{20,}",
    r"\bxox[abprs]-[A-Za-z0-9\-]{10,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)]
SECRET_URL_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://([^\s/:@]*):([^\s/@]+)@")
SECRET_KEY_RE = re.compile(
    r"(?i)(?<![a-z0-9])(?:[a-z0-9]+[_-])*(password|passwd|pwd|pass|secret|token|api[_-]?key|access[_-]?key"
    r"|client[_-]?secret|private[_-]?key|パスワード|トークン|秘密鍵)(?![a-z0-9])\s*[:=：]\s*['\"`]?([^\s'\"`<>|、。，,;]+)")
_SECRET_PLACEHOLDER = re.compile(
    r"(?i)^(\*+|x+|\.{3,}|…+|<.*>|\$\{?\w+\}?|%\w+%|\{\{\s*\w+\s*\}\}|changeme|dummy|example|sample|redacted"
    r"|none|null|true|false|required|optional|pass|password|passwd|pw|secret|user|token)$")
_SECRET_REF = re.compile(r"(?i)^(os\.|process\.env|getenv|env\(|secrets\.|vault:)|[\(\[]|\.md$")
_SECRET_ENVNAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
SECRET_OPT_OUT = "secret-scan: ok"
SECRET_EXCLUDE_NAMES = {"環境情報.md", "案件情報.md"}


def _secret_value_ok(v: str, minlen: int) -> bool:
    """秘密とみなさない値なら True。"""
    if len(v) < minlen or any(ord(c) > 0x7e for c in v):
        return True
    return bool(_SECRET_PLACEHOLDER.match(v) or _SECRET_REF.search(v) or _SECRET_ENVNAME.match(v))


def secret_hits(line: str) -> bool:
    """行に秘密らしき文字列があれば True。`secret-scan: ok` のある行は False。"""
    if SECRET_OPT_OUT in line:
        return False
    if any(r.search(line) for r in SECRET_TOKEN_RES):
        return True
    if any(not _secret_value_ok(m.group(2), 1) for m in SECRET_URL_RE.finditer(line)):
        return True
    return any(not _secret_value_ok(m.group(2), 8) for m in SECRET_KEY_RE.finditer(line))


def secret_targets(root: Path, design_only: bool = False) -> list[Path]:
    """秘密検出の対象。design_only は概要 HTML + 設計書（--docs の現行互換の範囲）。"""
    root = Path(root)
    if design_only:
        base = root / "docs/設計書"
        return [root / "docs/プロジェクト概要.html"] + (sorted(base.rglob("*.md")) if base.is_dir() else [])
    out: list[Path] = [root / n for n in ("CLAUDE.md", "README.md", "CHANGELOG.md")]
    for sub, pats in (("docs", ("*.md", "*.html")), (".claude", ("*.md",))):
        base = root / sub
        if base.is_dir():
            for pat in pats:
                out += sorted(base.rglob(pat))
    return [p for p in out if p.name not in SECRET_EXCLUDE_NAMES and not p.name.startswith(".env")
            and ".work" not in p.relative_to(root).parts]


def check_secrets(root: Path = ROOT, report=None, design_only: bool = False) -> int:
    """秘密らしき文字列を検査する（全フェーズで止める）。戻り値は `secret-scan: ok` で除外した行数。"""
    chk = report or check
    root = Path(root)
    skipped = 0
    for p in secret_targets(root, design_only):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        hits = []
        for i, l in enumerate(lines, 1):
            if SECRET_OPT_OUT in l:
                skipped += 1
            elif secret_hits(l):
                hits.append(i)
        rel = p.relative_to(root).as_posix()
        chk(not hits, f"{rel}: 秘密らしき文字列（行 {', '.join(map(str, hits[:5]))}。値は 環境情報.md へ。"
                      f"誤検知なら行に <!-- secret-scan: ok 理由 -->）" if hits else f"{rel}: 秘密らしき文字列なし")
    if skipped and report is None:
        info(f"秘密検出: secret-scan: ok で除外した行 {skipped} 行")
    return skipped


def iter_design_docs(root: Path) -> list[Path]:
    """鮮度メタ行・改訂履歴の検査対象（decisions/・runbook/・README.md を除く）。"""
    base = root / "docs/設計書"
    if not base.is_dir():
        return []
    return [p for p in sorted(base.rglob("*.md"))
            if p.relative_to(base).parts[0] not in DESIGN_EXCLUDE_DIRS and p.name != "README.md"]


def check_design_docs(root: Path = ROOT, template: bool = False, report=None, secrets: bool = True) -> None:
    """docs/設計書/ の約束を検査する（メタ行・改訂履歴・索引・影響マップ・秘密・docs_freshness.py）。

    template=True はスケルトンの template/ を対象にする（2026-10-01 を許容、docs_freshness.py の結果と
    フェーズ依存の検査は見ない）。report は check(cond, msg) 互換の関数。省略時はこのモジュールの check。
    secrets=False は秘密検出を飛ばす（check_all が全範囲の check_secrets を別に呼ぶため）。
    """
    chk = report or check
    base = root / "docs/設計書"
    if not chk(base.is_dir(), "docs/設計書/ がある"):
        return
    meta_re = META_RE_TEMPLATE if template else META_RE

    # (i) メタ行 (ii) 改訂履歴
    for p in iter_design_docs(root):
        rel = p.relative_to(root).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            chk(False, f"{rel} を読めない")
            continue
        head = text.splitlines()[:20]
        meta = next((l for l in head if meta_re.match(l)), None)
        chk(meta is not None, f"{rel}: 冒頭に鮮度メタ行（> 最終更新: YYYY-MM-DD（…）／ 対象: …）がある")
        if meta is not None and not template:
            chk(not PLACEHOLDER_RE.search(meta), f"{rel}: メタ行にプレースホルダが残っていない")
        chk(bool(re.search(r"^## 改訂履歴", text, re.M)), f"{rel}: ## 改訂履歴 がある")

    # 索引: 直下の NN-*.md が README に載っている / README が指す NN-*.md が実在する
    readme = base / "README.md"
    try:
        readme_text = readme.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        chk(False, "docs/設計書/README.md を読めない")
        return
    for p in sorted(base.glob("*.md")):
        if re.match(r"^\d{2}-.*\.md$", p.name):
            chk(p.name in readme_text, f"索引漏れ: docs/設計書/README.md に {p.name} が載っている")
    for name in sorted(set(re.findall(r"`(\d{2}-[^`/]+\.md)`", readme_text))):
        chk((base / name).is_file(), f"死に索引: README.md が指す {name} が実在する")

    # 影響マップ
    try:
        import impact_map
    except ImportError:
        chk(False, "影響マップ: .claude/hooks/impact_map.py を import できない")
        return
    rows = impact_map.load_impact_map(str(readme))
    if chk(len(rows) >= 1, f"影響マップ（## 変えたもの → 一緒に直す正本）に機械行が 1 行以上ある: {len(rows)} 行"):
        for row in rows:
            for g in row.globs:
                try:
                    impact_map.glob_matches("x/y", g)
                    usable = True
                except re.error:
                    usable = False
                chk(usable, f"影響マップ {row.line_no} 行目: glob が使える: {g}")
            chk(bool(row.targets), f"影響マップ {row.line_no} 行目: 一緒に直す正本が 1 つ以上ある")
            for t in row.targets:
                chk(bool(impact_map.resolve_target(t, str(root))),
                    f"影響マップ {row.line_no} 行目: 正本が実ファイルに解決できる: {t}")

    # 差し込み口（任意）: 置いたなら、影響マップの表にそれを指す行がある（表を唯一の入口に保つ）
    if (root / IMPACT_LOCAL).is_file():
        section = readme_text.split("## 変えたもの", 1)[1].split("\n## ", 1)[0] if "## 変えたもの" in readme_text else ""
        table = [l for l in section.splitlines() if l.lstrip().startswith("|")]    # 説明文ではなく表の行
        chk(any(f"`{IMPACT_LOCAL}`" in l for l in table),
            f"差し込み口 {IMPACT_LOCAL} を置いたら、docs/設計書/README.md の影響マップの表にそれを指す行を書く")

    # 秘密らしき文字列（概要 HTML + 全設計書。check_all は全範囲を check_secrets で別に見る）
    if secrets:
        check_secrets(root, report=report, design_only=True)

    # docs_freshness.py --quiet が整数、--counts が 2 整数を返す（鮮度の中身では fail にしない）
    fresh = root / "scripts/docs_freshness.py"
    if fresh.is_file() and not template:
        r = _run_py(fresh, "--quiet", cwd=root)
        chk(r.returncode == 0 and r.stdout.strip().isdigit(),
            f"docs_freshness.py --quiet が整数を返す（exit {r.returncode}: {r.stdout.strip()[:20]!r}）")
        r = _run_py(fresh, "--counts", cwd=root)
        nums = r.stdout.split()
        if chk(r.returncode == 0 and len(nums) == 2 and all(n.isdigit() for n in nums),
               f"docs_freshness.py --counts が 2 整数を返す（exit {r.returncode}: {r.stdout.strip()[:20]!r}）"):
            if report is None:
                by_phase("docs_unfilled", nums[1] == "0",
                         f"雛形のままの設計書: 未記入 {nums[1]} 本（節を 1 行でも埋めてメタ行を書き換えれば外れる）")


def _run_py(script: Path, *args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run([sys.executable, str(script), *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def check_drops_quiet() -> None:
    """scripts/check_drops.py --quiet が 5 つの整数を返す（中身では fail にしない）。"""
    drops = ROOT / "scripts/check_drops.py"
    if not drops.is_file():
        return
    r = _run_py(drops, "--quiet")
    nums = r.stdout.split()
    check(r.returncode == 0 and len(nums) == 5 and all(n.isdigit() for n in nums),
          f"check_drops.py --quiet が 5 つの整数を返す（exit {r.returncode}: {r.stdout.strip()[:30]!r}）")


def check_drops_strict() -> None:
    """--drops: scripts/check_drops.py --strict（警告があれば exit 1）。"""
    drops = ROOT / "scripts/check_drops.py"
    if not check(drops.is_file(), "scripts/check_drops.py がある"):
        return
    r = _run_py(drops, "--strict")
    if not check(r.returncode == 0, f"check_drops.py --strict が exit 0（実際: {r.returncode}）"):
        for line in (r.stdout + r.stderr).strip().splitlines()[-10:]:
            print(f"   | {line}")


# ---------------------------------------------------------------------------
# ハーネスの形（harness スキル・docs/ハーネス台帳.md）
# ---------------------------------------------------------------------------
_TABLE_SPLIT = re.compile(r"(?<!\\)\|")
_BACKTICK = re.compile(r"`([^`]+)`")
_PERMISSION_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*\(.*\)$")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in _TABLE_SPLIT.split(line.strip().strip("|"))]


def parse_ledger(root: Path) -> list[tuple[int, list[str]]]:
    """台帳の表の行（見出し・区切りを除く）を (行番号, セル) で返す。読めなければ空。"""
    try:
        lines = (Path(root) / HARNESS_LEDGER).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    rows = []
    for i, line in enumerate(lines, 1):
        if not line.lstrip().startswith("|"):
            continue
        cells = _cells(line)
        if not cells or cells[0] in ("ID", "") or set(cells[0]) <= set(":-"):
            continue
        rows.append((i, cells))
    return rows


def _dest_paths(cell: str) -> list[str]:
    """定義先セルのバッククォート内のパス（末尾の ` §n` は捨てる）。
    `Bash(git push *)` のような権限パターン（ツール名(…)）はパスではないので除く。実在は settings.json 側で決まる。"""
    out = []
    for t in _BACKTICK.findall(cell):
        t = t.strip()
        if not t or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\(.*\)", t):
            continue
        out.append(re.sub(r"\s*§.*$", "", t).strip())
    return out


def section_nine_patterns(root: Path) -> list[tuple[str, list[str]]]:
    """05 §9 の表のうち状態が「決定」の行の (操作, deny 列の権限パターン)。05 を足していなければ空（対象ゼロ）。
    05 は番号で探す（旧い名前 05-セキュリティ設計.md の案件もある）。"""
    hits = sorted((Path(root) / "docs/設計書").glob("05-*.md"))
    try:
        text = hits[0].read_text(encoding="utf-8") if hits else ""
    except (OSError, UnicodeDecodeError):
        return []
    m = re.search(r"^## 9\..*?$(.*?)(?=^## )", text, re.M | re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) >= 4 and cells[-1] == "決定":
            pats = [t for t in _BACKTICK.findall(cells[2]) if _PERMISSION_PATTERN.match(t)]
            out.append((cells[0][:30], pats))
    return out


def check_harness(root: Path = ROOT, report=None, template: bool = False) -> None:
    """ハーネスの形を検査する。定義したものの形だけを見る（何も定義しなければ対象ゼロ）。

    止める: agents の model・台帳の ID/状態/定義済の定義先の実在・05 §9 決定行の deny パターン。
    フェーズ依存（harness_unlisted）: コア以外の skill・rules・agents・hook が台帳の定義済に無い。template=True では見ない。
    """
    chk = report or check
    root = Path(root)

    # agents の model（`_` で始まるファイルは共通の本文でエージェントではないので除く）
    agents = root / ".claude/agents"
    agent_files = [p for p in sorted(agents.rglob("*.md")) if not p.name.startswith("_")] if agents.is_dir() else []
    if agent_files:
        for p in agent_files:
            fm = parse_frontmatter(p) or {}
            model = fm.get("model", "")
            chk(model in AGENT_MODELS or model.startswith("claude-"),
                f"agents {p.relative_to(root).as_posix()}: frontmatter に model（{' / '.join(AGENT_MODELS)} か claude-…）"
                f"がある（実際: {model!r}）")

    # 台帳
    rows = parse_ledger(root)
    defined: list[str] = []
    for line_no, cells in rows:
        where = f"{HARNESS_LEDGER} {line_no} 行目"
        chk(bool(re.fullmatch(r"HN-\d{2,}", cells[0])), f"{where}: ID が HN-NN の形（{cells[0]!r}）")
        if not chk(len(cells) >= 7, f"{where}: 7 列（ID・観点・内容・きっかけ・状態・定義先・更新）"):
            continue
        state, dest = cells[4], cells[5]
        chk(state in HARNESS_STATES, f"{where}: 状態が {' / '.join(HARNESS_STATES)} のどれか（{state!r}）")
        if state == "定義済":
            paths = _dest_paths(dest)
            if chk(bool(paths), f"{where}: 定義済の定義先にバッククォートでパスがある"):
                for d in paths:
                    chk((root / d.rstrip("/")).exists(), f"{where}: 定義先が実在する: {d}")
                defined += paths
    if not rows:
        ok("ハーネス台帳: 行なし（対象ゼロ）")

    # 05 §9 の決定行 ↔ settings.json の deny
    deny: list[str] = []
    try:
        deny = list(json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
                    .get("permissions", {}).get("deny", []))
    except (OSError, ValueError, AttributeError):
        pass
    for op, pats in section_nine_patterns(root):
        for pat in pats:
            chk(pat in deny, f"05 §9 の決定行「{op}」の {pat} が .claude/settings.json の permissions.deny にある")

    if template or report is not None:
        return
    # 台帳に無いハーネス（フェーズ依存）
    def listed(prefix: str) -> bool:
        return any(d == prefix or d.startswith(prefix + "/") or d.startswith(prefix + ".") for d in defined)

    unlisted: list[str] = []
    skills = root / ".claude/skills"
    if skills.is_dir():
        unlisted += [f"skill {d.name}" for d in sorted(skills.iterdir())
                     if d.is_dir() and d.name not in CORE_SKILLS and not listed(f".claude/skills/{d.name}")]
    rules = root / ".claude/rules"
    if rules.is_dir():
        unlisted += [f"rule {p.name}" for p in sorted(rules.glob("*.md"))
                     if p.name not in CORE_RULES and not listed(f".claude/rules/{p.stem}")]
    if agent_files:
        unlisted += [f"agent {p.name}" for p in agent_files
                     if not listed(p.relative_to(root).with_suffix("").as_posix())]
    hooks = root / ".claude/hooks"
    if hooks.is_dir():
        stems = sorted({p.stem for p in hooks.iterdir()
                        if p.is_file() and p.suffix in (".sh", ".py") and p.name not in CORE_HOOKS
                        and p.name != Path(IMPACT_LOCAL).name})
        unlisted += [f"hook {s}" for s in stems if not listed(f".claude/hooks/{s}")]
    by_phase("harness_unlisted", not unlisted,
             f"台帳に無いハーネス {len(unlisted)} 件（{', '.join(unlisted[:5])}）。"
             f"{HARNESS_LEDGER} に定義済で 1 行ずつ書く（harness スキル）" if unlisted
             else "台帳に無いハーネスなし")


def check_project_config(root: Path = ROOT, report=None) -> None:
    """`.claude/project.json`（無ければ既定値で対象ゼロ）の形。hook は壊れていても止めないので、ここで拾う。"""
    chk = report or check
    try:
        import project_config
    except ImportError:
        chk(False, "project.json: .claude/hooks/project_config.py を import できない")
        return
    probs = project_config.problems(str(root))
    for p in probs:
        chk(False, p)
    if not probs:
        chk(True, f"{project_config.CONFIG} の形")


def check_skeleton_record(root: Path = ROOT, report=None) -> None:
    """`.claude/skeleton.json`（init.py の記録）の形と、スケルトンとのずれ。ずれは warn・info で出す（NG にしない）。"""
    chk = report or check
    path = root / ".claude/skeleton.json"
    if not path.exists():
        info("記録 .claude/skeleton.json が無い（スケルトンの init.py --merge を 1 回通すと作られる）")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        chk(False, f".claude/skeleton.json を読めない（{e}）。スケルトンの init.py --merge で作り直す")
        return
    if not chk(isinstance(data, dict) and isinstance(data.get("version"), str) and isinstance(data.get("files"), dict),
               ".claude/skeleton.json の形（version・files）"):
        return
    try:
        import skeleton_drift
        s = skeleton_drift.status(str(root))
    except Exception:
        return
    if s["behind"]:
        warn(f"スケルトン: v{s['project']} → v{s['skeleton']} が出ている（new-project スキルで更新）")
    if s["local_mechanisms"]:
        head = "、".join(s["local_mechanisms"][:5]) + (" ほか" if len(s["local_mechanisms"]) > 5 else "")
        info(f"案件で直した仕組み {len(s['local_mechanisms'])} 件: {head}（スケルトンにも返すなら台帳の「返す」列へ）")


def check_all() -> None:
    # 必須ファイル・ディレクトリ
    for rel in REQUIRED_FILES:
        check((ROOT / rel).is_file(), f"必須ファイル: {rel}")
    for rel in REQUIRED_DIRS:
        check((ROOT / rel).is_dir(), f"必須ディレクトリ: {rel}")
    # 01 の設計書（名前・拡張子は問わない。既存案件は 01-overview.md や独自の名前のことがある）
    check(any(p.is_file() for p in (ROOT / "docs/設計書").glob("01-*")), "必須ファイル: docs/設計書/01-*（01 の設計書）")

    # CLAUDE.md 内の相対パスが実在
    claude_md = ROOT / "CLAUDE.md"
    if claude_md.is_file():
        text = claude_md.read_text(encoding="utf-8", errors="replace")
        seen: set[str] = set()
        for m in re.finditer(r"`((?:docs|\.claude|scripts|\.work)/[^`\s]+)`", text):
            rel = m.group(1)
            if rel in seen or any(h in rel for h in PATH_PATTERN_HINTS) or rel.startswith(GENERATED_PREFIXES):
                continue
            seen.add(rel)
            target = ROOT / rel.rstrip("/")
            check(target.exists(), f"CLAUDE.md が参照するパスが実在: {rel}")
        if not seen:
            ok("CLAUDE.md に検査対象のパス記述なし")

    # skills の frontmatter
    skills_dir = ROOT / ".claude/skills"
    if skills_dir.is_dir():
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir():
                continue
            fm = parse_frontmatter(d / "SKILL.md")
            if not check(fm is not None, f"skill {d.name}: SKILL.md に frontmatter がある"):
                continue
            check(fm.get("name") == d.name, f"skill {d.name}: name がディレクトリ名と一致({fm.get('name')!r})")
            check(bool(fm.get("description")), f"skill {d.name}: description が非空")

    # rules 3 本
    for name in RULES:
        check((ROOT / ".claude/rules" / name).is_file(), f"rules: {name}")

    # settings.json の hooks が実在
    settings = None
    try:
        settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
        ok(".claude/settings.json が JSON として読める")
    except (OSError, json.JSONDecodeError) as e:
        ng(f".claude/settings.json を読めない: {e}")
    if isinstance(settings, dict):
        referenced = set()
        for s in walk_json_strings(settings.get("hooks", {})):
            referenced.update(re.findall(r"\.claude/hooks/[\w./-]+\.(?:sh|py)", s))
        for rel in sorted(referenced):
            check((ROOT / rel).is_file(), f"hooks が参照するスクリプトが実在: {rel}")

    # プレースホルダ残存なし
    leftovers: dict[str, set[str]] = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".work", "__pycache__", "node_modules")]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix != "" and p.suffix.lower() not in TEXT_EXTS:
                continue
            try:
                t = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            found = set(re.findall(r"\{\{[A-Z_]+\}\}", t))
            if found:
                leftovers[p.relative_to(ROOT).as_posix()] = found
    if leftovers:
        for f, names in sorted(leftovers.items()):
            ng(f"プレースホルダが残っている {', '.join(sorted(names))}: {f}")
    else:
        ok("プレースホルダの残存なし")

    # 概要 HTML
    check_overview()

    # 設計書（秘密検出は下の check_secrets が全範囲で見る）
    check_design_docs(secrets=False)

    # 秘密（docs/ 全体・CLAUDE.md・README.md・CHANGELOG.md・.claude/**/*.md）
    check_secrets()

    # ハーネスの形
    check_harness()

    # 案件ごとの設定 .claude/project.json の形
    check_project_config()

    # スケルトンの記録とずれ（ずれは info）
    check_skeleton_record()

    # 落ち先の検査が動く（中身では fail にしない。一覧は python3 scripts/check_drops.py）
    check_drops_quiet()

    # .gitignore
    gi = ROOT / ".gitignore"
    if gi.is_file():
        lines = {
            l.strip().lstrip("/").rstrip("/")
            for l in gi.read_text(encoding="utf-8", errors="replace").splitlines()
            if l.strip() and not l.strip().startswith("#")
        }
        for entry in GITIGNORE_REQUIRED:
            check(entry.rstrip("/") in lines, f".gitignore に {entry} がある")

    # build.py --check
    build_py = ROOT / "docs/案件/01_タスク管理/build.py"
    if build_py.is_file():
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        r = subprocess.run([sys.executable, str(build_py), "--check"], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if not check(r.returncode == 0, f"build.py --check が exit 0(実際: {r.returncode})"):
            for line in (r.stdout + r.stderr).strip().splitlines()[-10:]:
                print(f"   | {line}")

    # areas.json
    areas_path = ROOT / "docs/案件/01_タスク管理/areas.json"
    if areas_path.is_file():
        try:
            data = json.loads(areas_path.read_text(encoding="utf-8"))
            check(isinstance(data, dict) and isinstance(data.get("areas"), dict),
                  "areas.json の areas が dict")
        except (OSError, json.JSONDecodeError) as e:
            ng(f"areas.json を読めない: {e}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = sys.argv[1:]
    if "--overview" in args:
        check_overview()
    elif "--docs" in args:
        check_design_docs()
    elif "--secrets" in args:
        check_secrets()
    elif "--harness" in args:
        check_harness()
    elif "--drops" in args:
        check_drops_strict()
    else:
        check_all()
    print(f"pass={PASS} fail={FAIL} warn={WARN}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
