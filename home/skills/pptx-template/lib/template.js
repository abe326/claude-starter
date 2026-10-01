'use strict';
// 仕事用スライド共通テンプレート「帯」。他のセッションからは
//   const { createPresentation } = require(require('path').join(require('os').homedir(), '.claude/skills/pptx-template/lib/template.js'));
// で読み込む。デザインの変更は CONFIG とマスター定義（defineMasters）だけを触る。
const path = require('path');
const pptxgen = require(path.join(__dirname, '..', 'node_modules', 'pptxgenjs'));

const CONFIG = {
  font: 'Meiryo',
  colors: { band:'E3EAF1', accent:'4F6D8A', title:'2F3E4E', text:'333333', gray:'777777', line:'C8D2DC', tint:'F4F7FA', white:'FFFFFF', red:'B03A2E' },
  size: { title:18, message:14, body:14, coverTitle:30, coverSub:15, sectionTitle:26, sectionNo:28, footer:9 },
  layout: { bandHeight:0.45, bodyTop:1.2, bodyHeight:3.8, margin:0.5 },
  footerText: '資料名（スライドマスターで変更）',
};
const LAYOUTS = ['表紙', '扉', '本文', '2カラム', '見出しのみ'];

function mergeConfig(over = {}) {
  return {
    ...CONFIG, ...over,
    colors: { ...CONFIG.colors, ...(over.colors || {}) },
    size: { ...CONFIG.size, ...(over.size || {}) },
    layout: { ...CONFIG.layout, ...(over.layout || {}) },
  };
}

function defineMasters(pres, cfg) {
  const F = cfg.font, C = cfg.colors, S = cfg.size, L = cfg.layout;
  const ph = (name, type, o, text) => ({ placeholder: { options: Object.assign({ name, type, fontFace: F, margin: 0, align: 'left' }, o), text } });
  const rect = (x, y, w, h, fill) => ({ rect: { x, y, w, h, fill: { color: fill }, line: { color: fill, width: 0 } } });
  const hline = (x, y, w, color, pt) => ({ line: { x, y, w, h: 0, line: { color, width: pt } } });
  const stext = (t, x, y, w, h, o) => ({ text: { text: t, options: Object.assign({ x, y, w, h, fontFace: F, margin: 0 }, o) } });
  const num = { x: 9.1, y: 5.2, w: 0.4, h: 0.25, fontFace: F, fontSize: S.footer, color: C.gray, align: 'right' };
  const footer = stext(cfg.footerText, L.margin, 5.2, 5, 0.25, { fontSize: S.footer, color: C.gray });

  // 表紙: 白地、タイトルの上下に細い線、左端だけ濃い短線
  pres.defineSlideMaster({ title: '表紙', background: { color: C.white }, objects: [
    hline(0.8, 1.55, 8.4, C.line, 0.75), hline(0.8, 1.55, 1.2, C.accent, 2),
    ph('title', 'ctrTitle', { x: 0.8, y: 1.7, w: 8.4, h: 0.9, fontSize: S.coverTitle, bold: true, color: C.title, valign: 'middle' }, '資料のタイトル'),
    ph('sub', 'subTitle', { x: 0.8, y: 2.65, w: 8.4, h: 0.5, fontSize: S.coverSub, color: C.accent, valign: 'top' }, 'サブタイトル'),
    hline(0.8, 3.35, 8.4, C.line, 0.75),
    ph('date', 'body', { x: 0.8, y: 4.4, w: 8.4, h: 0.35, fontSize: 12, color: C.gray, valign: 'middle' }, '日付 ／ 発表者'),
  ] });
  // 扉: 左に淡い帯、番号と章名
  pres.defineSlideMaster({ title: '扉', background: { color: C.white }, objects: [
    rect(0, 0, 2.2, 5.625, C.band),
    ph('no', 'body', { x: 0.5, y: 2.2, w: 1.4, h: 0.8, fontSize: S.sectionNo, bold: true, color: C.accent, valign: 'middle' }, '1'),
    ph('title', 'title', { x: 2.7, y: 2.2, w: 6.8, h: 0.8, fontSize: S.sectionTitle, bold: true, color: C.title, valign: 'middle' }, 'セクション名'),
  ], slideNumber: num });
  // 本文系: 上端に細い帯（文字とほぼ同じ高さ）
  const head = [ rect(0, 0, 10, L.bandHeight, C.band),
    ph('title', 'title', { x: L.margin, y: 0.03, w: 10 - L.margin * 2, h: L.bandHeight - 0.06, fontSize: S.title, bold: true, color: C.title, valign: 'middle' }, '見出し'),
    ph('message', 'subTitle', { x: L.margin, y: L.bandHeight + 0.17, w: 10 - L.margin * 2, h: 0.42, fontSize: S.message, color: C.accent, valign: 'middle' }, 'このスライドで伝えたいことを一文で') ];
  const W = 10 - L.margin * 2, colW = (W - 0.3) / 2;
  const bodyOpt = { y: L.bodyTop, h: L.bodyHeight, fontSize: S.body, color: C.text, valign: 'top', paraSpaceAfter: 8 };
  pres.defineSlideMaster({ title: '本文', background: { color: C.white }, objects: [ ...head,
    ph('body', 'body', { x: L.margin, w: W, ...bodyOpt }, '本文'), footer ], slideNumber: num });
  pres.defineSlideMaster({ title: '2カラム', background: { color: C.white }, objects: [ ...head,
    ph('left', 'body', { x: L.margin, w: colW, ...bodyOpt }, '左の本文'),
    ph('right', 'body', { x: L.margin + colW + 0.3, w: colW, ...bodyOpt }, '右の本文'), footer ], slideNumber: num });
  pres.defineSlideMaster({ title: '見出しのみ', background: { color: C.white }, objects: [ ...head, footer ], slideNumber: num });
}

