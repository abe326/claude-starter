<!-- project-skeleton v1.5.0 generated 2026-10-01 -->
# claude-starter

## 1. このプロジェクトについて

Claude Code の初期セット。~/.claude に入れる汎用の決めごと・skill・rules・hooks と、プロジェクトから育てて自動展開する仕組み

詳細（目的・思想・現在地・将来対応・構成図）は `docs/プロジェクト概要.html` が正本。

**ここの決まりは初期値。** 利用者の方針に合わなければ変えてよい（変え方は `README.md`「合わせ方」。変えたら `harness` スキルで台帳に 1 行）。人が見るものはシンプルに、AI が読む正本は詳細に書く。

## 2. セッション開始時にすること

1. SessionStart の注入（フェーズ・open タスク・設計書の状況）を読む。詳しい現在地は `docs/プロジェクト概要.html` の「3. 現在地」
2. **フェーズで厳しさが変わる。** Sketch: 拾って落とすだけ（設計書は未記入でよい）/ Build: 設計書を実装・決定に追随させ、本番操作は 05 §9（足していれば）。表は `python3 .claude/hooks/phase.py --table`
3. 概要 HTML の「決めてほしいこと」「次の節目」で未決と期日を把握する（実名の待ち・公開しない日程は `案件情報.md`）
4. Build では、作業種別に応じて §7 の表の文書を読む。SessionStart が「設計書: 要確認 N 本」を出したら、着手する領域の設計書だけ先に読む
5. SessionStart に「スケルトン: vX → vY」が出たら、依頼された作業が一段落してから利用者に 1 行で更新を提案する（了承されたら new-project スキル。既存の資料から空欄を埋めるのは `draft-from-existing` スキル）

## 3. Global Constraints（逐語厳守）

以下は本リポジトリでの作業における絶対制約。優先度は記載順ではなく全て同格の必須事項として扱う。

1. **ファイルを作る前に、work-placement か scratch かを決める。** タスクに紐づく作業は `work-placement` スキル、それ以外の一時的な出力は `scratch` スキル。決めずに書き始めない
2. **一時ファイルは `.work/一時/YYYYMMDD_用途/` 以外に作らない。** プロジェクトルート直下・`.work/` 直下・`.work/一時/` 直下には置かない（PreToolUse hook が機械的に止める）
3. **環境・ユーザー・関係者・日程を変えたら、同じ作業の中で `update-env-info` スキルを実行する。** `環境情報.md` / `案件情報.md` を後回しにしない
4. **フェーズ・方針・ロードマップが動いたら `update-overview` スキルで `docs/プロジェクト概要.html` を更新する。** Sketch の間は現在地とフェーズの 1 行だけでよい。フェーズの切り替えは AI が判断し、同じスキルで行う（確認は挟まない。報告で 1 行伝える）
5. **秘密（URL・ID・パスワード・API キー・トークン）は `環境情報.md` と `.env` にだけ書く。** `docs/`・概要 HTML・タスク md・会話出力へ転記しない（`.claude/rules/secrets.md`）
6. **応答・文書は日本語。** コード識別子・コマンド・固有名詞は原語のまま
7. **作業の区切りで、出てきた決定・未決・あとでやることを `pickup` スキルで落とす。1 つの事柄の正本は 1 か所: あとでやること → タスク、決まっていないこと → 課題、決まったこと → 課題の `## 決定`（その場で決まったものも `new.py … --decided` で起票してすぐ閉じる）。落ち先の無いまま残さない。** Sketch の間は拾うだけ。Build では設計書に影響が出たら同じ作業の中で `sync-design-docs` スキル。空欄・未記入の多さでは止めない
8. **ハーネス（skill・hook・rule・permissions・agents）はユーザーの承認なしに定義しない。** 同じ手順を 2 回した・「しないで」と言われた・同じ指摘を 2 回受けたら、`harness` スキルで `docs/ハーネス台帳.md` に候補として書く。`.claude/agents/*.md` の定義には `model` を必ず書く

