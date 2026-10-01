"""machine_context.py（マシン側の plugin・hook・ワークスペース信頼の 1 行）のテスト。"""
from __future__ import annotations

import json
import unittest

from _util import ROOT, TempProject, run_py, write

HOOK = ROOT / ".claude/hooks/machine_context.py"
USER = {
    "enabledPlugins": {"security-guidance@mk": True, "frontend-design@mk": True, "old@mk": False},
    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
}


def run(project, home, **env):
    e = {"HOME": str(home), "USERPROFILE": str(home), "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_CONFIG_DIR": ""}
    e.update(env)
    return run_py(HOOK, env=e)


class MachineContext(unittest.TestCase):
    def test_empty_home_is_silent(self):
        with TempProject() as root, TempProject() as home:
            r = run(root, home)
            self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_plugins_and_hooks(self):
        with TempProject() as root, TempProject() as home:
            write(home / ".claude/settings.json", json.dumps(USER))
            r = run(root, home)
            self.assertEqual(r.returncode, 0)
            lines = r.stdout.strip().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("plugin 2 個（frontend-design・security-guidance）", lines[0])
            self.assertIn("hook 1 本（Stop 1）", lines[0])

    def test_project_disables_one(self):
        with TempProject() as root, TempProject() as home:
            write(home / ".claude/settings.json", json.dumps(USER))
            write(root / ".claude/settings.json", json.dumps({"enabledPlugins": {"security-guidance@mk": False}}))
            out = run(root, home).stdout
            self.assertIn("plugin 1 個（frontend-design）", out)

    def test_broken_json(self):
        with TempProject() as root, TempProject() as home:
            write(home / ".claude/settings.json", "{壊れている")
            r = run(root, home)
            self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_untrusted(self):
        with TempProject() as root, TempProject() as home:
            write(home / ".claude.json", json.dumps({"projects": {str(root): {"hasTrustDialogAccepted": False}}}))
            self.assertIn("ワークスペース未信頼", run(root, home).stdout)
            write(home / ".claude.json", json.dumps({"projects": {str(root): {"hasTrustDialogAccepted": True}}}))
            self.assertEqual(run(root, home).stdout, "")
            parent = str(root.parent)
            write(home / ".claude.json", json.dumps({"projects": {str(root): {}, parent: {"hasTrustDialogAccepted": True}}}))
            self.assertEqual(run(root, home).stdout, "")      # 祖先を信頼していれば出さない
            write(home / ".claude.json", json.dumps({"projects": {}}))
            self.assertEqual(run(root, home).stdout, "")      # 項目が無ければ判定しない


if __name__ == "__main__":
    unittest.main()
