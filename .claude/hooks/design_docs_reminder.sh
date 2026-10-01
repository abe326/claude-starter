#!/usr/bin/env bash
# PostToolUse hook のラッパー: python3 → python → py -3 の順に「実際に動く」ものを探して design_docs_reminder.py を起動する
# （Windows の Git Bash では python3 が無い、または Store のスタブで動かないことがあるため）。
# どれも無ければ exit 0（何もしない）。stdin はそのまま Python へ渡る。
set -u
case "$0" in */*) here="${0%/*}" ;; *) here="." ;; esac
hook="$here/design_docs_reminder.py"
[ -f "$hook" ] || exit 0

if python3 -c "pass" >/dev/null 2>&1; then
  exec python3 "$hook"
elif python -c "pass" >/dev/null 2>&1; then
  exec python "$hook"
elif py -3 -c "pass" >/dev/null 2>&1; then
  exec py -3 "$hook"
fi
exit 0
