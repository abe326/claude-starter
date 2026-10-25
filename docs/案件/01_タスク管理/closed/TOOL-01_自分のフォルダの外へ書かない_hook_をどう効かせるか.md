---
id: TOOL-01
title: 自分のフォルダの外へ書かない hook をどう効かせるか
area: install・検査・hook
kind: 課題
status: 完了
priority: 中
decider: 
epic: 
owner: 
due: 
tags: []
screens: []
source: 
created: 2026-10-25
updated: 2026-10-25
closed: 2026-10-25
---

## 概要
（何を決める必要があるか。1〜3 行。決まらないと何が止まるか）

## 論点
- …

## 選択肢
- 案A: …
- 案B: …
- 推奨: （あれば。理由 1 行）

## 決着条件
（誰が・何をもって決着とするか。frontmatter の decider / due と食い違わせない）

## 決定
settings.base.json に全体で登録し、プロジェクトの env に CC_OWN_FOLDER_GUARD=1 があるときだけ判定する（既定は何もしない）。例外は CC_OFFICE_DIR と ~/.claude/own-folder-allow.txt。skill は置き場の README を正本とし、番号は起票.sh に取らせる
→ 反映済: README「自分のフォルダの外へ書かない hook」
→ HOME-01

## 過去の経緯
（これまでの打合せ・決定の変遷）

## 参照情報
（打合せ出典・設計書・関連タスク ID・関連画面 ID）
