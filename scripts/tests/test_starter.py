"""scripts/starter.py と scripts/check_public.py の単体テスト。一時的な HOME の中だけで動かす。"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import check_public  # noqa: E402
import starter  # noqa: E402

_ORIG_PATHS = starter.paths


class HomeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="starter-test-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".claude"))
        self.env = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        self.env.start()
        self.npm = mock.patch.object(starter, "ensure_npm", lambda log, dry: None)
        self.npm.start()
        self.cand = os.path.join(self.tmp, "candidates.jsonl")
        self.cand_patch = mock.patch.object(starter, "paths", self._paths)
        self.cand_patch.start()

    def _paths(self):
        p = dict(_ORIG_PATHS())
        p["candidates"] = self.cand  # リポの実物の候補台帳に触らない
        return p

    def tearDown(self):
        self.cand_patch.stop()
        self.npm.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def c(self, *parts):
        return os.path.join(self.home, ".claude", *parts)

    def run_cmd(self, *argv) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            starter.main(list(argv))
        return buf.getvalue()

    def write_json(self, path, obj):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def read_json(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)


class TestMerge(unittest.TestCase):
    def test_deep_merge_lists_union_and_scalar_override(self):
        base = {"a": [1, 2], "b": {"x": 1, "y": 2}, "c": "base"}
        over = {"a": [2, 3], "b": {"y": 9}, "c": "over"}
        self.assertEqual(starter.deep_merge(base, over), {"a": [1, 2, 3], "b": {"x": 1, "y": 9}, "c": "over"})

    def test_delta_takes_only_additions_and_changes(self):
        old = {"a": [1, 2], "b": {"x": 1}, "c": 1}
        new = {"a": [1, 3], "b": {"x": 2}, "d": True}
        delta, removed = starter.settings_delta(old, new)
        self.assertEqual(delta, {"a": [3], "b": {"x": 2}, "d": True})
        self.assertEqual(removed, 2)  # a の 2 と c

    def test_delta_none_when_same(self):
        self.assertEqual(starter.settings_delta({"a": [1]}, {"a": [1]}), (None, 0))


class TestInstall(HomeCase):
    def test_fresh_install_links_and_stub(self):
        self.run_cmd("install")
        self.assertTrue(starter.same_place(self.c("starter"), starter.REPO))
        self.assertTrue(os.path.islink(self.c("skills", "promote")))
        self.assertTrue(os.path.isfile(self.c("skills", "promote", "SKILL.md")))
        self.assertTrue(os.path.isfile(self.c("rules", "starter", "safety.md")))
        with open(self.c("CLAUDE.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), starter.STUB)
        self.assertTrue(os.path.isfile(self.c("CLAUDE.personal.md")))
        s = self.read_json(self.c("settings.json"))
        self.assertEqual(s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "sonnet")
        self.assertNotIn("@PY@", json.dumps(s))
        self.assertTrue(self.read_json(self.c("starter.json"))["auto_pull"])

    def test_existing_files_are_backed_up_and_split(self):
        os.makedirs(self.c("skills", "promote"))
        with open(self.c("skills", "promote", "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("mine")
        with open(self.c("CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# 自分の決めごと\n")
        self.write_json(self.c("settings.json"), {"theme": "dark", "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet", "X": "1"}})
        out = self.run_cmd("install", "--no-auto-pull")
        self.assertIn("退避先", out)
        backups = os.listdir(self.c("backups"))
        self.assertEqual(len(backups), 1)
        b = self.c("backups", backups[0])
        self.assertTrue(os.path.isfile(os.path.join(b, "skills", "promote", "SKILL.md")))
        self.assertTrue(os.path.isfile(os.path.join(b, "CLAUDE.md")))
        self.assertTrue(os.path.isfile(os.path.join(b, "settings.json")))
        with open(self.c("CLAUDE.personal.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# 自分の決めごと\n")
        personal = self.read_json(self.c("settings.personal.json"))
        self.assertEqual(personal, {"theme": "dark", "env": {"X": "1"}})
        self.assertEqual(self.read_json(self.c("settings.json"))["theme"], "dark")
        self.assertFalse(self.read_json(self.c("starter.json"))["auto_pull"])

    def test_prepared_personal_wins_on_first_install(self):
        self.write_json(self.c("settings.json"), {"statusLine": {"type": "command", "command": "old"}})
        self.write_json(self.c("settings.personal.json"), {"theme": "light"})
        self.run_cmd("install")
        s = self.read_json(self.c("settings.json"))
        self.assertIn("statusline.py", s["statusLine"]["command"])
        self.assertEqual(s["theme"], "light")
        self.assertEqual(self.read_json(self.c("settings.personal.json")), {"theme": "light"})

    def test_install_is_idempotent(self):
        self.run_cmd("install")
        out = self.run_cmd("sync")
        self.assertEqual(out, "")


class TestSync(HomeCase):
    def test_ui_change_moves_to_personal(self):
        self.run_cmd("install")
        s = self.read_json(self.c("settings.json"))
        s["permissions"]["allow"].append("Bash(make *)")
        s["model"] = "opus"
        self.write_json(self.c("settings.json"), s)
        out = self.run_cmd("sync")
        self.assertIn("settings.personal.json へ移した", out)
        personal = self.read_json(self.c("settings.personal.json"))
        self.assertEqual(personal["model"], "opus")
        self.assertIn("Bash(make *)", personal["permissions"]["allow"])
        self.assertEqual(self.run_cmd("sync"), "")

    def test_removed_skill_link_is_unlinked_but_own_skill_kept(self):
        self.run_cmd("install")
        fake = os.path.join(starter.HOME_SRC, "skills", "zz-gone")
        os.symlink(fake, self.c("skills", "zz-gone"))  # リポから消えた skill へのリンクに見立てる
        os.makedirs(self.c("skills", "mine"))
        out = self.run_cmd("sync")
        self.assertIn("unlink skills/zz-gone", out)
        self.assertFalse(os.path.lexists(self.c("skills", "zz-gone")))
        self.assertTrue(os.path.isdir(self.c("skills", "mine")))

    def test_hook_mode_never_raises(self):
        with mock.patch.object(starter, "sync_links", side_effect=RuntimeError("boom")), \
                mock.patch.object(starter, "maybe_pull", lambda log: None):
            out = self.run_cmd("sync", "--hook")
        self.assertIn("sync に失敗", out)


class TestCue(HomeCase):
    def setUp(self):
        super().setUp()
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.proj, ".claude", "rules"))

    def cue(self):
        return starter.cue(json.dumps({"cwd": self.proj}))

    def write(self, rel, text):
        f = os.path.join(self.proj, rel)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_first_sight_is_baseline_then_changes_become_candidates(self):
        self.write(".claude/rules/a.md", "a")
        self.assertIsNone(self.cue())
        self.assertIsNone(self.cue())
        self.write(".claude/rules/a.md", "a2")
        self.write(".claude/skills/x/SKILL.md", "x")
        self.write("src/main.py", "ignored")
        out = self.cue()
        self.assertIn("2 件", out["systemMessage"])
        items = starter.load_candidates()
        self.assertEqual(sorted(i["file"] for i in items), [".claude/rules/a.md", ".claude/skills/x/SKILL.md"])
        self.write(".claude/rules/a.md", "a3")  # 未判定の同じファイルは増やさない
        self.assertIsNone(self.cue())
        self.assertEqual(len(starter.load_candidates()), 2)

    def test_skeleton_origin_and_close(self):
        self.write(".claude/rules/s.md", "s")
        self.write(".claude/skeleton.json", json.dumps({"files": {".claude/rules/s.md": {}}}))
        self.cue()
        self.write(".claude/rules/s.md", "s2")
        self.cue()
        items = starter.load_candidates()
        self.assertEqual(items[0]["origin"], "skeleton")
        out = self.run_cmd("candidates", "--close", str(items[0]["id"]), "--as", "スケルトン")
        self.assertIn("スケルトン", out)
        self.assertEqual(self.run_cmd("candidates").strip(), "候補なし")

    def test_repo_itself_is_ignored(self):
        self.assertIsNone(starter.cue(json.dumps({"cwd": starter.REPO})))


class TestCheckPublic(unittest.TestCase):
    def scan(self, text, deny=None):
        return check_public.scan("t", text, deny or [], True)

    def test_detects_formats(self):
        hits = self.scan("/home/alice/x\nC:\\Users\\bob\\x\na@b.co.jp\n192.168.1.5\n" + "AKIA" + "ABCDEFGHIJKLMNOP\n")
        kinds = " ".join(hits)
        for k in ("ホームの絶対パス", "メールアドレス", "プライベート IP", "トークン(AWS)"):
            self.assertIn(k, kinds)

    def test_allows_placeholders_and_noreply(self):
        text = "~/.claude/starter/home/x\nC:\\Users\\<ユーザー名>\\x\nx@users.noreply.github.com\nt@example.invalid\n"
        self.assertEqual(self.scan(text), [])

    def test_denylist_word_boundary_and_regex(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("# c\nACME\nre:secret-\\d+\n社名\n")
        try:
            deny = check_public.load_denylist(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(len(self.scan("the ACME project", deny)), 1)
        self.assertEqual(self.scan("ACMEX", deny), [])
        self.assertEqual(len(self.scan("secret-12", deny)), 1)
        self.assertEqual(len(self.scan("この社名は", deny)), 1)

    def test_repo_is_clean_without_denylist(self):
        r = subprocess.run([sys.executable, os.path.join(check_public.REPO, "scripts", "check_public.py"), "--denylist", os.devnull],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