function createPresentation(overrides = {}) {
  const cfg = mergeConfig(overrides);
  const F = cfg.font, C = cfg.colors, S = cfg.size, L = cfg.layout;
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9';
  defineMasters(pres, cfg);

  // ── 部品 ──
  const text = (s, str, x, y, w, h, o = {}) => s.addText(str, Object.assign({ x, y, w, h, fontFace: F, fontSize: o.size || 12, bold: !!o.bold, color: o.color || C.text, align: o.align || 'left', valign: o.valign || 'top', margin: 0 }, o.extra || {}));
  const box = (s, x, y, w, h, lines, o = {}) => {
    s.addShape(pres.ShapeType.rect, { x, y, w, h, fill: { color: o.fill || C.white }, line: { color: o.border || C.line, width: o.bw || 0.75, dashType: o.dash ? 'dash' : 'solid' } });
    const runs = (Array.isArray(lines) ? lines : [{ t: lines }]).map((l, i, a) => ({ text: l.t, options: { fontFace: F, fontSize: l.size || 12, bold: !!l.bold, color: l.color || C.text, breakLine: i < a.length - 1 } }));
    s.addText(runs, { x: x + 0.1, y, w: w - 0.2, h, margin: 0, valign: 'middle', align: o.align || 'center', paraSpaceAfter: 2 });
  };
  const arrow = (s, x1, x2, y, o = {}) => s.addShape(pres.ShapeType.line, { x: x1, y, w: x2 - x1, h: 0, line: { color: o.color || C.accent, width: o.width || 1.25, endArrowType: 'triangle', dashType: o.dash ? 'dash' : 'solid' } });
  const vArrow = (s, x, y1, y2, o = {}) => s.addShape(pres.ShapeType.line, { x, y: y1, w: 0, h: y2 - y1, line: { color: o.color || C.line, width: o.width || 1, endArrowType: 'triangle' } });
  const bullets = (items, o = {}) => items.map((t, i) => ({ text: t, options: Object.assign({ bullet: o.number ? { type: 'number' } : true, breakLine: i < items.length - 1 }, o.opt || {}) }));
  const th = (t) => ({ text: t, options: { fontFace: F, fontSize: 12, bold: true, color: C.title, fill: { color: C.tint }, border: [{ type: 'none' }, { type: 'none' }, { type: 'solid', color: C.line, pt: 1 }, { type: 'none' }], valign: 'middle' } });
  const td = (t, b = false, o = {}) => ({ text: t, options: Object.assign({ fontFace: F, fontSize: 12, bold: b, color: C.text, fill: { color: C.white }, border: [{ type: 'none' }, { type: 'none' }, { type: 'solid', color: C.line, pt: 0.5 }, { type: 'none' }], valign: 'middle' }, o) });
  const callout = (s, x, y, w, h, title, body) => {
    s.addShape(pres.ShapeType.rect, { x, y, w, h, fill: { color: C.tint }, line: { color: C.tint, width: 0 } });
    text(s, title, x + 0.25, y + 0.12, w - 0.5, 0.3, { size: 11, bold: true, color: C.accent });
    text(s, body, x + 0.25, y + 0.45, w - 0.5, h - 0.55, { size: 13 });
  };
  return { pres, cfg, LAYOUTS, text, box, arrow, vArrow, bullets, th, td, callout };
}

module.exports = { createPresentation, CONFIG, LAYOUTS };
