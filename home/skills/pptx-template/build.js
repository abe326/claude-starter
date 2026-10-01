'use strict';
// template.pptx（レイアウト＋サンプル7枚）と _base.pptx（レイアウト＋表紙1枚、.potx の元）を生成する
const path = require('path');
const { createPresentation } = require('./lib/template.js');
const HERE = __dirname;

function samples() {
  const { pres, cfg, text, box, arrow, bullets, th, td, callout } = createPresentation();
  const C = cfg.colors, L = cfg.layout;
  { const s = pres.addSlide({ masterName: '表紙' });
    s.addText('業務システム刷新プロジェクト 進捗報告', { placeholder: 'title' });
    s.addText('2026年9月 定例', { placeholder: 'sub' });
    s.addText('2026-09-06 ／ 開発チーム', { placeholder: 'date' }); }
  { const s = pres.addSlide({ masterName: '扉' });
    s.addText('1', { placeholder: 'no' }); s.addText('現状の整理', { placeholder: 'title' }); }
  { const s = pres.addSlide({ masterName: '本文' });
    s.addText('現状の整理', { placeholder: 'title' });
    s.addText('3つの業務のうち、受注と請求は移行済み。在庫だけ旧システムが残る', { placeholder: 'message' });
    s.addText(bullets(['受注: 7月に移行完了。問い合わせは週1件以下', '請求: 8月に移行完了。締め処理は新旧並行で確認中', '在庫: 旧システムのまま。連携仕様の確認に時間を要している', '全体: 利用部門からの評価は良好。教育は9月中に完了予定']), { placeholder: 'body' }); }
  { const s = pres.addSlide({ masterName: '2カラム' });
    s.addText('在庫移行の論点', { placeholder: 'title' });
    s.addText('連携仕様を先に確定すれば、10月中の移行は可能', { placeholder: 'message' });
    s.addText([{ text: '課題', options: { bold: true, color: C.accent, breakLine: true } }, ...bullets(['倉庫システムとの連携仕様が未確定', '月末の棚卸と移行日が重なる', '旧データの重複が約2%'])], { placeholder: 'left' });
    s.addText([{ text: '対応案', options: { bold: true, color: C.accent, breakLine: true } }, ...bullets(['9/20 までに仕様を確定（倉庫側と合同で）', '移行日を棚卸の翌週に設定', '重複は移行前に一括で名寄せ'])], { placeholder: 'right' }); }
  { const s = pres.addSlide({ masterName: '見出しのみ' });
    s.addText('スケジュール', { placeholder: 'title' });
    s.addText('在庫移行は10月に前倒し。11月に全体テスト', { placeholder: 'message' });
    s.addTable([
      [th('項目'), th('9月'), th('10月'), th('11月'), th('担当')],
      [td('連携仕様の確定', true), td('9/20 確定'), td(''), td(''), td('開発・倉庫')],
      [td('データ名寄せ', true), td('着手'), td('完了'), td(''), td('開発')],
      [td('在庫の移行', true), td(''), td('10/22 実施'), td(''), td('開発・業務')],
      [td('全体テスト', true), td(''), td(''), td('2週間'), td('全員')],
      [td('教育', true), td('完了'), td(''), td('補講'), td('業務')],
    ], { x: 0.5, y: L.bodyTop, w: 9.0, colW: [2.2, 1.6, 1.6, 1.6, 2.0], rowH: [0.4, 0.45, 0.45, 0.45, 0.45, 0.45], margin: [3, 8, 3, 8] }); }
  { const s = pres.addSlide({ masterName: '見出しのみ' });
    s.addText('移行の流れ', { placeholder: 'title' });
    s.addText('移行は3段階。各段階の終わりに業務側が確認する', { placeholder: 'message' });
    const y = 1.6, h = 1.1, w = 2.3;
    box(s, 0.5, y, w, h, [{ t: '現行システム', size: 14, bold: true }, { t: '受注・請求・在庫', size: 11, color: C.gray }]);
    arrow(s, 2.85, 3.75, y + h / 2); text(s, '抽出', 2.85, y + h / 2 - 0.32, 0.9, 0.25, { size: 10, color: C.gray, align: 'center' });
    box(s, 3.8, y, w, h, [{ t: 'データ移行', size: 14, bold: true }, { t: '名寄せ・変換・検証', size: 11, color: C.gray }], { fill: C.band, border: C.accent });
    arrow(s, 6.15, 7.05, y + h / 2); text(s, '投入', 6.15, y + h / 2 - 0.32, 0.9, 0.25, { size: 10, color: C.gray, align: 'center' });
    box(s, 7.1, y, w, h, [{ t: '新システム', size: 14, bold: true }, { t: '10/22 切替', size: 11, color: C.gray }]);
    [0.5, 3.8, 7.1].forEach((x, i) => {
      s.addShape(pres.ShapeType.line, { x: x + w / 2, y: y + h, w: 0, h: 0.4, line: { color: C.line, width: 1, endArrowType: 'triangle' } });
      box(s, x, y + h + 0.4, w, 0.6, [{ t: ['業務側の確認 ①', '業務側の確認 ②', '業務側の確認 ③'][i], size: 11, color: C.accent }], { border: C.line, dash: true });
    });
    text(s, '確認①: 抽出件数の突合　確認②: 変換後のサンプル照合　確認③: 切替後1週間の並行運用', 0.5, 4.2, 9, 0.3, { size: 10.5, color: C.gray }); }
  { const s = pres.addSlide({ masterName: '本文' });
    s.addText('次のアクション', { placeholder: 'title' });
    s.addText('来週までに3件。決めていただきたいことが1件', { placeholder: 'message' });
    s.addText(bullets(['連携仕様の確定会議を 9/12 に設定（開発・倉庫）', '名寄せルールの案を 9/15 までに業務側へ提示', '教育の補講日程を 9/19 までに確定'], { number: true }), { x: 0.5, y: L.bodyTop, w: 9.0, h: 1.5, placeholder: 'body' });
    callout(s, 0.5, 3.1, 9.0, 1.1, '決めていただきたいこと', '在庫の移行日を 10/15 と 10/22 のどちらにするか。棚卸との重なりを避けるなら 10/22 を推奨。'); }
  return pres.writeFile({ fileName: path.join(HERE, 'template.pptx') });
}
function base() {
  const { pres } = createPresentation();
  const s = pres.addSlide({ masterName: '表紙' });
  s.addText('資料のタイトル', { placeholder: 'title' });
  s.addText('サブタイトル', { placeholder: 'sub' });
  s.addText('日付 ／ 発表者', { placeholder: 'date' });
  return pres.writeFile({ fileName: path.join(HERE, '_base.pptx') });
}
(async () => { await samples(); await base(); console.log('built template.pptx / _base.pptx'); })();
