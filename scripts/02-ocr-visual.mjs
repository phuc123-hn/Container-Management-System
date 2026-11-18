// Xuất ảnh kết quả OCR cho từng crop biển: ảnh gốc + ảnh 128x64 model thấy + chữ đọc được + đáp án
// -> result/02_ocr_visual/<tên>.png và result/02_ocr_visual/_tong_hop.png
import fs from 'node:fs';
import path from 'node:path';
import * as ort from 'onnxruntime-node';
import { createCanvas, loadImage } from '@napi-rs/canvas';
import { PlateReader } from '../src/plate-reader.js';
import { P, loadGT, keyOf, makeReport } from './_common.mjs';

const IN = process.argv[2] ?? P.crops;
const OUT = process.argv[3] ?? path.join(P.result, '02_ocr_visual');
const GT = loadGT();
const FONT = '"Segoe UI", Arial, "DejaVu Sans", sans-serif';
const C = { ok: '#16a34a', bad: '#dc2626', none: '#64748b', bg: '#0f172a', text: '#f8fafc', dim: '#94a3b8' };

const CARD_W = 520, IMG_H = 220, PANEL_H = 130, CARD_H = IMG_H + PANEL_H;

function card(img, model, r, gt) {
  const cv = createCanvas(CARD_W, CARD_H), g = cv.getContext('2d');
  g.fillStyle = C.bg; g.fillRect(0, 0, CARD_W, CARD_H);
  // ảnh crop gốc (giữ tỉ lệ) bên trái
  const maxW = 330, maxH = IMG_H - 20;
  const s = Math.min(maxW / img.width, maxH / img.height);
  const w = img.width * s, h = img.height * s;
  g.drawImage(img, 10, 10 + (maxH - h) / 2, w, h);
  // ảnh 128x64 mà model THỰC SỰ nhìn thấy (phóng 1.4x để dễ xem) bên phải
  g.imageSmoothingEnabled = false;
  g.drawImage(model, 360, 40, 150, 75);
  g.fillStyle = C.dim; g.font = `12px ${FONT}`;
  g.font = `11px ${FONT}`; g.fillText('Model nhìn thấy (128×64):', 360, 30);
  // kết quả
  const status = gt === undefined ? 'none' : gt === null ? 'none' : r.text === gt ? 'ok' : 'bad';
  const label = { ok: 'ĐÚNG', bad: 'SAI', none: gt === null ? 'BỎ QUA' : 'CHƯA CÓ ĐÁP ÁN' }[status];
  g.fillStyle = C[status]; g.fillRect(0, IMG_H, CARD_W, 6);
  g.fillStyle = C.dim; g.font = `13px ${FONT}`;
  g.fillText('OCR đọc được:', 12, IMG_H + 28);
  g.fillStyle = C.text; g.font = `bold 38px ${FONT}`;
  g.fillText(r.text || '(trống)', 12, IMG_H + 68);
  g.fillStyle = C[status]; g.font = `bold 20px ${FONT}`;
  g.fillText(label, 300, IMG_H + 62);
  g.fillStyle = C.dim; g.font = `13px ${FONT}`;
  g.fillText(`conf ${r.conf.toFixed(3)}`, 300, IMG_H + 28);
  g.fillText(gt ? `Đáp án: ${gt}` : 'Đáp án: —', 12, IMG_H + 92);
  // tô ký tự đáp án: xanh = model đọc đúng (căn theo LCS), đỏ = bị thiếu/đọc sai
  if (status === 'bad') {
    const a = gt, b = r.text, dp = Array.from({ length: a.length + 1 }, () => Array(b.length + 1).fill(0));
    for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const hit = new Set(); for (let i = 0, j = 0; i < a.length && j < b.length;) {
      if (a[i] === b[j]) { hit.add(i); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) i++; else j++; }
    let x = 12 + g.measureText('Đáp án: ').width;
    for (let i = 0; i < gt.length; i++) {
      g.fillStyle = hit.has(i) ? C.ok : C.bad;
      g.fillText(gt[i], x, IMG_H + 112); x += g.measureText(gt[i]).width + 1;
    }
    g.fillStyle = C.dim; g.fillText('đỏ = model đọc thiếu/sai ký tự này', x + 10, IMG_H + 112);
  }
  return { cv, status };
}

const rep = makeReport('02_ocr_visual.txt');
const reader = await PlateReader.create({
  ort, modelUrl: P.cctModel, createCanvas, sessionOptions: { executionProviders: ['cpu'] },
});
fs.mkdirSync(OUT, { recursive: true });
const files = fs.readdirSync(IN).filter((f) => /\.(png|jpe?g|webp)$/i.test(f)).sort();
const cards = []; let ok = 0, bad = 0;
for (const f of files) {
  const key = keyOf(f);
  const img = await loadImage(path.join(IN, f));
  const r = await reader.read(img);
  const model = createCanvas(128, 64); model.getContext('2d').drawImage(img, 0, 0, 128, 64); // cùng cách resize với reader
  const { cv, status } = card(img, model, r, GT[key]);
  fs.writeFileSync(path.join(OUT, `${key}.png`), cv.toBuffer('image/png'));
  cards.push(cv); if (status === 'ok') ok++; if (status === 'bad') bad++;
  rep.log(`${key.padEnd(22)} ${r.text.padEnd(11)} conf=${r.conf.toFixed(3)} ${status}`);
}
// ảnh tổng hợp: ưu tiên đưa các ảnh SAI lên đầu
const COLS = 3, rows = Math.ceil(cards.length / COLS), HEAD = 70;
const sheet = createCanvas(COLS * CARD_W + (COLS + 1) * 8, HEAD + rows * (CARD_H + 8) + 8), sg = sheet.getContext('2d');
sg.fillStyle = '#020617'; sg.fillRect(0, 0, sheet.width, sheet.height);
sg.fillStyle = C.text; sg.font = `bold 26px ${FONT}`;
sg.fillText(`Kết quả OCR — ${files.length} ảnh`, 16, 32);
sg.font = `16px ${FONT}`; sg.fillStyle = C.dim;
sg.fillText(`Đúng ${ok}  ·  Sai ${bad}  ·  Không tính điểm ${files.length - ok - bad}   (exact-match ${(ok / Math.max(1, ok + bad) * 100).toFixed(1)}%)`, 16, 58);
cards.forEach((cv, i) => sg.drawImage(cv, 8 + (i % COLS) * (CARD_W + 8), HEAD + Math.floor(i / COLS) * (CARD_H + 8)));
fs.writeFileSync(path.join(OUT, '_tong_hop.png'), sheet.toBuffer('image/png'));
rep.log(`\nĐã lưu ${files.length} ảnh + _tong_hop.png vào: ${OUT}`);
rep.log(`Đúng ${ok} · Sai ${bad} · exact-match ${(ok / Math.max(1, ok + bad) * 100).toFixed(1)}%`);
rep.save();
