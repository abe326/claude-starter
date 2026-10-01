"""scripts/work_log.py（作業ログを正本から生成する）のテスト。"""
from __future__ import annotations

import unittest

from _util import TempProject, run_py, write

TM = "docs/案件/01_タスク管理"
LOG = "docs/案件/作業ログ"


def item(iid: str, title: str, kind: str, created: str, closed: str = "", decision: str = "") -> str:
    body = f"\n## 決定\n{decision}\n→ 反映済: 01 §3\n" if decision else "\n## 概要\n本文は作業ログに写さない\n"
    return (f"---\nid: {iid}\ntitle: {title}\narea: 横断\nkind: {kind}\nstatus: {'完了' if closed else '未着手'}\n"
            f"created: {created}\nupdated: {created}\nclosed: {closed}\n---\n{body}")


def project(root) -> None:
    write(root / f"{TM}/open/APP-02_一覧.md", item("APP-02", "一覧画面", "タスク", "2026-09-20"))
    write(root / f"{TM}/closed/APP-01_ログイン.md", item("APP-01", "ログイン", "タスク", "2026-08-30", "2026-09-22"))
    write(root / f"{TM}/closed/QA-01_範囲.md",
          item("QA-01", "対象範囲をどこまでにするか", "課題", "2026-09-01", "2026-09-23", "本社の正社員のみ"))
    write(root / "docs/案件/02_打合せ/20260923_定例.md", "# 定例\n")
    write(root / "docs/案件/02_打合せ/README.md", "# 置き場\n")


class WorkLogTest(unittest.TestCase):
    def run_log(self, root, *args):
        return run_py(root / "scripts/work_log.py", *args, cwd=root, env={"CLAUDE_SKELETON_TODAY": "2026-09-24"})

    def test_files_and_window(self):
        with TempProject(copy=("scripts/work_log.py", ".claude/hooks")) as root:
            project(root)
            r = self.run_log(root)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            latest = (root / f"{LOG}/最新.md").read_text(encoding="utf-8")
            # 直近 14 日（09-11〜09-24）に入るのは 4 件。08-30 の起票と 09-01 の起票は入らない
            self.assertIn("## 2026-09-23", latest)
            self.assertIn("- 決定 [QA-01](../01_タスク管理/closed/QA-01_範囲.md) 対象範囲をどこまでにするか → 本社の正社員のみ", latest)
            self.assertIn("- 完了 [APP-01]", latest)
            self.assertIn("- 起票 [APP-02]", latest)
            self.assertIn("- 打合せ [定例](../02_打合せ/20260923_定例.md)", latest)
            self.assertNotIn("2026-08-30", latest)
            self.assertNotIn("本文は作業ログに写さない", latest)
            self.assertLess(latest.index("## 2026-09-23"), latest.index("## 2026-09-22"))   # 新しい順
            self.assertLess(latest.index("- 決定"), latest.index("- 打合せ"))                  # 同じ日は決定が先
            self.assertTrue((root / f"{LOG}/2026-08.md").is_file())
            index = (root / f"{LOG}/README.md").read_text(encoding="utf-8")
            self.assertIn("| [2026-09](2026-09.md) | 5 | QA-01 対象範囲をどこまでにするか |", index)
            self.assertIn("| [2026-08](2026-08.md) | 1 | — |", index)

    def test_same_day_is_one_line(self):
        """起票した日に閉じたもの（その場で決めた課題）は「決定」の 1 行だけにする。"""
        with TempProject(copy=("scripts/work_log.py", ".claude/hooks")) as root:
            write(root / f"{TM}/closed/QA-05_締め.md",
                  item("QA-05", "締めをいつにするか", "課題", "2026-09-24", "2026-09-24", "月末"))
            self.run_log(root)
            latest = (root / f"{LOG}/最新.md").read_text(encoding="utf-8")
            self.assertIn("- 決定 [QA-05]", latest)
            self.assertNotIn("- 起票 [QA-05]", latest)

    def test_quiet_prints_count(self):
        with TempProject(copy=("scripts/work_log.py", ".claude/hooks")) as root:
            project(root)
            r = self.run_log(root, "--quiet")
            self.assertEqual(r.stdout.strip(), "4")

    def test_no_rewrite_when_same(self):
        with TempProject(copy=("scripts/work_log.py", ".claude/hooks")) as root:
            project(root)
            self.run_log(root)
            path = root / f"{LOG}/2026-08.md"
            before = path.stat().st_mtime_ns
            self.run_log(root)
            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_empty_project(self):
        with TempProject(copy=("scripts/work_log.py", ".claude/hooks")) as root:
            r = self.run_log(root, "--quiet")
            self.assertEqual(r.stdout.strip(), "0")
            self.assertIn("出来事はありません", (root / f"{LOG}/最新.md").read_text(encoding="utf-8"))


class DecisionSourceTest(unittest.TestCase):
    """決定の正本は課題。落ち先が課題の ID の決定行は、直近の決定で二重に数えない。旧い形の行は数える。"""

    def test_no_double_count(self):
        import drops
        with TempProject() as root:
            project(root)
            write(root / "docs/案件/02_打合せ/20260924_定例.md",
                  "# 定例\n\n## 決定\n- 対象は本社の正社員のみ → QA-01\n- 締めは月末 → 反映済: 01 §3\n\n## 未決\n\n## 宿題\n")
            texts = [d["text"] for d in drops.recent_decisions(str(root), 10)]
            self.assertIn("本社の正社員のみ", texts)                 # 課題の側から 1 件
            self.assertNotIn("対象は本社の正社員のみ", texts)          # 打合せの行は数えない
            self.assertIn("締めは月末", texts)                        # 旧い形はそのまま数える


if __name__ == "__main__":
    unittest.main()
