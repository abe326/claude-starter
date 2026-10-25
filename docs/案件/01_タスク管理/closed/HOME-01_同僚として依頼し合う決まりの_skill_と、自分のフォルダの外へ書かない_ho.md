---
id: HOME-01
title: 同僚として依頼し合う決まりの skill と、自分のフォルダの外へ書かない hook を足す
area: 配布物(home/)
kind: タスク
status: 完了
priority: 高
epic: 
owner: 
due: 
tags: [依頼2026-10-25-03]
screens: []
source: 依頼 2026-10-25-03（AI 秘書のプロジェクトからの引き継ぎ）
created: 2026-10-25
updated: 2026-10-25
closed: 2026-10-25
---

## 概要
プロジェクトごとのセッションが同僚として直接頼み合う決まりを skill（`peer-request`）にし、自分のプロジェクトの外へ書かせない PreToolUse hook（`own_folder_guard.py`）を、プロジェクトごとに効かせる形で配る。

## 対応の意義（なぜやるか）
- 対応しないデメリット: プロジェクト間の依頼がユーザー経由の取り次ぎになり、文脈の写しと伝言が増える。直接頼めるようにしても、決まりと歯止めが無いと別のプロジェクトのファイルを直接書き換えたり、依頼が連鎖したりする
- 対応するメリット: 依頼元が確認事項に自分で答え、ユーザーには判断だけが上がる。書き込みは hook で自分のフォルダに限られる

## 対応後の変更点（利用者視点）
- 「〇〇に頼んで」と言うと、セッションが依頼書を起票して相手のセッションへ送り、確認・完了が依頼元に返る（`CC_OFFICE_DIR` を入れたマシンだけ）
- `CC_OWN_FOLDER_GUARD=1` を入れたプロジェクトでは、外への Edit・Write が止まり、依頼するよう案内が出る。入れていないプロジェクトは変わらない

## 対応計画の概要
- [x] skill `home/skills/peer-request/SKILL.md`（依頼を出す側・受ける側・確認が来た側・完了が来た側・台帳・禁止事項）
- [x] hook `home/hooks/own_folder_guard.py` と `settings.base.json` への登録（既定は何もしない）
- [x] テスト `scripts/tests/test_own_folder_guard.py`（27 件）
- [x] README・CHANGELOG
- [x] commit・push（2026-10-25 ユーザー承認。fd2ae9f）
- [x] 該当なし: 試しの 2 プロジェクトで効かせるのは、それぞれのセッションの作業（依頼元へ完了報告で伝えた）

## 対応計画の詳細
- 置き場は環境変数 `CC_OFFICE_DIR`。中の形（`README.md`・`社員名簿.md`・`回覧台帳.md`・`起票.sh`・依頼書）は置き場を作る側のプロジェクトと合わせた。skill は README を正本として読み、番号は `起票.sh` に取らせ、依頼書のパスは起票.sh の出力と台帳の「依頼書」列を使う（置き場の形が変わっても skill を直さずに済む）
- hook の効かせ方: `settings.base.json` に全体で登録し、プロジェクトの env（`.claude/settings.local.json` か `settings.json`）に `CC_OWN_FOLDER_GUARD=1` があるときだけ判定する。hook に env が渡らない場合に備えて、settings の env も直接読む
- 通す場所: 自分のプロジェクト（`CLAUDE_PROJECT_DIR`）・`~/.claude/`・一時フォルダ・`CC_OFFICE_DIR`・`~/.claude/own-folder-allow.txt`（個人部。全員が書く台帳など）
- 元にしたのは依頼元のプロジェクトにある guard hook（対象を固定の親フォルダの中に限っていた）。汎用にするため、自分のプロジェクトの外は既定で止め、通す場所を足す形にした

## 影響・依存
- `settings.base.json` を変えたので、次のセッション開始時の sync で全マシンの settings.json に PreToolUse が入る。env を入れていないプロジェクトでは即 exit 0
- 置き場の作成と `CC_OFFICE_DIR`・`own-folder-allow.txt` の値は、各マシンの個人部（このリポの外）
- 設計書 06（品質と確認）は未作成。Sketch の間は足さない

## 完了条件（クローズ3条件）
- [x] 対象環境へ適用済み（push 済み。各マシンは次のセッション開始の sync で入る）
- [x] 確認者の確認: hook のテスト 27 件と全テスト・公開前検査（`--history`）が通る
- [x] 該当なし: 正本への反映（README・CHANGELOG に反映済み。設計書は Sketch で未作成）

## 過去の経緯
- 2026-10-25 依頼元のプロジェクトで「案件セッション同士が同僚として依頼し合う」方式を相談し、推奨案（当事者どうしで直接＋共通の回覧台帳、確認は依頼元がまず答える）で進めると決定。skill と hook はこのリポ、置き場と全体の決まりは全体設定のプロジェクトに分担
- 置き場の形は、置き場を作るセッションと SendMessage で合わせた（採番は起票.sh、skill はパスを組み立てない）
- hook は「いきなり全プロジェクトで効かせない」ため、プロジェクトごとの env で効かせる形にした

## 参照情報
- `home/skills/peer-request/SKILL.md`・`home/hooks/own_folder_guard.py`・`scripts/tests/test_own_folder_guard.py`・README「同僚として依頼し合う（peer-request）」
