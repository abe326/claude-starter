"""scripts/tests/ の共通部品（テスト本体ではない）。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS = ROOT / ".claude/hooks"
sys.path.insert(0, str(HOOKS))

PHASE_HTML = """<!doctype html>
<html><head><meta charset="UTF-8"></head><body>
<section id="phase">
  <!-- BEGIN:phase -->
  <div class="phase"{attr}>
    <div class="name">{name}</div>
    <div class="word">次の一手: 何かする。</div>
  </div>
  <!-- END:phase -->
  <div class="name">マーカー外</div>
</section>
</body></html>
"""


def overview_html(phase: str | None, name: str = "Sketch") -> str:
    attr = "" if phase is None else f' data-phase="{phase}"'
    return PHASE_HTML.format(attr=attr, name=name)


class TempProject:
    """一時ディレクトリに最小の案件を作る。with で使う。copy に渡したルート相対パスは実物を複製する。"""

    def __init__(self, copy: tuple[str, ...] = ()):
        self.copy = copy

    def __enter__(self) -> Path:
        self.dir = Path(tempfile.mkdtemp(prefix="skel-test-"))
        for rel in self.copy:
            src = ROOT / rel
            dst = self.dir / rel
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        return self.dir

    def __exit__(self, *exc) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def run_py(script: Path, *args: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    e.pop("CLAUDE_SKELETON_PHASE", None)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, str(script), *args], cwd=str(cwd) if cwd else None, env=e,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
