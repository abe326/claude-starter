"""scripts/add_doc.py（設計書を 1 本ずつ足す）のテスト。"""
from __future__ import annotations

import json
import re
import unittest

from _util import ROOT, TempProject, run_py, write

README = """# 設計書

## 索引

| # | パス | 何の正本か | いつ読むか | 更新トリガ |
|:--|:--|:--|:--|:--|
| 01 | `01-概要.md` | 目的 | 最初に | 目的が動いた |

## 変えたもの → 一緒に直す正本

| 変えたもの | 一緒に直す正本 | 備考 |
|:--|:--|:--|
| `docs/設計書/01-概要.md` | `docs/プロジェクト概要.html` | |

## 書き方

- 本文
"""
CATALOG = {"docs": {"05": {"file": "05-セキュリティ.md", "rows": {
    "## 索引": ["| 05 | `05-セキュリティ.md` | 守るもの | 権限を触るとき | 権限が動いた |"],
    "## 変えたもの → 一緒に直す正本": ["| `**/auth*` | `05-セキュリティ.md` §3 | |"],
    "## 無い見出し": ["| x | y |"],
}}}}
DOC = "# 05 セキュリティ\n\n> 最終更新: 2026-01-01（初版。雛形のまま）／ 対象: —\n> 作成: 2026-01-01 ／ 位置づけ: 守るもの\n\n## 改訂履歴\n"


def project(root) -> None:
    write(root / "docs/設計書/README.md", README)
    write(root / "docs/設計書/01-概要.md", "# 01\n")
    write(root / "docs/設計書/template/catalog.json", json.dumps(CATALOG, ensure_ascii=False))
    write(root / "docs/設計書/template/05-セキュリティ.md", DOC)


class AddDocTest(unittest.TestCase):
    def add(self, root, *args):
        return run_py(root / "scripts/add_doc.py", *args, cwd=root)

    def test_add_copies_and_indexes(self):
        with TempProject(copy=("scripts/add_doc.py",)) as root:
            project(root)
            r = self.add(root, "5")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            doc = (root / "docs/設計書/05-セキュリティ.md").read_text(encoding="utf-8")
            self.assertNotIn("2026-01-01", doc)                          # 日付は今日に
            self.assertIn("雛形のまま", doc)                              # 未記入の印は残す
            readme = (root / "docs/設計書/README.md").read_text(encoding="utf-8")
            idx = readme.index("## 索引")
            self.assertLess(idx, readme.index("| 05 | `05-セキュリティ.md`"))
            self.assertLess(readme.index("| 05 | `05-セキュリティ.md`"), readme.index("## 変えたもの"))
            self.assertLess(readme.index("| `**/auth*`"), readme.index("## 書き方"))
            self.assertNotIn("| x | y |", readme)                        # 見出しが無い表には足さない

    def test_twice_does_not_duplicate(self):
        with TempProject(copy=("scripts/add_doc.py",)) as root:
            project(root)
            self.add(root, "05")
            r = self.add(root, "05")
            self.assertEqual(r.returncode, 1)
            self.assertIn("既にある", r.stdout)
            readme = (root / "docs/設計書/README.md").read_text(encoding="utf-8")
            self.assertEqual(readme.count("| 05 | `05-セキュリティ.md`"), 1)

    def test_old_name_counts_as_existing(self):
        with TempProject(copy=("scripts/add_doc.py",)) as root:
            project(root)
            write(root / "docs/設計書/05-セキュリティ設計.md", "# 旧い名前\n")
            r = self.add(root, "05")
            self.assertEqual(r.returncode, 1)
            self.assertFalse((root / "docs/設計書/05-セキュリティ.md").exists())

    def test_other_extension_counts_as_existing(self):
        with TempProject(copy=("scripts/add_doc.py",)) as root:
            project(root)
            write(root / "docs/設計書/05-守るもの.html", "<p>既存</p>\n")
            self.assertEqual(self.add(root, "05").returncode, 1)
            self.assertIn("あり（05-守るもの.html）", self.add(root, "--list").stdout)

    def test_dry_run_and_list(self):
        with TempProject(copy=("scripts/add_doc.py",)) as root:
            project(root)
            r = self.add(root, "05", "--dry-run")
            self.assertEqual(r.returncode, 0)
            self.assertFalse((root / "docs/設計書/05-セキュリティ.md").exists())
            self.assertIn("なし", self.add(root, "--list").stdout)

    def test_unknown_number(self):
        with TempProject(copy=("scripts/add_doc.py",)) as root:
            project(root)
            self.assertEqual(self.add(root, "42").returncode, 1)


