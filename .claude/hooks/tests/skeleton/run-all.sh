#!/usr/bin/env bash
# hooks の回帰テスト。
#   1) work_area_guard: hook-cases-guard.txt の各行（<期待>\t<file_path>[\t<root>]）を PreToolUse の JSON にして
#      work_area_guard.sh へ流し、期待どおり allow / block になるかを見る
#   2) design_docs_reminder: hook-cases-reminder.txt の各行（<期待>\t<file_path>\t<含む文字列>\t<session_id>\t<root>\t<フェーズ>）を
#      PostToolUse の JSON にして design_docs_reminder.sh へ流し、additionalContext の有無と内容を見る
#      （影響マップは reminder-fixture/ の固定の表を使う。テンプレや案件の設計書 README に左右されない。
#       フェーズは CLAUDE_SKELETON_PHASE で渡し、省略時は Build）
#      3〜6 列目の空欄は `-` で書く。bash の `IFS=$'\t' read` は連続するタブを 1 つに畳むので、空のタブ区切りは列ずれを起こす。
#      末尾の列は省略してよい（guard 側は省略可能な列が最後の 1 つだけなので、この問題は起きない）
#   3) pickup: run_pickup_cases.py（hook-cases-pickup.txt。UserPromptSubmit → PostToolUse → Stop の手順つきケース）
#   4) drops: run_drops_cases.py（あれば。check_drops.py・close.py・new.py の異常系）
#   5) scripts/tests/run_tests.py（あれば。phase・秘密検出・ハーネス・machine_context などの unittest）
#   3〜5 は各ランナーの最後の行 `pass=N fail=M` を足し込む。
# 使い方: bash .claude/hooks/tests/run-all.sh   （pass=N fail=M を 1 本で出し、fail>0 なら exit 1）
# hook の状態ファイルは mktemp -d の一時ディレクトリに書く（消さない。OS の一時領域の掃除に任せる）
set -u
here="$(cd "$(dirname "$0")" && pwd)"
root_default="$(cd "$here/../../../.." && pwd)"
export CLAUDE_DOCS_REMINDER_STATE_DIR="$(mktemp -d)"
export PYTHONDONTWRITEBYTECODE=1
unset CLAUDE_PICKUP CLAUDE_PICKUP_MAX_BLOCKS

PY=""
if python3 -c "pass" >/dev/null 2>&1; then PY=python3
elif python -c "pass" >/dev/null 2>&1; then PY=python
else echo "python が無いので実行できない"; exit 1
fi

pass=0; fail=0

# --- 1) work_area_guard ------------------------------------------------------
hook="$here/../../work_area_guard.sh"
cases="$here/hook-cases-guard.txt"
while IFS=$'\t' read -r expect path root; do
  case "$expect" in ''|'#'*) continue ;; esac
  [ -n "${root:-}" ] || root="$root_default"
  json=$("$PY" -c 'import json,sys; print(json.dumps({"tool_name":"Write","tool_input":{"file_path":sys.argv[1]}}, ensure_ascii=False))' "$path")
  err=$(printf '%s' "$json" | CLAUDE_PROJECT_DIR="$root" bash "$hook" 2>&1 >/dev/null)
  rc=$?
  if [ "$rc" -eq 2 ]; then got=block; else got=allow; fi
  if [ "$got" = "$expect" ]; then
    pass=$((pass+1))
  else
    fail=$((fail+1))
    printf 'NG guard expect=%s got=%s (rc=%s) : %s  [root=%s]\n    %s\n' "$expect" "$got" "$rc" "$path" "$root" "$err"
  fi
done < "$cases"

# --- 2) design_docs_reminder ---------------------------------------------------
hook="$here/../../design_docs_reminder.sh"
cases="$here/hook-cases-reminder.txt"
fixture="$here/reminder-fixture"
# {WIN} = フィクスチャの Windows 形式（/mnt/c/x → C:\x、/c/x → C:\x）。変換できなければそのまま。
# ルート列の {WIN} は、Windows 上ではその形を、それ以外では実際に開ける fixture を使う（file_path 側だけ Windows 形式で流す）
win_root=$("$PY" -c 'import re,sys; p=sys.argv[1]; m=re.match(r"^/(?:mnt/)?([a-zA-Z])/(.*)$", p); print(m.group(1).upper()+":\\"+m.group(2).replace("/","\\") if m else p)' "$fixture")
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) win_root_for_env="$win_root" ;; *) win_root_for_env="$fixture" ;; esac

