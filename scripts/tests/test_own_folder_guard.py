"""home/hooks/own_folder_guard.py の単体テスト。一時フォルダの中に HOME・プロジェクト・置き場を作って動かす。"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "home", "hooks"))
import own_folder_guard as guard  # noqa: E402

ENV_KEYS = ("CC_OWN_FOLDER_GUARD", "CC_OFFICE_DIR", "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR")


class GuardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
        self.home = self.mk("home")
        self.claude = self.mk("home", ".claude")
        self.own = self.mk("projects", "own")
        self.other = self.mk("projects", "other")
        self.office = self.mk("office")
        self.systmp = self.mk("systmp")
        saved = {k: os.environ.pop(k) for k in ENV_KEYS if k in os.environ}
        self.addCleanup(os.environ.update, saved)
        env = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        env.start()
        self.addCleanup(env.stop)
        # テスト用のフォルダ自体が一時フォルダの中にあるので、通す一時フォルダは別の場所に向ける
        gettemp = mock.patch.object(guard.tempfile, "gettempdir", lambda: self.systmp)
        gettemp.start()
        self.addCleanup(gettemp.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def mk(self, *parts) -> str:
        p = os.path.join(self.tmp, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def on(self, **extra):
        os.environ.update({"CC_OWN_FOLDER_GUARD": "1", "CLAUDE_PROJECT_DIR": self.own, **extra})

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def allow(self, *lines):
        self.write(os.path.join(self.claude, "own-folder-allow.txt"), "\n".join(lines) + "\n")

    def denied(self, path, cwd=None) -> bool:
        return guard.judge(path, cwd) is not None


class Enable(GuardCase):
    def test_off_by_default(self):
        os.environ["CLAUDE_PROJECT_DIR"] = self.own
        self.assertFalse(self.denied(os.path.join(self.other, "a.md")))

    def test_flag_in_env(self):
        self.on()
        self.assertTrue(self.denied(os.path.join(self.other, "a.md")))

    def test_flag_zero_is_off(self):
        self.on(CC_OWN_FOLDER_GUARD="0")
        self.assertFalse(self.denied(os.path.join(self.other, "a.md")))

    def test_flag_in_project_settings_local(self):
        os.environ["CLAUDE_PROJECT_DIR"] = self.own
        self.write(os.path.join(self.own, ".claude", "settings.local.json"),
                   json.dumps({"env": {"CC_OWN_FOLDER_GUARD": "1"}}))
        self.assertTrue(self.denied(os.path.join(self.other, "a.md")))

    def test_flag_in_project_settings(self):
        os.environ["CLAUDE_PROJECT_DIR"] = self.own
        self.write(os.path.join(self.own, ".claude", "settings.json"),
                   json.dumps({"env": {"CC_OWN_FOLDER_GUARD": "true"}}))
        self.assertTrue(self.denied(os.path.join(self.other, "a.md")))

    def test_flag_of_other_project_does_not_apply(self):
        os.environ["CLAUDE_PROJECT_DIR"] = self.own
        self.write(os.path.join(self.other, ".claude", "settings.local.json"),
                   json.dumps({"env": {"CC_OWN_FOLDER_GUARD": "1"}}))
        self.assertFalse(self.denied(os.path.join(self.other, "a.md")))

    def test_broken_settings_is_off(self):
        os.environ["CLAUDE_PROJECT_DIR"] = self.own
        self.write(os.path.join(self.own, ".claude", "settings.local.json"), "{broken")
        self.assertFalse(self.denied(os.path.join(self.other, "a.md")))


class Judge(GuardCase):
    def test_own_project(self):
        self.on()
        self.assertFalse(self.denied(os.path.join(self.own, "docs", "new.md")))

    def test_relative_path_resolves_from_cwd(self):
        self.on()
        self.assertFalse(self.denied("docs/a.md", cwd=self.own))
        self.assertTrue(self.denied("../other/a.md", cwd=self.own))

    def test_project_dir_falls_back_to_cwd(self):
        os.environ["CC_OWN_FOLDER_GUARD"] = "1"
        self.assertFalse(self.denied(os.path.join(self.own, "a.md"), cwd=self.own))
        self.assertTrue(self.denied(os.path.join(self.other, "a.md"), cwd=self.own))

    def test_dotdot_escape(self):
        self.on()
        self.assertTrue(self.denied(os.path.join(self.own, "..", "other", "a.md")))

    def test_prefix_sibling_is_not_inside(self):
        self.on()
        sibling = self.mk("projects", "own-2")
        self.assertTrue(self.denied(os.path.join(sibling, "a.md")))

    def test_symlink_to_other_project(self):
        self.on()
        link = os.path.join(self.own, "link")
        try:
            os.symlink(self.other, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink を作れない環境")
        self.assertTrue(self.denied(os.path.join(link, "a.md")))

    def test_claude_dir_and_tmp(self):
        self.on()
        self.assertFalse(self.denied(os.path.join(self.claude, "skills", "x", "SKILL.md")))
        self.assertFalse(self.denied("~/.claude/CLAUDE.personal.md"))
        self.assertFalse(self.denied(os.path.join(self.systmp, "scratchpad", "a.txt")))
        self.assertTrue(self.denied(os.path.join(self.home, "notes.md")))

    def test_office_dir_from_env(self):
        self.on(CC_OFFICE_DIR=self.office)
        self.assertFalse(self.denied(os.path.join(self.office, "回覧台帳.md")))

    def test_office_dir_from_user_settings(self):
        self.on()
        self.write(os.path.join(self.claude, "settings.json"), json.dumps({"env": {"CC_OFFICE_DIR": self.office}}))
        self.assertFalse(self.denied(os.path.join(self.office, "依頼", "x.md")))

    def test_no_office_dir(self):
        self.on()
        self.assertTrue(self.denied(os.path.join(self.office, "回覧台帳.md")))

    def test_empty_path(self):
        self.on()
        self.assertIsNone(guard.judge(None))
        self.assertIsNone(guard.judge(""))


class AllowFile(GuardCase):
    def test_folder_and_file_entries(self):
        self.on()
        rules = os.path.join(self.other, "docs", "決まりの台帳.md")
        shared = self.mk("shared")
        self.allow("# 全員が書く台帳", rules, shared)
        self.assertFalse(self.denied(rules))
        self.assertFalse(self.denied(os.path.join(shared, "x", "y.md")))
        self.assertTrue(self.denied(os.path.join(self.other, "docs", "ほか.md")))

    def test_tilde_and_var_entries(self):
        self.on(SHARED_DIR=self.mk("shared"))
        self.mk("home", "bin")
        self.allow("~/bin", "$SHARED_DIR")
        self.assertFalse(self.denied(os.path.join(self.home, "bin", "tool")))
        self.assertFalse(self.denied(os.path.join(self.tmp, "shared", "a.md")))

    def test_unexpanded_var_does_not_open(self):
        self.on()
        self.allow("$NO_SUCH_VAR/x")
        self.assertTrue(self.denied(os.path.join(self.other, "a.md")))

    def test_glob_entry(self):
        self.on()
        self.allow(os.path.join(self.tmp, "projects", "*", "docs", "台帳.md"))
        self.assertFalse(self.denied(os.path.join(self.other, "docs", "台帳.md")))
        self.assertTrue(self.denied(os.path.join(self.other, "docs", "ほか.md")))

    def test_blank_and_comment_lines(self):
        self.on()
        self.allow("", "   ", "# " + self.other)
        self.assertTrue(self.denied(os.path.join(self.other, "a.md")))


class Main(GuardCase):
    def run_main(self, payload) -> tuple[int, str]:
        err = io.StringIO()
        stdin = io.StringIO(payload if isinstance(payload, str) else json.dumps(payload))
        with mock.patch.object(sys, "stdin", stdin), redirect_stderr(err):
            code = guard.main()
        return code, err.getvalue()

    def test_deny_exit_2_with_reason(self):
        self.on()
        code, err = self.run_main({"tool_name": "Write", "cwd": self.own,
                                   "tool_input": {"file_path": os.path.join(self.other, "a.md")}})
        self.assertEqual(code, 2)
        self.assertIn("peer-request", err)

    def test_notebook_path(self):
        self.on()
        code, _ = self.run_main({"tool_name": "NotebookEdit", "cwd": self.own,
                                 "tool_input": {"notebook_path": os.path.join(self.other, "a.ipynb")}})
        self.assertEqual(code, 2)

    def test_allow_exit_0(self):
        self.on()
        code, err = self.run_main({"tool_name": "Edit", "cwd": self.own,
                                   "tool_input": {"file_path": os.path.join(self.own, "a.md")}})
        self.assertEqual((code, err), (0, ""))

    def test_broken_input_does_not_block(self):
        self.on()
        self.assertEqual(self.run_main("not json")[0], 0)
        self.assertEqual(self.run_main({"tool_input": None})[0], 0)


if __name__ == "__main__":
    unittest.main()