class GrowNudgeTest(unittest.TestCase):
    """設計書追随 hook: まだ足していない文書に関わる変更で「文書の候補」、Sketch で実装を始めたら「フェーズ」を知らせる。"""

    def hook(self, root, path: str, phase: str, sid: str = ""):
        import json
        import os
        import subprocess
        d = {"tool_name": "Write", "tool_input": {"file_path": path}}
        if sid:
            d["session_id"] = sid
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), CLAUDE_SKELETON_PHASE=phase, PYTHONDONTWRITEBYTECODE="1",
                   CLAUDE_DOCS_REMINDER_STATE_DIR=str(root / ".state"))
        return subprocess.run(["bash", str(root / ".claude/hooks/design_docs_reminder.sh")], input=json.dumps(d),
                              env=env, capture_output=True, text=True, encoding="utf-8", timeout=60).stdout

    def test_nudges(self):
        with TempProject(copy=(".claude/hooks", "docs/設計書", "scripts/add_doc.py")) as root:
            (root / ".state").mkdir()
            out = self.hook(root, "src/auth/login.py", "Sketch", "s1")
            self.assertIn("[文書の候補]", out)
            self.assertIn("05-セキュリティ.md", out)
            self.assertIn("06-品質と確認.md", out)
            self.assertIn("[フェーズ]", out)
            again = self.hook(root, "src/auth/logout.py", "Sketch", "s1")
            self.assertEqual(again.strip(), "")                                      # 同じセッションでは 1 回だけ
            self.assertNotIn("[フェーズ]", self.hook(root, "src/auth/login.py", "Build", "s2"))
            self.assertNotIn("[フェーズ]", self.hook(root, "docs/設計書/01-概要.md", "Sketch", "s3"))
            run_py(root / "scripts/add_doc.py", "05", cwd=root)
            out = self.hook(root, "src/auth/login.py", "Build", "s4")
            self.assertNotIn("05-セキュリティ.md に関わる。要るなら", out)            # 足したら候補ではなく追随
            self.assertIn("[設計書追随]", out)
            self.assertIn("06-品質と確認.md", out)                                   # 06 はまだ候補


class CatalogConsistencyTest(unittest.TestCase):
    """テンプレの catalog.json・template/ の文書・README の見出しが噛み合っている。"""

    def test_catalog_matches_template(self):
        catalog = json.loads((ROOT / "docs/設計書/template/catalog.json").read_text(encoding="utf-8"))["docs"]
        readme = (ROOT / "docs/設計書/README.md").read_text(encoding="utf-8")
        self.assertEqual(sorted(catalog), [f"{n:02d}" for n in range(2, 10)])
        for no, entry in catalog.items():
            self.assertTrue(entry["file"].startswith(no + "-"), entry["file"])
            self.assertTrue((ROOT / "docs/設計書/template" / entry["file"]).is_file(), entry["file"])
            for heading, rows in entry["rows"].items():
                self.assertIn("\n" + heading + "\n", readme, heading)
                for row in rows:
                    self.assertTrue(row.startswith("| ") and row.endswith(" |"), row)
                    # 自分以外の番号付き文書をバッククォートで指さない（まだ無い文書を指さないため）
                    for ref in re.findall(r"`(\d{2})-[^`]+\.md`", row):
                        self.assertEqual(ref, no, row)

    def test_all_added_resolves(self):
        """まだ足していない文書を全部足すと、check_skeleton の設計書検査が通る（使っている案件でも通る）。"""
        import sys
        with TempProject(copy=("scripts", ".claude/hooks", "docs/設計書", "docs/プロジェクト概要.html", "CLAUDE.md")) as root:
            missing = [f"{n:02d}" for n in range(2, 10) if not list((root / "docs/設計書").glob(f"{n:02d}-*.md"))]
            if missing:
                r = run_py(root / "scripts/add_doc.py", *missing, cwd=root)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            sys.path.insert(0, str(root / "scripts"))
            fails: list[str] = []
            import importlib
            import check_skeleton as cs
            importlib.reload(cs)
            cs.check_design_docs(root, template=True, secrets=False,
                                 report=lambda c, m: c or fails.append(m) or c)
            self.assertEqual(fails, [])


if __name__ == "__main__":
    unittest.main()
