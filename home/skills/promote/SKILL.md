---
name: promote
description: プロジェクトで直した skill・rules・agents・CLAUDE.md のうち、他のプロジェクトでも使えるものを claude-starter（~/.claude/starter）に取り込み、検査して公開まで進める。「共通化して」「グローバルに寄せて」「starter に入れて」「promote して」、SessionStart や Stop に「claude-starter: 共通化の候補 N 件」が出て利用者が取り込みを了承したとき、利用者が「これ他でも使いたい」と言ったときに使う。
---

# promote — プロジェクトの改善を claude-starter に寄せる

claude-starter のリポ（`~/.claude/starter`）は、全マシンの `~/.claude` の汎用部の正本で、GitHub に公開している。
ここに入れたものは、リンク・同期・`git pull` で各マシンに自動で入り、公開もされる。**だから個人の事情は入れない。**

## 1. 候補を見る

```bash
python3 ~/.claude/starter/scripts/starter.py candidates
```

Stop hook が、作業中のプロジェクトで変わった `.claude/skills`・`.claude/rules`・`.claude/agents`・`CLAUDE.md` を記録している。
利用者が具体的なファイルを指したときは、候補に無くてもそれを扱う。

## 2. 振り分けを推奨付きで出す（決めるのは利用者）

候補ごとにプロジェクト側のファイルを読み、次のどれにするかを表で提案する。**取り込みは利用者の承認を得てから。**

| 振り分け | 当てはまるもの | 行き先 |
|---|---|---|
| 取り込み | どのプロジェクトでも役に立つ手順・決まり・つまずきの回避 | `~/.claude/starter/home/`（skills/・rules/・CLAUDE.md） |
| 個人 | 自分の環境・マシン・案件・通知先に依存するが、全プロジェクトで効かせたい | `~/.claude/CLAUDE.personal.md`（公開しない） |
| スケルトン | 由来が `skeleton`（project-skeleton が配ったファイル）の改善 | project-skeleton へ返す（案件の `docs/ハーネス台帳.md` の「返す」列） |
| 却下 | そのプロジェクトだけのもの | 何もしない |

一部だけ汎用なら、汎用の部分だけ取り込む。

## 3. 汎用の形に書き直して入れる

- 案件名・社名・人名・マシン名・IP・絶対パス・日付つきの経緯を抜き、「なぜそうするか」を一般論で書く
- 既存の skill・rules と重なるなら新しく作らず、そこへ足す。rules は 1 テーマ 1 ファイル
- skill を足すときは `home/skills/<名前>/SKILL.md`（frontmatter に name・description）。`allowed-tools` は書かない
- settings を変えたいときは `home/settings.base.json`（個人の値は `~/.claude/settings.personal.json`）
- `.claude/agents/` 由来の定義を入れるなら frontmatter に `model` を必ず書く

## 4. 検査して公開する

```bash
cd ~/.claude/starter
python3 scripts/check_public.py            # 個人語リスト ~/.claude/public-denylist.txt も見る
python3 scripts/tests/run_tests.py
```

- NG が出たら直す。個人語リストに足すべき語が見つかったら `~/.claude/public-denylist.txt` に足す
- 通ったら `git add` → `git commit`（メッセージにも個人の事情を書かない）→ `git push`。push まで進めてよい（このスキルを使った時点で利用者は公開を了承している）。押せない環境なら commit までで止め、その旨を伝える
- 自動で各マシンに入る: リンクのマシンは即時、clone のマシンは次のセッションの `git pull`。新しい skill は次のセッションから見える

## 5. 候補を閉じて報告する

```bash
python3 ~/.claude/starter/scripts/starter.py candidates --close <ID> --as 取り込み|個人|スケルトン|却下 [--note "…"]
```

報告は 3 行程度: 何を取り込み（どのファイルへ）、何を個人・スケルトン・却下にしたか、push したか。
