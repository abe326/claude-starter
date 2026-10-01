"""check_skeleton.check_harness（ハーネスの形）のテスト。"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest

from _util import ROOT, TempProject, write

sys.path.insert(0, str(ROOT / "scripts"))
import check_skeleton as cs  # noqa: E402

LEDGER_HEAD = """# ハーネス台帳

| ID | 観点 | 内容 | きっかけ（日付・出典） | 状態 | 定義先 | 更新 |
|---|---|---|---|---|---|---|
"""
SEC9 = """# 05

## 9. Claude Code が行ってはいけない操作

| 操作 | なぜ | `permissions.deny` の対応 | 状態 |
|:--|:--|:--|:--|
| 転記 | 回収できない | （`.claude/rules/secrets.md`） | 決定 |
| 履歴の破壊 | 戻せない | `Bash(git push --force *)`・`Bash(git reset --hard *)` | 決定 |
| 本番 | 承認の外 | `Bash(deploy *)` | 提案 |

## 10. 未決
"""


def settings(deny: list[str]) -> str:
    return json.dumps({"permissions": {"allow": [], "deny": deny}})


class Recorder:
    def __init__(self):
        self.fails: list[str] = []

    def __call__(self, cond, msg):
        if not cond:
            self.fails.append(msg)
        return cond


def run_full(root, phase: str) -> tuple[int, int, str]:
    """report なしで回し、(増えた fail, 増えた warn, 出力) を返す。"""
    cs._PHASE = phase
    f0, w0 = cs.FAIL, cs.WARN
    verbose = cs.VERBOSE
    cs.VERBOSE = True
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            cs.check_harness(root)
    finally:
        cs.VERBOSE = verbose
        cs._PHASE = None
    return cs.FAIL - f0, cs.WARN - w0, buf.getvalue()


class Harness(unittest.TestCase):
    def base(self, root, ledger_rows: str = "", deny=None):
        write(root / "docs/ハーネス台帳.md", LEDGER_HEAD + ledger_rows)
        write(root / ".claude/settings.json", settings(deny if deny is not None else []))

    def test_empty_ledger_passes(self):
        with TempProject() as root:
            self.base(root)
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertEqual(rec.fails, [])

    def test_template_itself_passes(self):
        rec = Recorder()
        cs.check_harness(ROOT, report=rec)
        self.assertEqual(rec.fails, [])

    def test_agent_model(self):
        with TempProject() as root:
            self.base(root)
            write(root / ".claude/agents/reviewer.md", "---\nname: reviewer\ndescription: x\n---\n本文\n")
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertEqual(len(rec.fails), 1)
            self.assertIn("reviewer.md", rec.fails[0])
            for model in ("inherit", "sonnet", "claude-sonnet-5"):
                write(root / ".claude/agents/reviewer.md", f"---\nname: reviewer\nmodel: {model}\n---\n")
                rec = Recorder()
                cs.check_harness(root, report=rec)
                self.assertEqual(rec.fails, [], model)
            write(root / ".claude/agents/reviewer.md", "---\nname: reviewer\nmodel: gpt\n---\n")
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertEqual(len(rec.fails), 1)

    def test_ledger_rows(self):
        with TempProject() as root:
            write(root / ".claude/skills/deploy-check/SKILL.md", "---\nname: deploy-check\ndescription: x\n---\n")
            rows = ("| HN-01 | 定型手順 | デプロイ前確認 | 2026-09-23 | 定義済 | `.claude/skills/deploy-check/SKILL.md` | 2026-09-23 |\n"
                    "| HN-02 | 権限 | pytest | 2026-09-23 | 候補 | permissions.allow | 2026-09-23 |\n")
            self.base(root, rows)
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertEqual(rec.fails, [])
            rows_bad = rows + ("| HN-3 | 権限 | x | - | 保留 | - | - |\n"
                               "| HN-04 | 役割 | x | - | 定義済 | `.claude/agents/無い.md` | - |\n"
                               "| HN-05 | 役割 | x | - | 定義済 | 06 §7 | - |\n")
            self.base(root, rows_bad)
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertEqual(len(rec.fails), 4, rec.fails)   # ID の形・状態・定義先が無い・パスが無い

    def test_permission_pattern_in_dest(self):
        # 定義先に権限パターン（Bash(...)）をバッククォートで書いてもパス扱いしない（実地確認で見つかった）
        with TempProject() as root:
            rows = ("| HN-01 | 危険操作 | git push をしない | 2026-09-24 | 定義済 | "
                    "`.claude/settings.json`・`Bash(git push)`・`Bash(git push *)` | 2026-09-24 |\n")
            self.base(root, rows, deny=["Bash(git push)", "Bash(git push *)"])
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertEqual(rec.fails, [])

    def test_section_nine_deny(self):
        with TempProject() as root:
            write(root / "docs/設計書/05-セキュリティ.md", SEC9)
            self.base(root, deny=["Bash(git push --force *)"])
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertEqual(len(rec.fails), 1)
            self.assertIn("git reset --hard", rec.fails[0])
            self.base(root, deny=["Bash(git push --force *)", "Bash(git reset --hard *)"])
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertEqual(rec.fails, [])       # 提案の行は見ない

    def test_unlisted_by_phase(self):
        with TempProject() as root:
            self.base(root)
            write(root / ".claude/skills/deploy-check/SKILL.md", "---\nname: deploy-check\ndescription: x\n---\n")
            write(root / ".claude/hooks/lint_guard.sh", "exit 0\n")
            write(root / ".claude/hooks/lint_guard.py", "pass\n")
            write(root / ".claude/hooks/phase.py", "")
            fail, warn, out = run_full(root, "Sketch")
            self.assertEqual((fail, warn), (0, 0))
            self.assertIn("INFO 台帳に無いハーネス 2 件", out)
            fail, warn, out = run_full(root, "Build")
            self.assertEqual((fail, warn), (0, 1))
            self.assertIn("WARN 台帳に無いハーネス 2 件", out)
            rows = ("| HN-01 | 定型手順 | x | - | 定義済 | `.claude/skills/deploy-check/SKILL.md` | - |\n"
                    "| HN-02 | 品質ゲート | x | - | 定義済 | `.claude/hooks/lint_guard.sh`・settings.json | - |\n")
            self.base(root, rows)
            fail, warn, out = run_full(root, "Build")
            self.assertEqual((fail, warn), (0, 0), out)


class CoreConstants(unittest.TestCase):
    def test_core_skills_exist(self):
        skills = {d.name for d in (ROOT / ".claude/skills").iterdir() if d.is_dir()}
        pending = {"pickup"} - skills          # 担当 Y の実装が揃うまで
        self.assertEqual(skills, cs.CORE_SKILLS - pending)

    def test_core_rules_exist(self):
        rules = {p.name for p in (ROOT / ".claude/rules").glob("*.md")}
        self.assertEqual(rules, cs.CORE_RULES)

    def test_hooks_are_core(self):
        hooks = {p.name for p in (ROOT / ".claude/hooks").iterdir() if p.is_file() and p.suffix in (".sh", ".py")}
        self.assertEqual(hooks - cs.CORE_HOOKS, set())


if __name__ == "__main__":
    unittest.main()
