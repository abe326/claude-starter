"""秘密検出（check_skeleton.secret_hits・check_secrets）のテスト。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from _util import ROOT, TempProject, write

sys.path.insert(0, str(ROOT / "scripts"))
import check_skeleton  # noqa: E402

CASES = Path(__file__).with_name("secret-cases.txt")


def load_cases() -> list[tuple[str, str]]:
    out = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        expect, text = line.split("\t", 1)
        out.append((expect, text))
    return out


class Recorder:
    def __init__(self):
        self.fails: list[str] = []
        self.passes = 0

    def __call__(self, cond: bool, msg: str) -> bool:
        if cond:
            self.passes += 1
        else:
            self.fails.append(msg)
        return cond


class SecretHits(unittest.TestCase):
    def test_case_table(self):
        cases = load_cases()
        self.assertGreaterEqual(len(cases), 36)
        wrong = [(e, t) for e, t in cases if check_skeleton.secret_hits(t) != (e == "hit")]
        self.assertEqual(wrong, [])

    def test_template_placeholder_is_not_secret(self):
        # 波括弧 2 つのテンプレート変数。ファイルに直に書くとスケルトンのプレースホルダ検査
        # （init.py・check.py）に掛かるので、ここで組み立てる
        o, c = "{" * 2, "}" * 2
        for text in (f"token: {o} API_TOKEN {c}", f"token: {o}API_TOKEN{c}", f"password: {o} db_password {c}"):
            self.assertFalse(check_skeleton.secret_hits(text), text)

    def test_both_kinds_present(self):
        kinds = {e for e, _ in load_cases()}
        self.assertEqual(kinds, {"hit", "miss"})


class CheckSecrets(unittest.TestCase):
    def test_project_itself_is_clean(self):
        rec = Recorder()
        check_skeleton.check_secrets(ROOT, report=rec)
        self.assertEqual(rec.fails, [])
        self.assertGreater(rec.passes, 10)

    def test_meeting_note_hit_reports_line_only(self):
        with TempProject() as root:
            write(root / "docs/案件/02_打合せ/20260923_キックオフ.md",
                  "# キックオフ\n\n- 接続先は postgres://app:s3cretpass@db.example.com/kintai\n")
            rec = Recorder()
            check_skeleton.check_secrets(root, report=rec)
            self.assertEqual(len(rec.fails), 1)
            self.assertIn("docs/案件/02_打合せ/20260923_キックオフ.md", rec.fails[0])
            self.assertIn("行 3", rec.fails[0])
            self.assertNotIn("s3cretpass", rec.fails[0])

    def test_opt_out(self):
        with TempProject() as root:
            write(root / "docs/案件/02_打合せ/a.md",
                  "- postgres://app:s3cretpass@db.example.com/kintai <!-- secret-scan: ok 検査の例 -->\n")
            rec = Recorder()
            self.assertEqual(check_skeleton.check_secrets(root, report=rec), 1)
            self.assertEqual(rec.fails, [])

    def test_scope(self):
        with TempProject() as root:
            bad = "password=Kintai2027!\n"
            for rel in ("CLAUDE.md", "docs/ハーネス台帳.md", ".claude/rules/x.md", "docs/案件/確認依頼一覧.md",
                        "docs/案件/01_タスク管理/open/APP-01_x.md"):
                write(root / rel, bad)
            for rel in ("環境情報.md", "案件情報.md", ".work/一時/20260923_x/a.md", "docs/案件/01_タスク管理/data.js",
                        "src/app.md"):
                write(root / rel, bad)
            rec = Recorder()
            check_skeleton.check_secrets(root, report=rec)
            self.assertEqual(len(rec.fails), 5, rec.fails)
            files = {f.split(":", 1)[0] for f in rec.fails}
            self.assertEqual(files, {"CLAUDE.md", "docs/ハーネス台帳.md", ".claude/rules/x.md",
                                     "docs/案件/確認依頼一覧.md", "docs/案件/01_タスク管理/open/APP-01_x.md"})

    def test_design_only(self):
        with TempProject() as root:
            write(root / "docs/案件/02_打合せ/a.md", "password=Kintai2027!\n")
            write(root / "docs/設計書/05-セキュリティ.md", "token：abc123XYZ789\n")
            rec = Recorder()
            check_skeleton.check_secrets(root, report=rec, design_only=True)
            self.assertEqual(len(rec.fails), 1)
            self.assertIn("05-セキュリティ.md", rec.fails[0])


if __name__ == "__main__":
    unittest.main()
