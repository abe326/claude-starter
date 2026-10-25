# claude-starter

Claude Code を使い始めるときに `~/.claude` に入れておく、**汎用の決めごと・skill・rules・hooks・status line の初期セット**。
入れたあとも、プロジェクトで直した「他でも使える改善」を取り込み、各マシンに自動で行き渡らせながら育てていける。

- 個人の事情（マシン名・案件・通知先など）はリポに入れず、各マシンの別ファイルに置く。公開しても漏れない作り
- 必要なもの: Claude Code、Python 3（標準ライブラリだけ）、git。Windows でも動く（リンクの代わりにジャンクション）
- 案件フォルダの型は姉妹リポ [project-skeleton](https://github.com/abe326/project-skeleton)。こちらはその一段上、ユーザー全体の層

## 入っているもの

| 種類 | 中身 | 場所 |
|:--|:--|:--|
| 決めごと | 応答の言語を守る・進め方の要点・このセットの育て方 | `home/CLAUDE.md` |
| rules | モデルとサブエージェントの使い分け（既定 sonnet・Explore にモデルを書く・本数を絞る）／取り返しのつかない操作と秘密の扱い／シェルの落とし穴 | `home/rules/` |
| skills | `smart-orchestrator`（委譲するかの判断とモデル選び）／`pptx-template`（スライドの共通デザイン）／`promote`（プロジェクトの改善を取り込む）／`peer-request`（プロジェクトのセッションどうしが同僚として依頼し合う） | `home/skills/` |
| settings | サブエージェントの既定モデル・読み取り系の許可・status line・hook | `home/settings.base.json` |
| status line | モデル名、このセッションのモデル別応答割合（メイン＋サブエージェント）、コンテキスト使用率、利用枠 | `home/statusline/statusline.py` |
| hooks | セッション開始時の自動同期／終了時の改善候補の記録 | `scripts/starter.py`（`sync --hook`／`cue`） |
| | 自分のプロジェクトのフォルダの外へ書かせない（プロジェクトごとに効かせる。既定は何もしない） | `home/hooks/own_folder_guard.py` |

`pptx-template` を使うには、Anthropic 製の `pptx` スキルが別途要る（再配布できないので含めていない）。

## 入れ方

```bash
git clone https://github.com/abe326/claude-starter.git ~/claude-starter
python3 ~/claude-starter/scripts/starter.py install --dry-run   # 何が変わるかを見る
python3 ~/claude-starter/scripts/starter.py install
```

Windows は `python3` を `python` に読み替える（PowerShell・Git Bash どちらでも可）。

install は次のことをする。置き換えるものは `~/.claude/backups/starter-YYYYmmdd-HHMMSS/` に退避する。

- `~/.claude/starter` → このリポ、`~/.claude/skills/<名前>`・`~/.claude/rules/starter` → `home/` の中をリンクする
- `~/.claude/CLAUDE.md` を、汎用部と個人部を読み込むだけの短いファイルにする。もとの中身は `~/.claude/CLAUDE.personal.md` に移す
- `~/.claude/settings.json` を `home/settings.base.json` ＋ `~/.claude/settings.personal.json` から作る。もとの設定のうち base に無いものは personal に移す

### 個人の部分（リポの外）

| ファイル | 書くこと |
|:--|:--|
| `~/.claude/CLAUDE.personal.md` | マシン・案件・自分の運用の決めごと。雛形は `personal.example/` |
| `~/.claude/settings.personal.json` | 好みの設定・広めの許可・plugin。base に重なる（list は足し合わせ、値は personal が勝つ） |
| `~/.claude/starter.json` | `auto_pull`（このマシンで 1 日 1 回 `git pull` するか） |
| `~/.claude/public-denylist.txt` | 公開前検査で弾く個人語（自分の名前・社名・ホスト名など）。`promote` で公開する人だけ |

`/config` などで設定を変えても、次のセッションの開始時に差分が `settings.personal.json` に移るので消えない。

## 使いながら育てる

```
プロジェクトで .claude/skills・rules・agents・CLAUDE.md を直す
  └─ セッション終了時の hook が「共通化の候補」として記録（.work/promote/、Git 管理外）
       └─ promote スキル: 汎用 / 個人 / project-skeleton へ返す / 却下 に振り分け（承認制）
            └─ 汎用の形に書き直して home/ へ → 公開前検査 → commit・push
                 └─ 各マシン: リンクなら即時、clone なら次のセッションの git pull で入る
```

- 公開前検査 `python3 scripts/check_public.py`: トークン・秘密鍵・メールアドレス・プライベート IP・ホームの絶対パスと、`public-denylist.txt` の語を見る（`--history` で全履歴も）。CI では形式検査・単体テスト・gitleaks を回す
- 自分用に fork して育てる使い方を想定している。fork したら `promote` の push 先は自分のリポになる

## 同僚として依頼し合う（peer-request）

プロジェクトごとのセッションが、`ListAgents`／`SendMessage` で別のプロジェクトのセッションへ直接頼み合う決まり。
連絡は `【依頼】`・`【確認】`・`【回答】`・`【完了】` の 4 種類で、依頼書と回覧台帳に残す。手順と禁止事項は `home/skills/peer-request/SKILL.md`。

- 置き場（社員名簿・回覧台帳・依頼書・起票の道具・`README.md`）は各自で用意し、その絶対パスを `settings.personal.json` の `env.CC_OFFICE_DIR` に入れる。**無いマシンでは skill は何もしない**
- 置き場の `README.md` が採番・台帳・状態の書式の正本。skill はそれを読んで従う

### 自分のフォルダの外へ書かない hook

`home/hooks/own_folder_guard.py`。`Edit`・`Write`・`NotebookEdit` の対象が自分のプロジェクトの外なら止める（Bash の書き込みは見ない。skill の決まりで禁止）。
hook は `settings.base.json` で全プロジェクトに登録してあるが、**効かせたプロジェクトでしか動かない。**

効かせ方（そのプロジェクトのセッションが行う）: `.claude/settings.local.json`（自分だけ・試しに）か `.claude/settings.json`（メンバー全員）に足す。

```json
{ "env": { "CC_OWN_FOLDER_GUARD": "1" } }
```

次に開いたセッションから効く。外すときはこの行を消すか `"0"` にする。

止めずに通す場所:

| 場所 | 決め方 |
|:--|:--|
| 自分のプロジェクト | `CLAUDE_PROJECT_DIR`（無ければ作業フォルダ） |
| `~/.claude/` と一時フォルダ（scratchpad を含む） | 固定 |
| 社内連絡の置き場 | `CC_OFFICE_DIR` |
| 全員が書く台帳など、ほかの例外 | `~/.claude/own-folder-allow.txt`（個人部。1 行 1 パス、`#` でコメント、`~` と `$変数` を展開。フォルダならその中すべて、`*` `?` `[` を含む行は glob） |

リンク経由も実体のパスで判定する。入力や設定が読めないときは止めない。`own-folder-allow.txt` 自体は、hook が効いているセッションからは書き換えられない（例外はユーザーが足す）。誤って書き換えるのを止める歯止めで、守りの境界ではない（Bash とプロジェクトの settings の書き換えは見ていない）。テストは `scripts/tests/test_own_folder_guard.py`。

## このリポを開発する

このリポ自体は project-skeleton から作った作業フォルダで、開発の決まりは `CLAUDE.md` と `.claude/` にある（`home/` の配布物とは別）。

- テスト: `python3 scripts/tests/run_tests.py`
- 公開前検査: `python3 scripts/check_public.py --history`
- 目的・現在地は `docs/プロジェクト概要.html`、設計は `docs/設計書/`、タスクは `docs/案件/01_タスク管理/`
- 一時ファイルは `.work/一時/YYYYMMDD_用途/`。秘密は `環境情報.md` と `.env` だけ（どちらも Git 管理外）

## ライセンス

MIT（`LICENSE`）。

---

作成: 2026-10-01 ／ project-skeleton v1.5.0
