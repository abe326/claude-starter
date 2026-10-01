"""案件ごとの設定（.claude/project.json）と、それを使う仕組みのテスト。

project_config の読み込み・形の検査、置き場ガードの許可リスト、影響マップの入れ子リポ解決と差し込み口、
docs_freshness の入れ子リポ、check_skeleton の agents の `_` 除外と差し込み口の行の検査。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from _util import ROOT, TempProject, run_py, write

sys.path.insert(0, str(ROOT / "scripts"))
import check_skeleton as cs  # noqa: E402
import impact_map  # noqa: E402
import project_config  # noqa: E402
import work_area_guard  # noqa: E402


class Recorder:
    def __init__(self):
        self.fails: list[str] = []

    def __call__(self, cond, msg):
        if not cond:
            self.fails.append(msg)
        return cond


def config(root: Path, data) -> None:
    write(root / ".claude/project.json", data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))


class ProjectConfigTest(unittest.TestCase):
    def test_missing_is_default(self):
        with TempProject() as root:
            self.assertEqual(project_config.load(str(root)),
                             {"work_area_allow": [], "nested_repos": [], "save_cues": []})
            self.assertEqual(project_config.problems(str(root)), [])

    def test_broken_json(self):
        with TempProject() as root:
            config(root, "{ not json")
            self.assertEqual(project_config.load(str(root))["work_area_allow"], [])
            self.assertTrue(any("JSON" in p for p in project_config.problems(str(root))))

    def test_types_and_unknown_keys(self):
        with TempProject() as root:
            (root / "repos/a").mkdir(parents=True)
            config(root, {"_説明": "x", "work_area_allow": ["./a.txt", 3], "nested_repos": "repos/a", "extra": []})
            got = project_config.load(str(root))
            self.assertEqual(got["work_area_allow"], ["a.txt"])      # 文字列以外は捨て、./ は外す
            self.assertEqual(got["nested_repos"], [])                # 型違いは既定値
            probs = project_config.problems(str(root))
            self.assertTrue(any("extra" in p for p in probs))
            self.assertTrue(any("nested_repos は文字列のリスト" in p for p in probs))
            self.assertTrue(any("work_area_allow は文字列のリスト" in p for p in probs))
            self.assertFalse(any("_説明" in p for p in probs))

    def test_paths_must_be_relative_and_exist(self):
        with TempProject() as root:
            config(root, {"work_area_allow": ["/etc/x", "../y"], "nested_repos": ["repos/none"]})
            probs = project_config.problems(str(root))
            self.assertEqual(sum("ルート相対" in p for p in probs), 2)
            self.assertTrue(any("実在しない" in p for p in probs))

    def test_save_cues_load_and_problems(self):
        with TempProject() as root:
            config(root, {"save_cues": [
                {"glob": "環境情報.md", "cue": " 値は docs に書かない "},
                {"glob": ["./a/**", "b/*.md"], "cue": "x"},
                {"glob": "c.md", "cue": ""},          # cue が空 → 捨てる
                {"glob": 3, "cue": "y"},              # glob の型違い → 捨てる
                "not a dict",
            ]})
            got = project_config.load(str(root))["save_cues"]
            self.assertEqual(got, [{"globs": ["環境情報.md"], "cue": "値は docs に書かない"},
                                   {"globs": ["a/**", "b/*.md"], "cue": "x"}])
            probs = project_config.problems(str(root))
            self.assertTrue(any("3 件目の cue" in p for p in probs))
            self.assertTrue(any("4 件目の glob は文字列" in p for p in probs))
            self.assertTrue(any("5 件目が glob と cue" in p for p in probs))
            config(root, {"save_cues": [{"glob": "../x", "cue": "y"}]})
            self.assertTrue(any("ルート相対" in p for p in project_config.problems(str(root))))
            config(root, {"save_cues": "x"})
            self.assertTrue(any("オブジェクトのリスト" in p for p in project_config.problems(str(root))))

    def test_template_file_is_clean(self):
        self.assertEqual(project_config.problems(str(ROOT)), [])

    def test_nested_repo_of_longest(self):
        f = project_config.nested_repo_of
        self.assertEqual(f("repos/a/b/x.py", ["repos/a", "repos/a/b"]), "repos/a/b")
        self.assertIsNone(f("repos/ab/x.py", ["repos/a"]))


class GuardAllowTest(unittest.TestCase):
    ALLOW = ["playwright.config.ts", ".work/依存監査ログ.md", ".work/一時/tldv同期/**"]

    def test_template_rules_without_allow(self):
        self.assertIsNotNone(work_area_guard.judge("playwright.config.ts"))
        self.assertIsNotNone(work_area_guard.judge(".work/一時/tldv同期/a.json"))

    def test_allow_passes(self):
        for rel in ("playwright.config.ts", ".work/依存監査ログ.md", ".work/一時/tldv同期/2026/a.json"):
            self.assertIsNone(work_area_guard.judge(rel, self.ALLOW), rel)

    def test_allow_does_not_widen(self):
        self.assertIsNotNone(work_area_guard.judge("other.ts", self.ALLOW))
        self.assertIsNotNone(work_area_guard.judge(".work/一時/他/a.json", self.ALLOW))

    def test_load_allow_from_root(self):
        with TempProject() as root:
            config(root, {"work_area_allow": self.ALLOW})
            self.assertEqual(work_area_guard.load_allow(str(root)), self.ALLOW)


class ImpactMapTest(unittest.TestCase):
    def test_resolve_in_nested_repo(self):
        with TempProject() as root:
            write(root / "repos/ops/tenants.yaml", "a: 1\n")
            self.assertEqual(impact_map.resolve_target("tenants.yaml", str(root)), [])
            config(root, {"nested_repos": ["repos/ops"]})
            self.assertEqual(impact_map.resolve_target("tenants.yaml", str(root)), ["repos/ops/tenants.yaml"])

    def test_local_targets(self):
        with TempProject() as root:
            self.assertEqual(impact_map.local_targets("backend/x.py", str(root)), [])
            write(root / ".claude/hooks/impact_map_local.py",
                  "def targets(rel):\n    return ['tools/a.md'] if rel.startswith('backend/') else []\n")
            self.assertEqual(impact_map.local_targets("backend/x.py", str(root)), ["tools/a.md"])
            self.assertEqual(impact_map.local_targets("frontend/x.ts", str(root)), [])

    def test_local_targets_broken_is_empty(self):
        with TempProject() as root:
            write(root / ".claude/hooks/impact_map_local.py", "def targets(rel):\n    raise RuntimeError\n")
            self.assertEqual(impact_map.local_targets("backend/x.py", str(root)), [])


class CheckSkeletonTest(unittest.TestCase):
    def test_agents_underscore_skipped(self):
        with TempProject() as root:
            write(root / ".claude/agents/_共通.md", "共通の本文（frontmatter なし）\n")
            write(root / ".claude/agents/reviewer.md", "---\nname: reviewer\nmodel: sonnet\n---\n本文\n")
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertFalse(any("agents" in f for f in rec.fails), rec.fails)
            write(root / ".claude/agents/bad.md", "---\nname: bad\n---\n本文\n")
            rec = Recorder()
            cs.check_harness(root, report=rec)
            self.assertTrue(any("bad.md" in f for f in rec.fails), rec.fails)

    def test_local_module_needs_row(self):
        with TempProject(copy=("docs/設計書", ".claude/hooks")) as root:
            rec = Recorder()
            cs.check_design_docs(root, report=rec, secrets=False, template=True)
            base = list(rec.fails)
            write(root / ".claude/hooks/impact_map_local.py", "def targets(rel):\n    return []\n")
            rec = Recorder()
            cs.check_design_docs(root, report=rec, secrets=False, template=True)
            self.assertTrue(any("差し込み口" in f for f in rec.fails), rec.fails)
            readme = root / "docs/設計書/README.md"
            text = readme.read_text(encoding="utf-8").replace(
                "| `docs/設計書/01-概要.md`",
                "| 表で書きにくい判定 | `.claude/hooks/impact_map_local.py` | 差し込み口 |\n| `docs/設計書/01-概要.md`", 1)
            readme.write_text(text, encoding="utf-8")
            rec = Recorder()
            cs.check_design_docs(root, report=rec, secrets=False, template=True)
            self.assertEqual([f for f in rec.fails if "差し込み口" in f], [])
            self.assertEqual(len(rec.fails), len(base), rec.fails)

    def test_project_config_check(self):
        with TempProject() as root:
            config(root, {"nested_repos": ["repos/none"]})
            rec = Recorder()
            cs.check_project_config(root, report=rec)
            self.assertTrue(any("実在しない" in f for f in rec.fails))


def run_hook(name: str, payload: dict, root: Path, phase: str = "開発") -> subprocess.CompletedProcess:
    """hook の .sh を案件の置き場（root）で動かす。実物は root/.claude/hooks/ に複製したもの。"""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), CLAUDE_SKELETON_PHASE=phase,
               PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(["bash", str(root / ".claude/hooks" / name)], input=json.dumps(payload, ensure_ascii=False),
                          env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)


@unittest.skipUnless(shutil.which("bash"), "bash が無い")
class HookEndToEndTest(unittest.TestCase):
    def test_guard_uses_project_json(self):
        with TempProject(copy=(".claude/hooks",)) as root:
            payload = {"tool_name": "Write", "tool_input": {"file_path": ".work/一時/tldv同期/a.json"}}
            self.assertEqual(run_hook("work_area_guard.sh", payload, root).returncode, 2)
            config(root, {"work_area_allow": [".work/一時/tldv同期/**"]})
            self.assertEqual(run_hook("work_area_guard.sh", payload, root).returncode, 0)
            config(root, "{ broken")                                    # 壊れていてもテンプレの判定で動く
            self.assertEqual(run_hook("work_area_guard.sh", payload, root).returncode, 2)

    def test_reminder_uses_local_module(self):
        with TempProject(copy=(".claude/hooks", "docs/設計書")) as root:
            write(root / "docs/設計書/tools/a.md", "# a\n")
            payload = {"tool_name": "Edit", "tool_input": {"file_path": "backend/app/x.py"}}
            self.assertEqual(run_hook("design_docs_reminder.sh", payload, root).stdout.strip(), "")
            write(root / ".claude/hooks/impact_map_local.py",
                  "def targets(rel):\n    return ['tools/a.md'] if rel.startswith('backend/') else []\n")
            out = run_hook("design_docs_reminder.sh", payload, root).stdout
            self.assertIn("docs/設計書/tools/a.md", out)


    def test_reminder_save_cues(self):
        with TempProject(copy=(".claude/hooks", ".claude/project.json", "docs/設計書")) as root:
            # テンプレの既定: .claude/skills/** と 環境情報.md
            payload = {"tool_name": "Edit", "tool_input": {"file_path": ".claude/skills/task/SKILL.md"},
                       "session_id": ""}
            self.assertIn("[保存の促し]", run_hook("design_docs_reminder.sh", payload, root).stdout)
            payload["tool_input"]["file_path"] = "環境情報.md"
            self.assertIn("docs/ に転記しない", run_hook("design_docs_reminder.sh", payload, root).stdout)
            payload["tool_input"]["file_path"] = "README.md"
            self.assertNotIn("[保存の促し]", run_hook("design_docs_reminder.sh", payload, root).stdout)
            # 案件で足した cue は、打合せ記録の促しと一緒に出る
            config(root, {"save_cues": [{"glob": "docs/案件/02_打合せ/*.md", "cue": "議事録を共有フォルダにも置く"}]})
            payload["tool_input"]["file_path"] = "docs/案件/02_打合せ/20260926_定例.md"
            out = run_hook("design_docs_reminder.sh", payload, root).stdout
            self.assertIn("議事録を共有フォルダにも置く", out)
            self.assertIn("[落ち先]", out)


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=str(cwd),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git が無い")
class FreshnessNestedTest(unittest.TestCase):
    def test_nested_repo_source_change(self):
        with TempProject(copy=("scripts/docs_freshness.py", ".claude/hooks")) as root:
            repo = root / "repos/core"
            write(repo / "schemas/a.sql", "create table a();\n")
            git(repo, "init", "-q")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "a")
            sha = git(repo, "rev-parse", "--short", "HEAD")
            write(root / ".gitignore", "repos/\n")
            config(root, {"nested_repos": ["repos/core"]})
            meta = f"> 最終更新: 2099-01-01（APP-01: x）／ 対象: repos/core/schemas/** / core@{sha}"
            write(root / "docs/設計書/02-構成.md", f"# 02 構成\n\n{meta}\n\n本文\n")
            git(root, "init", "-q")
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "root")
            fresh = root / "scripts/docs_freshness.py"

            r = run_py(fresh, "--phase", "開発", cwd=root)
            self.assertIn("0 本の要確認", r.stdout, r.stdout + r.stderr)

            write(repo / "schemas/a.sql", "create table a(id int);\n")
            r = run_py(fresh, "--phase", "開発", cwd=root)
            self.assertIn("core: 未コミット変更あり", r.stdout, r.stdout)
            git(repo, "commit", "-q", "-am", "b")
            r = run_py(fresh, "--phase", "開発", cwd=root)
            self.assertIn("core: ソース変更あり", r.stdout, r.stdout)

    def test_nested_repo_sha_missing(self):
        with TempProject(copy=("scripts/docs_freshness.py", ".claude/hooks")) as root:
            repo = root / "repos/core"
            write(repo / "a.txt", "x\n")
            git(repo, "init", "-q")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "a")
            config(root, {"nested_repos": ["repos/core"]})
            write(root / "docs/設計書/02-構成.md",
                  "# 02\n\n> 最終更新: 2099-01-01（x）／ 対象: repos/core/a.txt / repo@abcdef1\n")
            git(root, "init", "-q")
            r = run_py(root / "scripts/docs_freshness.py", "--phase", "開発", cwd=root)
            self.assertIn("core: sha なし", r.stdout, r.stdout)


if __name__ == "__main__":
    unittest.main()
