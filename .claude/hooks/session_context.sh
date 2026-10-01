#!/usr/bin/env bash
# SessionStart hook: フェーズ・タスクの状況・概要 HTML の鮮度・環境情報の有無と当日の一時フォルダ数・設計書の要確認と未記入・
# 拾いもの・ハーネス候補とマシン側の混入・スケルトンの新しい版を、見出しを含め 8 行以内で注入する。
# 0 件の行（拾いもの・ハーネス/マシン側/スケルトン）は出さない。
# フェーズと厳しさの表は .claude/hooks/phase.py（表は --table）。stdout はそのまま Claude のコンテキストに入る。
# 秘密情報は出力しない。python が無くても動く（フェーズは grep で読む）。常に exit 0。
set -u
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0

PY=""
if python3 -c "pass" >/dev/null 2>&1; then PY=python3
elif python -c "pass" >/dev/null 2>&1; then PY=python
fi

echo "## セッションコンテキスト（session_context.sh 自動注入）"

# 0) フェーズ（phase.py。python が無ければ data-phase を grep。読めなければ Sketch 扱い）
OV="docs/プロジェクト概要.html"
phase_line=""
if [ -n "$PY" ] && [ -f ".claude/hooks/phase.py" ]; then
  phase_line=$("$PY" - <<'PYEOF' 2>/dev/null
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, ".claude/hooks")
import phase
p, problem = phase.phase_status(".")
note = {
    "Sketch": "拾うだけ。設計書は未記入でよい",
    "Build": "設計書追随が有効。直すなら sync-design-docs。本番操作は 05 §9",
}[p]
line = f"- フェーズ: {p}（{note}。表は python3 .claude/hooks/phase.py --table）"
if problem == "属性なし":
    line += "。概要 HTML に data-phase が無い（python3 .claude/hooks/phase.py --set <フェーズ> で設定）"
elif problem and problem.startswith("不正な値"):
    line += f"。概要 HTML の data-phase が{problem}（Sketch 扱い）"
s = phase.suggest(".", p)
if s:
    line += "。" + s
print(line)
PYEOF
  )
fi
if [ -z "$phase_line" ]; then
  ph=$(awk '/BEGIN:phase/{f=1} f{print} /END:phase/{f=0}' "$OV" 2>/dev/null | grep -oE 'data-phase="[^"]*"' | head -1 | cut -d'"' -f2)
  case "$ph" in 開発|運用|[Bb][Uu][Ii][Ll][Dd]) ph="Build" ;; *) ph="Sketch" ;; esac
  phase_line="- フェーズ: ${ph}（表は python3 .claude/hooks/phase.py --table）"
fi
echo "$phase_line"

# 1) タスク（data.js の window.TASKS から open 件数・うち課題・最高優先）
TM="docs/案件/01_タスク管理"
DATA="$TM/data.js"
if [ -f "$DATA" ]; then
  line=""
  if [ -n "$PY" ]; then
    line=$("$PY" - "$DATA" <<'PYEOF' 2>/dev/null
import json, sys
s = open(sys.argv[1], encoding="utf-8").read()
i = s.find("window.TASKS")
if i < 0:
    sys.exit(1)
j = s.find("[", i)
arr, _ = json.JSONDecoder().raw_decode(s[j:])
op = [t for t in arr if t.get("state") == "open"]
issue = sum(1 for t in op if t.get("kind") == "課題")
top = sum(1 for t in op if t.get("priority") == "最高")
prog = sum(1 for t in op if t.get("status") == "進行中")
print(f"{len(op)} 件（課題 {issue}・最高 {top}・進行中 {prog}）")
PYEOF
    )
  fi
  if [ -z "$line" ]; then
    # python 無し・解析失敗時の概算（state/kind/priority を独立に数えるので厳密ではない）
    open_n=$(grep -o '"state" *: *"open"' "$DATA" 2>/dev/null | wc -l | tr -d ' ')
    issue_n=$(grep -o '"kind" *: *"課題"' "$DATA" 2>/dev/null | wc -l | tr -d ' ')
    top_n=$(grep -o '"priority" *: *"最高"' "$DATA" 2>/dev/null | wc -l | tr -d ' ')
    line="${open_n:-0} 件（課題 ${issue_n:-0}・最高 ${top_n:-0}。grep 概算）"
  fi
  # 作業ログ（生成物）: 直近 14 日の件数だけ。中身は必要なときに最新.md から読む
  LOG="docs/案件/作業ログ/最新.md"
  log_part=""
  if [ -f "$LOG" ]; then
    log_n=$(grep -c '^- ' "$LOG" 2>/dev/null | tr -d ' ')
    log_part="。最近の出来事は ${LOG}（直近 14 日 ${log_n:-0} 件）"
  fi
  echo "- タスク: open ${line}（読むのは open だけ）。一覧は ${TM}/index.html、起票・クローズは task スキル。着手前に work-placement スキルで紐づけ先を確定${log_part}"
else
  echo "- タスク: ${DATA} が未生成（python3 ${TM}/build.py で生成）。着手前に work-placement スキルで紐づけ先を確定"
