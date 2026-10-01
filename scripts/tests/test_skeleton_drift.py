"""スケルトンとのずれ（.claude/hooks/skeleton_drift.py）と、それを出す SessionStart・check_skeleton のテスト。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from _util import ROOT, TempProject, run_py, write

sys.path.insert(0, str(ROOT / "scripts"))

DRIFT = ROOT / ".claude/hooks/skeleton_drift.py"


def record(root: Path, version: str, files: dict[str, str] | None = None) -> None:
    """files: {rel: 記録する中身}。sha は中身から作る。"""
    entries = {rel: {"sha": hashlib.sha256(body.encode("utf-8")).hexdigest(), "commit": None}
               for rel, body in (files or {}).items()}
    write(root / ".claude/skeleton.json", json.dumps({"version": version, "files": entries}, ensure_ascii=False))


def skeleton(tmp: Path, version: str) -> Path:
    d = tmp / "skeleton"
    write(d / "VERSION", version + "\n")
    return d


def drift(root: Path, skel: Path | None, *args: str) -> str:
    env = {"CLAUDE_PROJECT_DIR": str(root), "PROJECT_SKELETON_DIR": str(skel) if skel else str(root / "none")}
    return run_py(DRIFT, *args, cwd=root, env=env).stdout.strip()


class SkeletonDriftTest(unittest.TestCase):
    def test_behind_from_record(self):
        with TempProject() as root:
            record(root, "1.4.1")
            out = drift(root, skeleton(root, "1.5.0"))
            self.assertIn("スケルトン: v1.4.1 → v1.5.0", out)
            self.assertIn("new-project スキル", out)

    def test_same_or_newer_is_silent(self):
        with TempProject() as root:
            record(root, "1.5.0")
            self.assertEqual(drift(root, skeleton(root, "1.5.0")), "")
            record(root, "1.6.0")
            self.assertEqual(drift(root, skeleton(root, "1.5.0")), "")

    def test_stamp_when_no_record(self):
        with TempProject() as root:
            write(root / "CLAUDE.md", "<!-- project-skeleton v1.3.0 generated 2026-09-24 -->\n# x\n")
            self.assertIn("v1.3.0 → v1.5.0", drift(root, skeleton(root, "1.5.0")))

    def test_no_skeleton_or_version_is_silent(self):
        with TempProject() as root:
            record(root, "1.4.1")
            self.assertEqual(drift(root, None), "")
            write(root / "CLAUDE.md", "# 刻印なし\n")
            (root / ".claude/skeleton.json").write_text("{ broken", encoding="utf-8")
            self.assertEqual(drift(root, skeleton(root, "1.5.0")), "")

    def test_local_mechanisms(self):
        with TempProject() as root:
            write(root / ".claude/hooks/a.py", "print(1)\n")
            write(root / "scripts/b.py", "changed\n")
            write(root / "docs/c.md", "changed\n")               # 内容は数えない
            record(root, "1.4.1", {".claude/hooks/a.py": "print(1)\n", "scripts/b.py": "orig\n",
                                   "docs/c.md": "orig\n", "scripts/gone.py": "x\n"})
            st = json.loads(drift(root, skeleton(root, "1.5.0"), "--json"))
            self.assertEqual(st["local_mechanisms"], ["scripts/b.py"])
            self.assertTrue(st["behind"])
            self.assertIn("案件で直した仕組み 1 件", drift(root, skeleton(root, "1.5.0")))


@unittest.skipUnless(shutil.which("bash"), "bash が無い")
class SessionContextTest(unittest.TestCase):
    def test_line_in_session_context(self):
        with TempProject(copy=(".claude/hooks",)) as root:
            record(root, "1.4.1")
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PROJECT_SKELETON_DIR=str(skeleton(root, "9.9.9")),
                       PYTHONDONTWRITEBYTECODE="1")
            r = subprocess.run(["bash", str(root / ".claude/hooks/session_context.sh")], env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertIn("スケルトン: v1.4.1 → v9.9.9", r.stdout)
            self.assertLessEqual(len(r.stdout.strip().splitlines()), 8)


class CheckSkeletonRecordTest(unittest.TestCase):
    def test_broken_record_is_ng_and_behind_is_warn(self):
        import check_skeleton as cs
        fails: list[str] = []

        def rec(cond, msg):
            if not cond:
                fails.append(msg)
            return cond

        with TempProject() as root:
            write(root / ".claude/skeleton.json", "{ broken")
            cs.check_skeleton_record(root, report=rec)
            self.assertTrue(any("skeleton.json を読めない" in f for f in fails))
            fails.clear()
            record(root, "1.4.1")
            os.environ["PROJECT_SKELETON_DIR"] = str(skeleton(root, "1.5.0"))
            try:
                before = cs.WARN
                cs.check_skeleton_record(root, report=rec)
                self.assertEqual(fails, [])
                self.assertEqual(cs.WARN, before + 1)
            finally:
                os.environ.pop("PROJECT_SKELETON_DIR", None)


if __name__ == "__main__":
    unittest.main()
