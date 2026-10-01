#!/usr/bin/env python3
"""scripts/tests/ の unittest をまとめて回す入口。

使い方: python3 scripts/tests/run_tests.py [-v]
出力: unittest の結果 + 最後に `pass=N fail=M`。fail>0 なら exit 1。標準ライブラリのみ。
スケルトン側の scripts/check.py と .claude/hooks/tests/skeleton/run-all.sh からも呼ばれる。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    # テストが案件の実物のフェーズに左右されないよう、環境変数の指定は外して始める
    os.environ.pop("CLAUDE_SKELETON_PHASE", None)
    sys.path.insert(0, HERE)
    suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py", top_level_dir=HERE)
    result = unittest.TextTestRunner(verbosity=2 if "-v" in argv else 1, stream=sys.stdout).run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"pass={result.testsRun - failed - len(result.skipped)} fail={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