run_reminder() {  # $1=tool_name $2=file_path $3=session_id $4=root $5=phase → stdout
  local json
  json=$("$PY" -c 'import json,sys; d={"tool_name":sys.argv[1],"tool_input":{"file_path":sys.argv[2]}}
if sys.argv[3]: d["session_id"]=sys.argv[3]
print(json.dumps(d, ensure_ascii=False))' "$1" "$2" "$3")
  printf '%s' "$json" | CLAUDE_PROJECT_DIR="$4" CLAUDE_SKELETON_PHASE="${5:-Build}" bash "$hook" 2>/dev/null
}

while IFS=$'\t' read -r expect path want sid root phase; do
  case "$expect" in ''|'#'*) continue ;; esac
  [ "${want:-}" != "-" ] || want=""            # `-` は空欄
  [ "${sid:-}" != "-" ] || sid=""
  [ "${root:-}" != "-" ] || root=""
  [ "${phase:-}" != "-" ] || phase=""
  path="${path//\{WIN\}/$win_root}"
  root="${root:-}"; root="${root//\{WIN\}/$win_root_for_env}"
  [ -n "$root" ] || root="$fixture"
  out=$(run_reminder Write "$path" "${sid:-}" "$root" "${phase:-Build}")
  case "$out" in *additionalContext*) got=remind ;; *) got=none ;; esac
  ok=1
  [ "$got" = "$expect" ] || ok=0
  if [ "$ok" -eq 1 ] && [ -n "${want:-}" ]; then
    case "$want" in
      '!'*) case "$out" in *"${want#!}"*) ok=0 ;; esac ;;
      *) case "$out" in *"$want"*) ;; *) ok=0 ;; esac ;;
    esac
  fi
  if [ "$ok" -eq 1 ]; then
    pass=$((pass+1))
  else
    fail=$((fail+1))
    printf 'NG reminder expect=%s got=%s want=%s : %s  [sid=%s root=%s phase=%s]\n    %s\n' "$expect" "$got" "${want:-}" "$path" "${sid:-}" "$root" "${phase:-Build}" "$out"
  fi
done < "$cases"

# tool_name が Read なら何も出さない
out=$(run_reminder Read "src/auth/login.py" "" "$fixture" Build)
if [ -z "$out" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'NG reminder tool_name=Read で出力があった:\n    %s\n' "$out"; fi

# --- 3〜5) python のランナー（最後の行の pass=N fail=M を足し込む）------------------
run_sub() {  # $1=名前 $2=スクリプト → 集計に足す。失敗時はランナーの出力を見せる
  local name="$1" script="$2" out last p f rc
  [ -f "$script" ] || return 0
  out=$("$PY" "$script" 2>&1); rc=$?
  last=$(printf '%s\n' "$out" | grep -E '^pass=[0-9]+ fail=[0-9]+$' | tail -n 1)
  if [ -z "$last" ]; then
    fail=$((fail+1))
    printf 'NG %s: pass=N fail=M の行が無い (rc=%s)\n%s\n' "$name" "$rc" "$(printf '%s\n' "$out" | tail -n 20)"
    return 0
  fi
  p=${last#pass=}; p=${p%% *}; f=${last##*fail=}
  pass=$((pass+p)); fail=$((fail+f))
  if [ "$f" -ne 0 ] || [ "$rc" -ne 0 ]; then
    [ "$f" -ne 0 ] || fail=$((fail+1))
    printf 'NG %s: %s (rc=%s)\n%s\n' "$name" "$last" "$rc" "$(printf '%s\n' "$out" | grep -v -E '^(ok |pass=)' | tail -n 40)"
  fi
}
run_sub pickup "$here/run_pickup_cases.py"
run_sub drops "$here/run_drops_cases.py"
run_sub run_tests "$root_default/scripts/tests/run_tests.py"

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
