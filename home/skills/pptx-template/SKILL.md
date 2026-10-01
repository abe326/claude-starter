---
name: pptx-template
description: 仕事用スライドの共通テンプレート（帯デザイン）。PowerPoint／pptx のスライド作成依頼、スライドの見た目の統一、この共通テンプレートの修正・ブラッシュアップ依頼で使う。pptx の作成前に必ず読む。
---

# 共通スライドテンプレート「帯」

仕事で使う PowerPoint の共通デザイン。派手にせず、白地・淡い青灰の一色・大きめの文字・1枚1メッセージ。
本体は `lib/template.js`（デザイン定義と部品）。`template.pptx`（サンプル入り）と `template.potx`（PowerPoint 用）はそこから生成する。

必要なもの: Node.js（初回はこのフォルダで `npm install`。claude-starter の install が自動で行う）と、pptx の生成手順を持つ `pptx` スキル（Anthropic 製。claude-starter には含めない。Claude Code の公式プラグインなどから入れる）。

## スライドを作るとき

pptx の生成そのもの（pptxgenjs の癖、検証、画像確認）は `pptx` スキルの手順に従う。見た目はこのテンプレートに揃える。

```js
const { createPresentation } = require(require('path').join(require('os').homedir(), '.claude/skills/pptx-template/lib/template.js'));
const { pres, cfg, text, box, arrow, vArrow, bullets, th, td, callout } = createPresentation();
// レイアウト: '表紙' '扉' '本文' '2カラム' '見出しのみ'
let s = pres.addSlide({ masterName: '表紙' });
s.addText('資料のタイトル', { placeholder: 'title' });     // 表紙: title / sub / date
s.addText('サブタイトル', { placeholder: 'sub' });
s = pres.addSlide({ masterName: '本文' });
s.addText('見出し', { placeholder: 'title' });               // 本文系: title / message / body（2カラムは left / right）
s.addText('このスライドの結論を一文で', { placeholder: 'message' });
s.addText(bullets(['要点1', '要点2']), { placeholder: 'body' });
s = pres.addSlide({ masterName: '見出しのみ' });            // 表・図解・自由配置用。本文は cfg.layout.bodyTop（1.2in）から
s.addTable([[th('列'), th('列')], [td('値', true), td('値')]], { x: 0.5, y: cfg.layout.bodyTop, w: 9, colW: [4.5, 4.5] });
box(s, 0.5, 2.5, 2.3, 1.0, [{ t: '箱', size: 14, bold: true }, { t: '補足', size: 11, color: cfg.colors.gray }]);
arrow(s, 2.9, 3.7, 3.0);
callout(s, 0.5, 4.0, 9, 1.0, '決めていただきたいこと', '本文');
await pres.writeFile({ fileName: '出力先.pptx' });
```

書き方の約束:
- 見出しは短く、`message` にそのスライドの結論を一文で書く。読み手は一文だけ読めば話が追える。
- 本文 14pt 以上、表 12pt 以上。10pt 以下は注記だけ。
- 色は `cfg.colors` の範囲で。強調は太字か淡い地色（tint／band）。赤（red）は「問題」を示すときだけ。
- 図は白い箱と細線（box／arrow）。塗るのは「変わる箇所」「注目してほしい箇所」だけ。
- 帯・線・アイコン・カード塗りなどの飾りを足さない。余白で区切る。
- 発表者ノートは `slide.addNotes()`。

## テンプレートの修正・ブラッシュアップ依頼を受けたとき

このテンプレートは全プロジェクト共通。どのセッションからでも次の手順で直してよい。

1. 依頼を `lib/template.js` の変更に落とす。色・文字サイズ・帯の高さ・余白は `CONFIG`、形は `defineMasters`、部品は `createPresentation` 内。
2. 守ること: レイアウト名（表紙・扉・本文・2カラム・見出しのみ）とプレースホルダー名（title／sub／date／no／message／body／left／right）は変えない。既存のデッキ生成コードが壊れる。
3. 守ること: デザインの原則（淡い一色、装飾なし、帯は文字とほぼ同じ高さ、本文 14pt 以上）を崩す依頼は、ユーザーに一言確認してから。
4. `bash ~/.claude/skills/pptx-template/build.sh` を実行する。生成、検証、`preview/` の画像作成まで行う。
5. `preview/slide-*.jpg` を目で確認する（帯の高さ、文字の折り返し、はみ出し）。
6. `CHANGELOG.md` に「日付 ／ 依頼元 ／ 変更 ／ 理由」を1行足す。
7. 依頼元のセッションに、変えたファイルと見た目の変化を報告する。プロジェクト内に古いコピーがあれば差し替えを勧める。

## ファイル

| ファイル | 役割 |
|:--|:--|
| `lib/template.js` | デザイン定義と部品。正本 |
| `build.js` | サンプル7枚入り `template.pptx` と、表紙1枚の `_base.pptx` を生成 |
| `make_potx.py` | `_base.pptx` を `template.potx` に変換 |
| `build.sh` | 生成・検証・プレビューを一括実行 |
| `template.pptx` | レイアウト5種＋サンプル7枚。見本 |
| `template.potx` | PowerPoint の「個人用テンプレート」に置くファイル |
| `preview/` | スライド画像と一覧 |
| `CHANGELOG.md` | 変更履歴 |

## PowerPoint で直接使う

`template.potx` を Windows の `ドキュメント\Office のカスタム テンプレート` にコピーすると「新規 → 個人用」に出る。
WSL 側の実体は `\\wsl.localhost\<ディストリ名>\home\<ユーザー名>\.claude\skills\pptx-template\template.potx`。
フォントは Meiryo。フッターの文言は「表示 → スライドマスター」で変える。
