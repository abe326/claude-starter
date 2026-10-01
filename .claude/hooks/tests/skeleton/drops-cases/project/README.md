# drops-cases/project — check_drops.py・close.py・new.py・build.py の異常系の模擬プロジェクト

`../../run_drops_cases.py` がケースごとに一時ディレクトリへ複製し、実物のスクリプトを入れて流す。
`dot-claude/` は複製先で `.claude/` になる（案件の中に入れ子の `.claude/` を置かないため）。
ケースの中身（打合せ記録など）はランナーの表が足す。ここを書き換えるとケースが崩れる。