fi

# 2) 概要 HTML の最終更新日（BEGIN:updated … END:updated の間の日付）
if [ -f "$OV" ]; then
  upd=$(awk '/BEGIN:updated/{f=1} f{print} /END:updated/{f=0}' "$OV" 2>/dev/null | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1)
  echo "- 概要 HTML（${OV}）の最終更新: ${upd:-不明}。「3. 現在地」を読んでから着手。動いたら update-overview スキル"
else
  echo "- 概要 HTML（${OV}）が無い"
fi

# 3) 環境情報.md の有無（Git 管理外の正本。中身は出さない）と当日の一時フォルダ数（.work/一時/YYYYMMDD_*）
today=$(date +%Y%m%d)
n=$(ls -d ".work/一時/${today}_"* 2>/dev/null | wc -l | tr -d ' ')
if [ -f "環境情報.md" ]; then
  env_part="あり（秘密の正本。値は転記しない。変えたら update-env-info スキル）"
else
  env_part="無し（環境が増えたら update-env-info スキルで作る）"
fi
echo "- 環境情報.md: ${env_part}。.work/一時/ の本日フォルダ: ${n:-0} 個（一時ファイルは .work/一時/${today}_用途/ へ。scratch スキル）"

# 4) 設計書の要確認と未記入（docs_freshness.py --counts。python が無ければメタ行の有無だけ grep で数える）
DD="docs/設計書"
if [ -d "$DD" ]; then
  cnt=""
  if [ -n "$PY" ] && [ -f "scripts/docs_freshness.py" ]; then
    cnt=$("$PY" scripts/docs_freshness.py --counts 2>/dev/null)
  fi
  stale=$(printf '%s' "$cnt" | awk 'NF==2 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {print $1}')
  unfilled=$(printf '%s' "$cnt" | awk 'NF==2 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {print $2}')
  if [ -n "$stale" ]; then
    case "$phase_line" in *"フェーズ: Sketch"*) note="Sketch の間は未記入でよい。" ;; *) note="" ;; esac
    echo "- 設計書: 要確認 ${stale} 本・未記入 ${unfilled} 本（${note}一覧は python3 scripts/docs_freshness.py。直すなら sync-design-docs、棚卸しは audit-design-docs）"
  else
    miss=0
    for f in "$DD"/*.md; do
      [ -f "$f" ] || continue
      case "$f" in */README.md) continue ;; esac
      head -20 "$f" | grep -q "最終更新" || miss=$((miss+1))
    done
    echo "- 設計書: メタ行なし ${miss} 本（grep 概算。python を入れると鮮度も見る。直すなら sync-design-docs）"
  fi
fi

# 5) 拾いもの（check_drops.py --quiet: 警告 情報 落ち先なし 決めてほしいこと 期限切れ。表示する 4 つが全部 0 なら出さない）
if [ -n "$PY" ] && [ -f "scripts/check_drops.py" ]; then
  q=$("$PY" scripts/check_drops.py --quiet 2>/dev/null)
  set -- $q
  if [ "$#" -eq 5 ] && [ "$1$2$3$4$5" -eq "$1$2$3$4$5" ] 2>/dev/null; then
    if [ "$1" -gt 0 ] || [ "$3" -gt 0 ] || [ "$4" -gt 0 ] || [ "$5" -gt 0 ]; then
      echo "- 拾いもの: 落ち先なし $3 行・警告 $1 件 ／ 決めてほしいこと $4 件（期限切れ $5）。一覧は python3 scripts/check_drops.py、落とすのは pickup スキル"
    fi
  fi
fi

# 6) ハーネス候補（台帳の状態「候補」の行数）とマシン側の混入（machine_context.py）。どちらも 0 件なら出さない
parts=""
LEDGER="docs/ハーネス台帳.md"
if [ -f "$LEDGER" ]; then
  hn=$(grep -cE '^\|[[:space:]]*HN-[0-9]+[[:space:]]*\|.*\|[[:space:]]*候補[[:space:]]*\|' "$LEDGER" 2>/dev/null)
  if [ "${hn:-0}" -gt 0 ] 2>/dev/null; then
    parts="ハーネス候補: ${hn} 件（${LEDGER}。提示は harness スキル）"
  fi
fi
if [ -n "$PY" ] && [ -f ".claude/hooks/machine_context.py" ]; then
  mc=$("$PY" .claude/hooks/machine_context.py 2>/dev/null | head -1)
  if [ -n "$mc" ]; then
    parts="${parts:+${parts}。}${mc}"
  fi
fi
# 7) スケルトンの新しい版（skeleton_drift.py。無ければ出さない）。6) と同じ行にまとめて 8 行以内を保つ
if [ -n "$PY" ] && [ -f ".claude/hooks/skeleton_drift.py" ]; then
  sd=$("$PY" .claude/hooks/skeleton_drift.py 2>/dev/null | head -1)
  if [ -n "$sd" ]; then
    parts="${parts:+${parts}。}${sd}"
  fi
fi
[ -z "$parts" ] || echo "- ${parts}"

exit 0
