#!/usr/bin/env bash
# Stop hook: 作業の区切りで作業ログ（docs/案件/作業ログ/）を正本から作り直す。
# python3 → python → py -3 の順に「実際に動く」ものを探して scripts/work_log.py --quiet を起動する。
# 何も出さず、止めない（常に exit 0）。stdin は読まない。中身が変わらないファイルは書き換えない。
set -u
case "$0" in */*) here="${0%/*}" ;; *) here="." ;; esac
root="${CLAUDE_PROJECT_DIR:-$here/../..}"
script="$root/scripts/work_log.py"
[ -f "$script" ] || exit 0

if python3 -c "pass" >/dev/null 2>&1; then
  python3 "$script" --quiet >/dev/null 2>&1
elif python -c "pass" >/dev/null 2>&1; then
  python "$script" --quiet >/dev/null 2>&1
elif py -3 -c "pass" >/dev/null 2>&1; then
  py -3 "$script" --quiet >/dev/null 2>&1
fi
exit 0