<!-- プロジェクト固有の制約をここに追記する（番号は 9 から続ける） -->
9. **このリポは public。個人の事情（実名・メールアドレス・社名・案件名・マシン名・IP・ホームの絶対パス・Slack チャンネル）を書かない。** commit の前に `python3 scripts/check_public.py --history` を通す。個人の事情は各マシンの `~/.claude/CLAUDE.personal.md`・`settings.personal.json` へ
10. **`home/` と `scripts/starter.py` は全マシンの `~/.claude` から使われている配布物。** 直した瞬間に、このマシンの全セッションに効く。壊すと全プロジェクトの起動が乱れるので、`scripts/` を変えたら `python3 scripts/tests/run_tests.py` を通してから作業を終える
11. **Anthropic 製の skill（docx・pdf・pptx・xlsx など）は収録しない。** 再配布できない

## 4. リポジトリ構造

```
claude-starter/
├── CLAUDE.md / README.md / CHANGELOG.md
├── 環境情報.md / 案件情報.md    ← Git 管理外の正本（秘密・関係者・日程）
├── docs/
│   ├── プロジェクト概要.html     ← 目的・思想・現在地・将来対応・構成図（正本）
│   ├── 案件/01_タスク管理/       ← タスク md（open/ closed/）＋ new.py / close.py / build.py
│   ├── 案件/02_打合せ/           ← 打合せ記録 YYYYMMDD_タイトル.md
│   ├── ハーネス台帳.md           ← ハーネスの候補・定義済（harness スキル）
│   ├── 案件/作業ログ/           ← 出来事の時系列（生成物。最新.md から読む）
│   └── 設計書/                  ← 設計の正本。最初は 01 だけ、template/ から足す（decisions/ に ADR、runbook/ に手順）。構成図の正本は .claude/rules/docs-management.md
├── home/                        ← 配布物（~/.claude にリンクされる）: CLAUDE.md / rules/ / skills/ / statusline/ / settings.base.json
├── personal.example/            ← 個人部の雛形
├── scripts/starter.py           ← install / sync（SessionStart）/ cue（Stop）/ candidates
├── scripts/check_public.py      ← 公開前検査（.public-allow で形式検査の例外）
├── .work/                       ← Git 管理外の作業領域（証跡/ 機密/ 一時/ _bk/ promote/）
└── .claude/                     ← rules/ skills/ hooks/ settings.json(編集は承認が要る領域)
```

## 5. 技術スタック

| レイヤー | 技術 | 備考 |
|---|---|---|
| 展開・同期・検査 | Python 3（標準ライブラリのみ） | `scripts/starter.py`・`scripts/check_public.py`。Windows はジャンクション（`_winapi.CreateJunction`） |
| 配布物 | Markdown・JSON | `home/`。CLAUDE.md の `@` 読み込み・`~/.claude/rules/`・`~/.claude/skills/` |
| skill の依存 | Node.js（pptx-template だけ） | `npm install` は install／sync が行う。`node_modules/` は Git 管理外 |
| CI | GitHub Actions | 形式検査（`--history`）・単体テスト・gitleaks |

## 6. 用語集

| 用語 | 意味 |
|---|---|
| 汎用部 | `home/` の配布物。公開してよい、どのマシン・プロジェクトでも効く決めごと |
| 個人部 | 各マシンの `~/.claude/CLAUDE.personal.md`・`settings.personal.json`・`public-denylist.txt`。リポに入れない |
| 候補 | プロジェクトで変わった skill・rules・agents・CLAUDE.md の記録（作業領域 .work の promote フォルダにある candidates.jsonl）。`promote` スキルで振り分ける |
| 公開前検査 | `scripts/check_public.py`。形式（トークン・メール・IP・絶対パス）と個人語リスト |

## 7. 作業前に読むもの

- **タスク・課題は open だけを読む**（`docs/案件/01_タスク管理/open/`）。closed は ID で指されたときだけ開く
- 最近の出来事は `docs/案件/作業ログ/最新.md` → 無ければ同じフォルダの `README.md`（索引）で月を絞る → その月 → 正本の ID
- 決まったことの正本は課題 md の `## 決定`。設計書は「今どうなっているか」を書き、「（決定 QA-03）」のように ID を指す
- 作業種別ごとに読む設計書は `docs/設計書/README.md` の「知りたいこと → 正本」。無い文書は、要るときに候補を出し、承認を得て `python3 scripts/add_doc.py <番号>` で足す
- 「決定」に反する実装・設定はそちらを直す。「未決」「提案」を根拠に指摘しない
