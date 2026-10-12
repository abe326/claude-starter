# Changelog

このプロジェクトの変更履歴。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に従う。
節は Added / Changed / Deprecated / Removed / Fixed / Security。

## [Unreleased]

### Added

- `home/rules/environment-independent.md`: プロジェクトに機名・LAN の値・ホームの絶対パスを書かず、役割の名前と環境変数の名前で書く決まり
- `scripts/check_public.py`: 任意のプロジェクトのフォルダを引数に取れる。外すパスは `--exclude` と対象直下の `.public-exclude`（既定の動きは変わらない）

### Changed

- `home/CLAUDE.md` から新しい rules を指す

### Fixed

## [0.1.0] - 2026-10-01

### Added

- project-skeleton v1.5.0 から初版を生成
- 配布物 `home/`: 汎用の CLAUDE.md、rules（モデルの使い分け・安全・シェルの落とし穴）、skills（smart-orchestrator・pptx-template・promote）、settings.base.json、status line
- `scripts/starter.py`: install（リンク・ジャンクション・退避・settings の合成）、sync（SessionStart）、cue（Stop で候補を記録）、candidates
- `scripts/check_public.py`: 公開前検査（形式と個人語リスト、`--history`）、CI（形式検査・単体テスト・gitleaks）
