---
name: harness
description: この案件のハーネス（skill・hook・rules・permissions・agents・env・MCP）の漏れに気づき、候補を docs/ハーネス台帳.md に書き、ユーザーの承認後に定義する手順。同じ手順を 2 回した、同じ Bash の承認を 2 回求めた・権限で拒否された、「しないで」「二度と」と言われた、同じ指摘を 2 回受けた、テストや lint の実行手段が無かった、同じ種類の委譲を 2 回した、SessionStart に「マシン側:」や「ハーネス候補:」が出た、期待しない hook・plugin が動いた、フェーズを切り替えた、「ハーネスを整えて」「許可を足して」「毎回聞かないで」と言われたときに使う。承認なしに定義しない。
---

# harness

この案件で Claude の動きを揃える仕組み（ハーネス）を、**候補 → ユーザー承認 → 定義** の順で育てるスキル。
観点カタログは「漏れに気づく目」であって、記入欄ではない。全観点を埋めさせない。

- 台帳: `docs/ハーネス台帳.md`（候補・定義済・見送り・マシン依存を 1 行ずつ。セッションをまたいだ「2 回目」の記憶を兼ねる）
- 検査: `python3 scripts/check_skeleton.py --harness`（定義したものの形だけを見る。何も定義しなければ対象ゼロ）
- スケルトンが最初から持つ skill・hook・rules は運用の型としてコアに残す。台帳には書かない

## 観点カタログ（11 観点）

| 観点 | 気づくきっかけ | 問い | 定義先 |
|---|---|---|---|
| 権限 | 同じ Bash の承認を 2 回求めた / 権限で拒否された | 毎回許してよいコマンドはどれか | `.claude/settings.json` の `permissions.allow` |
| 危険操作 | 「〜しないで」「勝手に〜しないで」/ 本番・履歴・データを壊す操作に触れた | 機械で止めるべき操作はどれか | `permissions.deny` + 05 §9 の行（状態を決定に） |
| 秘密 | 新しい種類の秘密（鍵ファイル・証明書・接続文字列）が出た | 置き場と検出は足りているか | `環境情報.md`・`.gitignore`・`.claude/rules/secrets.md` |
| 品質ゲート | テストを実行しようとして手段が無い / 同じ検証コマンドを 2 回打った | テスト・lint の実行コマンドは何か。無いときは入れるか、報告して止まるか | 06 §2・§7、CLAUDE.md §5、`permissions.allow` の該当コマンド |
| 文脈注入 | セッション開始のたびに同じ調べもの（同じファイル・同じコマンド）を 2 回した | 毎回最初に知るべきことは何か | `.claude/hooks/session_context.sh` に 1 行、または CLAUDE.md §2 |
| 定型手順 | 同じ手順を 2 回した | 手順を skill にするか | `.claude/skills/<名前>/SKILL.md` |
| 繰り返す指摘・出力規約 | 同じ指摘・同じ書式の直しを 2 回受けた | 決まりとして書くか | `.claude/rules/<名前>.md`、CLAUDE.md 制約 9〜、04 設計原則 |
| 役割エージェント | 同じ種類の委譲（レビュー・調査）を 2 回した | 定義して再利用するか | `.claude/agents/<名前>.md`（`model` 必須） |
| モデルとコスト | サブエージェントが想定より高いモデルで走った / 長い委譲が続く | 既定モデルと上げる条件は | agents の `model`、`.claude/settings.json` の `env` |
| 外部接続 | 外部サービス・MCP に触る必要が出た | 何に、どの権限でつなぐか | `.mcp.json`、05 §2、`環境情報.md`（値） |
| グローバルとの干渉 | SessionStart に「マシン側:」が出た / 期待しない hook が走った / skill が権限で拒否された | 案件で抑えるか、マシン側の問題として記録するか | 下の「グローバルとの干渉」、台帳の「マシン依存」行 |

- 「2 回」は台帳で数える。1 回目は候補として 1 行書き、2 回目はその行のきっかけ欄に日付を足す
- **スケルトンの決まりが合わず変えた・外した**（hook を止めた、ルールを緩めた、テンプレの仕組みを直した）ときも台帳に 1 行書く。ほかの案件でも効きそうなら「返す」列に理由を書く（スケルトン側が `scripts/collect_returns.py` で集めて取り込むかを決める）
- 05 §9「Claude Code が行ってはいけない操作」は「危険操作」の定義先の 1 つ（05 の構成は変えない）

## 候補を書く（Claude が書く。確認しない）

きっかけに当たったら、作業を止めずに台帳へ 1 行足す。

```markdown
| HN-01 | 品質ゲート | テストの実行方法（pytest が無く止まった） | 2026-09-23 実装 APP-03 | 候補 | 06 §7・CLAUDE.md §5・permissions.allow | 2026-09-23 |
```

- ID は台帳の最大 +1（HN-01 から）。タスク ID・課題 ID とは別の番号
- 同じきっかけが再び起きたら、新しい行を作らず同じ行のきっかけ欄に日付を足す
- 打合せ記録や会話から拾ったものの落ち先は「→ ハーネス候補 HN-01」と書く（`pickup` スキル）
- 値（URL・トークン・パスワード）は台帳に書かない。秘密は `環境情報.md`

