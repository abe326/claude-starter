"""docs/案件/01_タスク管理/new.py（argparse・起票・--decided）のテスト。付録 B §5.2 と付録 A §1.4。"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from _util import TempProject, run_py, write

TM = "docs/案件/01_タスク管理"
NEW = f"{TM}/new.py"
# 起票に要る実物（drops.py は --to の確認、設計書は「反映済: 01 §3」の実在、概要 HTML は直近の決定）
COPY = (f"{TM}/new.py", f"{TM}/close.py", f"{TM}/build.py", f"{TM}/areas.json",
        ".claude/hooks/drops.py", ".claude/hooks/phase.py", "docs/設計書/01-概要.md",
        "docs/プロジェクト概要.html")


def md_files(root: Path, state: str = "open") -> list[str]:
    d = root / TM / state
    return sorted(p.name for p in d.glob("*.md")) if d.is_dir() else []


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    body = text.split("---", 2)[1]
    out = {}
    for line in body.strip().splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


class NewPy(unittest.TestCase):
    def run_new(self, root: Path, *args: str):
        return run_py(root / NEW, *args, cwd=root)

    # --- 何も作らない -----------------------------------------------------------
    def test_help_creates_nothing(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "-h")
            self.assertEqual(r.returncode, 0)
            self.assertIn("登録済みの領域", r.stdout)
            self.assertIn("横断=QA", r.stdout)
            self.assertEqual(md_files(root), [])

    def test_unknown_area_exit2(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "謎の領域", "何か")
            self.assertEqual(r.returncode, 2)
            self.assertIn("未登録", r.stderr)
            self.assertIn("--add-area", r.stderr)
            self.assertEqual(md_files(root), [])

    def test_title_required(self):
        with TempProject(COPY) as root:
            self.assertEqual(self.run_new(root, "横断").returncode, 2)
            self.assertEqual(self.run_new(root, "横断", "  ").returncode, 2)
            self.assertEqual(md_files(root), [])

    def test_bad_due_exit2(self):
        with TempProject(COPY) as root:
            for bad in ("2026-13-01", "10/7", "2026-02-30", "来週"):
                r = self.run_new(root, "横断", "x", "--due", bad)
                self.assertEqual(r.returncode, 2, bad)
            self.assertEqual(md_files(root), [])

    def test_decided_needs_to(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "横断", "対象範囲", "--decided", "本社のみ")
            self.assertEqual(r.returncode, 2)
            self.assertIn("--to", r.stderr)
            r = self.run_new(root, "横断", "対象範囲", "--to", "反映済: 01 §3")
            self.assertEqual(r.returncode, 2)
            r = self.run_new(root, "横断", "対象範囲", "--kind", "タスク", "--decided", "本社のみ", "--to", "反映済: 01 §3")
            self.assertEqual(r.returncode, 2)
            self.assertEqual(md_files(root) + md_files(root, "closed"), [])

    def test_decided_with_missing_id_creates_nothing(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "横断", "対象範囲", "--decided", "本社のみ", "--to", "APP-09")
            self.assertEqual(r.returncode, 2)
            self.assertIn("ID 不在", r.stderr)
            self.assertEqual(md_files(root) + md_files(root, "closed"), [])

    # --- 起票 -------------------------------------------------------------------
    def test_first_line_is_id(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "横断", "ログインの検証")
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = r.stdout.splitlines()
            self.assertEqual(lines[0], "QA-01")
            self.assertTrue(lines[1].startswith("作成: open/QA-01_ログインの検証.md"), lines[1])
            r = self.run_new(root, "横断", "二つ目")
            self.assertEqual(r.stdout.splitlines()[0], "QA-02")

    def test_numbering_sees_closed(self):
        with TempProject(COPY) as root:
            write(root / TM / "closed/QA-07_済.md", "---\nid: QA-07\ntitle: 済\narea: 横断\nstatus: 完了\npriority: 中\n---\n")
            r = self.run_new(root, "横断", "次")
            self.assertEqual(r.stdout.splitlines()[0], "QA-08")

    def test_prefix_is_read_as_area(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "qa", "小文字の接頭辞")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.splitlines()[0], "QA-01")
            self.assertIn("横断 として扱います", r.stderr)
            self.assertEqual(frontmatter(root / TM / "open/QA-01_小文字の接頭辞.md")["area"], "横断")

    def test_spec_area_registered(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "仕様", "画面遷移")
            self.assertEqual(r.stdout.splitlines()[0], "SPEC-01")

    def test_options_to_frontmatter(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "横断", "期限つき", "--priority", "高", "--owner", "担当A", "--due", "2026-10-07",
                             "--tag", "0527", "--tag", "移行")
            self.assertEqual(r.returncode, 0, r.stderr)
            fm = frontmatter(root / TM / "open/QA-01_期限つき.md")
            self.assertEqual((fm["priority"], fm["owner"], fm["due"], fm["tags"], fm["kind"]),
                             ("高", "担当A", "2026-10-07", "[0527, 移行]", "タスク"))
            self.assertNotIn("decider", fm)          # decider は課題だけ

    def test_issue_template_seven_sections(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "運用", "何世代残すか", "--kind", "課題", "--decider", "SH-02", "--due", "2026-10-07")
            self.assertEqual(r.returncode, 0, r.stderr)
            path = root / TM / "open/OPS-01_何世代残すか.md"
            fm = frontmatter(path)
            self.assertEqual((fm["kind"], fm["decider"], fm["due"]), ("課題", "SH-02", "2026-10-07"))
            heads = re.findall(r"^## (.+)$", path.read_text(encoding="utf-8"), re.M)
            self.assertEqual(heads, ["概要", "論点", "選択肢", "決着条件", "決定", "過去の経緯", "参照情報"])
            # 雛形のままでは閉じられない（決定の案内は HTML コメント）
            c = run_py(root / TM / "close.py", "OPS-01", cwd=root)
            self.assertEqual(c.returncode, 1)
            self.assertTrue(path.is_file())

    def test_task_conditions_warn_but_close(self):
        """タスクの完了条件に [ ] が残っていれば警告して閉じる。全部 [x] なら警告しない。"""
        with TempProject(COPY) as root:
            r = self.run_new(root, "運用", "バックアップを設定する")
            self.assertEqual(r.returncode, 0, r.stderr)
            path = root / TM / "open/OPS-01_バックアップを設定する.md"
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("- [ ] "), 3)
            c = run_py(root / TM / "close.py", "OPS-01", cwd=root)
            self.assertEqual(c.returncode, 0, c.stderr)
            self.assertIn("完了条件にチェックの無いもの", c.stderr)
            self.assertIn("- [ ] 対象環境へ適用済み", c.stderr)
            self.assertTrue((root / TM / "closed/OPS-01_バックアップを設定する.md").is_file())

            r = self.run_new(root, "運用", "手順書を直す")
            path = root / TM / "open/OPS-02_手順書を直す.md"
            path.write_text(path.read_text(encoding="utf-8").replace("- [ ] ", "- [x] "), encoding="utf-8")
            c = run_py(root / TM / "close.py", "OPS-02", cwd=root)
            self.assertEqual(c.returncode, 0, c.stderr)
            self.assertNotIn("完了条件にチェックの無いもの", c.stderr)

    def test_old_numbered_conditions_not_warned(self):
        """番号付きの旧い完了条件（v1.4 以前に起票したタスク）は見ない。"""
        with TempProject(COPY) as root:
            write(root / TM / "open/OPS-01_旧.md",
                  "---\nid: OPS-01\ntitle: 旧\narea: 運用\nstatus: 進行中\npriority: 中\n---\n\n"
                  "## 完了条件（クローズ3条件）\n1. 対象環境へ適用済み\n2. 確認\n\n## 過去の経緯\n")
            c = run_py(root / TM / "close.py", "OPS-01", cwd=root)
            self.assertEqual(c.returncode, 0, c.stderr)
            self.assertNotIn("完了条件にチェックの無いもの", c.stderr)

    def test_decider_implies_issue(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "横断", "誰が決めるか", "--decider", "SH-01")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(frontmatter(root / TM / "open/QA-01_誰が決めるか.md")["kind"], "課題")
            r = self.run_new(root, "横断", "x", "--kind", "タスク", "--decider", "SH-01")
            self.assertEqual(r.returncode, 2)

    def test_add_area(self):
        # 生成時の --areas で領域が足されていても通るよう、実在しない領域名を使う
        with TempProject(COPY) as root:
            r = self.run_new(root, "検証用", "画面を作る", "--add-area", "検証用:VRFY")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.splitlines()[0], "VRFY-01")
            areas = json.loads((root / TM / "areas.json").read_text(encoding="utf-8"))["areas"]
            self.assertEqual(areas["検証用"], "VRFY")
            before = (root / TM / "areas.json").read_bytes()
            for spec in ("別名:VRFY", "検証用:VRX", "ロール:SH", "変:app1"):   # 重複・既存名・予約・書式
                r = self.run_new(root, "横断", "x", "--add-area", spec)
                self.assertEqual(r.returncode, 2, spec)
            self.assertEqual((root / TM / "areas.json").read_bytes(), before)
            self.assertEqual(md_files(root), ["VRFY-01_画面を作る.md"])

    def test_decided_closes_immediately(self):
        with TempProject(COPY) as root:
            r = self.run_new(root, "横断", "対象範囲", "--decided", "本社のみ", "--to", "反映済: 01 §3", "--to", "取り下げ: 例")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.splitlines()[0], "QA-01")
            self.assertEqual(md_files(root), [])
            path = root / TM / "closed/QA-01_対象範囲.md"
            text = path.read_text(encoding="utf-8")
            self.assertIn("## 決定\n本社のみ\n→ 反映済: 01 §3\n→ 取り下げ: 例\n", text)
            self.assertEqual(frontmatter(path)["status"], "完了")
            html = (root / "docs/プロジェクト概要.html").read_text(encoding="utf-8")
            seg = html.split("BEGIN:recent-decisions", 1)[1].split("END:recent-decisions", 1)[0]
            self.assertIn("<span>本社のみ</span><span class=\"ref\">QA-01</span>", seg)


if __name__ == "__main__":
    unittest.main()
