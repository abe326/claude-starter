#!/usr/bin/env bash
# PreToolUse hook のラッパー: python3 → python → py -3 の順に「実際に動く」ものを探して work_area_guard.py を起動する
# （Windows の Git Bash では python3 が無い、または Store のスタブで動かないことがあるため）。
# どれも無ければ exit 0（通す）。stdin はそのまま Python へ渡る。
set -u
case "$0" in */*) here="${0%/*}" ;; *) here="." ;; esac
guard="$here/work_area_guard.py"
[ -f "$guard" ] || exit 0

if python3 -c "pass" >/dev/null 2>&1; then
  exec python3 "$guard"
elif python -c "pass" >/dev/null 2>&1; then
  exec python "$guard"
elif py -3 -c "pass" >/dev/null 2>&1; then
  exec py -3 "$guard"
fi
exit 0
