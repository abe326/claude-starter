# claude-starter

Claude Code の初期セット。~/.claude に入れる汎用の決めごと・skill・rules・hooks と、プロジェクトから育てて自動展開する仕組み

## まず読むもの

- `docs/プロジェクト概要.html` — 目的・設計原則・現在地・将来対応・構成図。ブラウザで開く
- `docs/README.md` — ドキュメントの索引と推奨読書順
- `docs/案件/01_タスク管理/index.html` — タスクの一覧（`build.py` で生成）

## 合わせ方（決まりは初期値）

ここにある決まりは、よくある失敗を防ぐための出発点。**合わなければ変えてよい。** 変えたら `docs/ハーネス台帳.md` に 1 行残す（`harness` スキル）。

| 変えたいこと | 変え方 |
|:--|:--|
| AI の口出しを減らす・増やす | フェーズ Sketch／Build（`python3 .claude/hooks/phase.py --set Sketch`）。AI も段階を見て切り替える |
| 区切りの拾い直しを止める | 環境変数 `CLAUDE_PICKUP=off` |
| 置き場のガードに、案件で決まった場所を通させる | `.claude/project.json` の `work_area_allow` |
| 入れ子の別リポを扱う | `.claude/project.json` の `nested_repos` |
| あるファイルを保存したら、決まったことを AI に促させる | `.claude/project.json` の `save_cues`（`glob` と `cue` の組を足す） |
| スケルトンの新しい版に追従する | SessionStart に「スケルトン: vX → vY」が出たら AI が提案する。了承すれば new-project スキルが `--merge` で更新（手を入れていないファイルは自動、手を入れたものは混ぜるか一覧に） |
| 設計書を足す | `python3 scripts/add_doc.py <番号>`（一覧は `--list`） |
| skill・hook・ルール・許可を足す・外す | `harness` スキル（台帳に候補 → 承認して定義。外すときも同じ） |
| マシン側の plugin を止める | `.claude/settings.json` の `enabledPlugins`（project-skeleton の `SETUP.md` §8） |
| 変えたことを元のスケルトンにも返す | `docs/ハーネス台帳.md` の「返す」列に理由を書く |

## Claude Code で開く前に

- **初回は対話起動（`claude`）でこのフォルダを開き、ワークスペースを信頼する。** 信頼する前に `claude -p` で動かすと `.claude/settings.json` の許可が効かず、skill やテストが権限で止まる
- 案件で揃うのは `CLAUDE.md`・`.claude/`（rules・skills・hooks・settings.json）・`docs/ハーネス台帳.md`。マシンの `~/.claude/` の指示・plugin・hook は合算されて動く。混ざっていればセッション開始時に「マシン側:」の行が出る
- 抑え方と書き分けの表は project-skeleton の `SETUP.md` §8「案件で Claude Code を使うとき」

## セットアップ

```
# 1. 依存の導入
#
# 2. 環境変数
cp .env.example .env    # 値は 環境情報.md（Git 管理外）を見て埋める
#
# 3. 起動
#
```

## 作業の決めごと

Claude Code で作業する前提の構成。ルールは `CLAUDE.md` と `.claude/rules/` にある。

- 秘密は `環境情報.md` と `.env` にだけ書く（どちらも Git 管理外）
- 一時ファイルは `.work/一時/YYYYMMDD_用途/` に置く（ルート直下に散らかさない）
- 案件ごとの違い（仕組みが固定で使う置き場・入れ子の別リポ）は `.claude/project.json` に書く。hook のコードは書き換えない
- 置き場のチェックは `.claude/hooks/work_area_guard.py`（PreToolUse hook）が行う。**python が PATH に無いマシンでは素通りになる**ので、Windows は `winget install Python.Python.3.12` で入れておく
- `.claude/settings.json` の `permissions.deny` は履歴の破壊と `--no-verify` を止める（05 を足していれば §9 と対応。元は `docs/設計書/template/05-セキュリティ.md`）。本番環境への操作など止めたいコマンドは `harness` スキルで 05 §9 と一緒に足す
- サブエージェントの既定モデルは `settings.json` の `env`（`CLAUDE_CODE_SUBAGENT_MODEL=sonnet`）で揃えている

---

作成: 2026-10-01 ／ 管理: （未定） ／ project-skeleton v1.5.0