## 提示する（承認を迫りすぎない）

提示するのは次の 4 つのときだけ。

1. 同じ候補のきっかけが 2 回になった区切り
2. フェーズを切り替えたとき（`update-overview` スキルの手順 4 で、観点カタログを 1 回通して見る）
3. ユーザーが「ハーネスを整えて」と言ったとき
4. その候補が今の作業を止めているとき（例: テストの実行手段が無い）。**このときだけは作業中でも 1 問で聞く**

提示の形: 候補ごとに「定義先・効果・リスク」と推奨 1 つ。複数あれば表 1 つにまとめる。**決めるのはユーザー。**

- 承認 → 下の「定義する」→ 検査 → 台帳の状態を「定義済」、定義先にバッククォートでパス、更新日
- 見送り → 状態を「見送り」、内容欄に理由を 1 行。同じ候補を再提案しない

## 定義する（承認後）

定義先の多く(`.claude/settings.json`・`.claude/skills/`・`.claude/hooks/`・`.claude/rules/`・`.claude/agents/`)は、Claude Code が編集のたびに承認を求める領域にある。その承認がユーザーの承認の関門を兼ねる。候補の台帳が `docs/` にあるのは、候補を書くたびに承認を求めないため。

| 定義先 | 手順の要点 | 検査（`check_skeleton.py --harness`） |
|---|---|---|
| `permissions.allow` / `deny` | パターンは最小。`pip install`・`npm install` などの導入系は allow しない（入れるかどうかは毎回人が決める）。deny は 05 §9 に行を足し、状態を「決定」、deny 列にパターンをバッククォートで書く | 05 §9 の決定行の deny 列のパターンが `settings.json` の deny にある |
| hook | `.claude/hooks/<名前>.sh` と `.py` の組（既存と同じ「python を探す sh + py」型）。`settings.json` に登録。テストケースを `.claude/hooks/tests/skeleton/` に 1 行以上 | 参照スクリプトの実在 |
| skill | `.claude/skills/<名前>/SKILL.md`。frontmatter は `name`・`description`。**`allowed-tools` は付けない**（未信頼のワークスペースで起動を拒否される） | frontmatter の name・description |
| rule | `.claude/rules/<名前>.md`。1 ルール 1 ファイル、20 行以内 | — |
| agents | `.claude/agents/<名前>.md`。**frontmatter に `model` を必ず書く**（`inherit` / `haiku` / `sonnet` / `opus` / `fable` か `claude-` で始まる ID）。継承させたいなら `model: inherit` と書く | `model` が無い・空・上の値以外 → NG |
| env | `.claude/settings.json` の `env`。サブエージェントの既定は `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`（上げるなら台帳経由） | — |
| 台帳 | 状態・定義先・更新日を書く | 状態が 4 値のどれか / 定義済の定義先が実在 |

- コア以外の skill・rules・agents・hook が台帳の定義済に無いと、検査が件数を出す（Sketch は情報、Build は警告。止めない）
- 定義したら `python3 scripts/check_skeleton.py` を回し、fail=0 を確かめてから報告する

### 最初の昇格例（品質ゲート）

テストを実行しようとして pytest が無く止まった → 観点「品質ゲート」の候補「テストの実行方法」を台帳に書く → 提示 4 に当たるので 1 問で聞く → 承認なら 06 §7 に実行コマンド、CLAUDE.md §5 に 1 行、`permissions.allow` にそのコマンド。`pip install` は許可しない。

## グローバルとの干渉

SessionStart に「マシン側: plugin N 個（名前…）・hook M 本」が出たら、マシンの `~/.claude/settings.json` の plugin・hook が案件に混ざっている。

| 手段 | 抑えられるもの | 置き場 |
|---|---|---|
| 干渉する plugin を `enabledPlugins` で `"<名前>@<マーケット>": false` にする（完全な名前はマシンの `~/.claude/settings.json`） | plugin の注入・plugin 内の hook・skill | 案件の `.claude/settings.json`（全員に効かせる）か `.claude/settings.local.json`（このマシンだけ） |
| グローバル hook 側で案件を見分けて抜ける（CLAUDE.md 1 行目の `project-skeleton` の印を見る） | ユーザー設定の hook | マシンの `~/.claude` の hook |
| 自動実行で `--setting-sources project,local` | ユーザー設定すべて | 起動コマンド（対話では使わない） |

- 案件で抑えたら台帳に「定義済」、マシン側で直すものは「マシン依存」として 1 行残す
- 初回に対話起動でワークスペースを信頼していないと、案件の `permissions` が効かない（SessionStart に「ワークスペース未信頼」が出る）

## 禁止

- 承認なしに skill・hook・rules・permissions・agents・env を定義・変更しない（台帳に候補を書くまで）
- 観点カタログを全部埋めようとしない。フェーズ切り替え時に 1 回通して見るだけ
- 導入系のコマンド（`pip install`・`npm install` など）を allow に入れない
- 見送りになった候補を再提案しない
