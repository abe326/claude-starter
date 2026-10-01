# reminder-fixture — design_docs_reminder の回帰テスト用の模擬プロジェクト

`../run-all.sh` の 2) が、この フォルダを CLAUDE_PROJECT_DIR にして `hook-cases-reminder.txt` を流す。
テンプレの `docs/設計書/README.md` を書き換えてもテストが崩れないように、影響マップをここに固定で持つ。
実物の影響マップが実ファイルに解決できるかは `scripts/check_skeleton.py` が見る。
（Claude Code が読み込まないよう、ここには `.claude/` と `CLAUDE.md` を置かない）
