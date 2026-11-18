// Pipeline đầy đủ trên ẢNH TOÀN CẢNH: YOLO tìm biển -> cắt -> CCT-S đọc ký tự -> vẽ khung + chữ lên ảnh.
// -> result/03_pipeline/<ảnh>.jpg  và  result/03_pipeline.txt
//   node scripts/03-pipeline.mjs [thư_mục_ảnh] [thư_mục_ra] [ngưỡng_score=0.25]
// Nhãn khung thật (data/labels/*.txt, định dạng YOLO) và đáp án chữ chỉ để đối chiếu/chấm, không ảnh hưởng kết quả.
import fs from 'node:fs';
import path from 'node:path';
import * as ort from 'onnxruntime-node';
import { createCanvas, loadImage } from '@napi-rs/canvas';
import { PlateReader } from '../src/plate-reader.js';
import { P, loadGT, naturalSort, makeReport } from './_common.mjs';

const IN = process.argv[2] ?? P.frames;
const OUT = process.argv[3] ?? path.join(P.result, '03_pipeline');
const THR = Number(process.argv[4] ?? 0.25);
const S = 320, PAD_GRAY = '#727272';
const GT = loadGT();
const rep = makeReport('03_pipeline.txt');
const FONT = '"Segoe UI", Arial, "DejaVu Sans", sans-serif';

const det = await ort.InferenceSession.create(P.yoloModel, { executionProviders: ['cpu'] });
const reader = await PlateReader.create({
  ort, modelUrl: P.cctModel, createCanvas, sessionOptions: { executionProviders: ['cpu'] },
});

/** Letterbox 320 như alpr.js (nền #727272, RGB/255, NCHW) -> hộp trong toạ độ ảnh gốc. */
async function detect(img) {
  const w = img.width, h = img.height, sc = Math.min(S / w, S / h);
  const nw = Math.round(w * sc), nh = Math.round(h * sc), dx = (S - nw) / 2, dy = (S - nh) / 2;
  const cv = createCanvas(S, S), g = cv.getContext('2d');
  g.fillStyle = PAD_GRAY; g.fillRect(0, 0, S, S); g.drawImage(img, dx, dy, nw, nh);
  const d = g.getImageData(0, 0, S, S).data, arr = new Float32Array(3 * S * S);
  for (let i = 0, p = 0; i < d.length; i += 4, p++) {
    arr[p] = d[i] / 255; arr[p + S * S] = d[i + 1] / 255; arr[p + 2 * S * S] = d[i + 2] / 255;
  }
  const out = (await det.run({ [det.inputNames[0]]: new ort.Tensor('float32', arr, [1, 3, S, S]) }))[det.outputNames[0]];
  const boxes = [];
  for (let k = 0; k < out.dims[1]; k++) {
    const b = k * 6, score = out.data[b + 4];
    if (score < THR) continue;
    boxes.push({
      x1: Math.max(0, (out.data[b] - dx) / sc), y1: Math.max(0, (out.data[b + 1] - dy) / sc),
      x2: Math.min(w, (out.data[b + 2] - dx) / sc), y2: Math.min(h, (out.data[b + 3] - dy) / sc), score,
    });
  }
  return boxes.sort((a, b) => b.score - a.score);
}
const iou = (a, b) => {
  const iw = Math.max(0, Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1)), ih = Math.max(0, Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1));
  const i = iw * ih; return i / ((a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - i || 1);
};
function loadLabels(name, W, H) {
  const p = path.join(P.labels, name.replace(/\.[^.]+$/, '.txt'));
  if (!fs.existsSync(p)) return null;
  return fs.readFileSync(p, 'utf8').trim().split(/\r?\n/).filter(Boolean).map((l) => {
    const [, cx, cy, w, h] = l.trim().split(/\s+/).map(Number);
    return { x1: (cx - w / 2) * W, y1: (cy - h / 2) * H, x2: (cx + w / 2) * W, y2: (cy + h / 2) * H };
  });
}
function nUncertain(name) { // số biển bạn đã đánh dấu "không chắc" (null) trong ảnh này
  const pre = name.replace(/\.[^.]+$/, '').replaceAll('.', '_') + '__';
  return Object.entries(GT).filter(([k, v]) => k.startsWith(pre) && v == null).length;
}
function gtTexts(name) { // mọi biển đáp án thuộc ảnh này, từ ground_truth.json (key: clip3_2_new_N__k)
  const pre = name.replace(/\.[^.]+$/, '').replaceAll('.', '_') + '__';
  return Object.entries(GT).filter(([k, v]) => k.startsWith(pre) && v).map(([, v]) => v);
}

fs.mkdirSync(OUT, { recursive: true });
const files = fs.readdirSync(IN).filter((f) => /\.(jpe?g|png|webp)$/i.test(f)).sort(naturalSort);
// 'keep' = giữ mọi box; 'reject' = bỏ box chạm mép ảnh (edgePolicy mặc định của bạn)
const K = { tp: 0, fp: 0, fn: 0 }, R_ = { tp: 0, fp: 0, fn: 0 };
let ocrOk = 0, ocrBad = 0, nEdge = 0, nStray = 0, nUnk = 0;
const rows = [];
for (const f of files) {
  const img = await loadImage(path.join(IN, f)), W = img.width, H = img.height;
  const t0 = performance.now();
  const boxes = await detect(img);
  const labels = loadLabels(f, W, H);
  const answers = gtTexts(f);
  const cv = createCanvas(W, H), g = cv.getContext('2d');
  g.drawImage(img, 0, 0);
  const lw = Math.max(3, W / 500), fs1 = Math.round(W / 55);

  if (labels) { // khung thật: nét đứt xanh dương, mỏng
    g.setLineDash([lw * 3, lw * 2]); g.lineWidth = lw * 0.7; g.strokeStyle = '#38bdf8';
    for (const l of labels) g.strokeRect(l.x1, l.y1, l.x2 - l.x1, l.y2 - l.y1);
    g.setLineDash([]);
  }
  const matchedK = new Set(), matchedR = new Set();
  const M = 4; // box chạm mép ảnh (<= M px) = biển bị cắt
  for (const b of boxes) {
    const bw = b.x2 - b.x1, bh = b.y2 - b.y1;
    const edge = b.x1 <= M || b.y1 <= M || b.x2 >= W - M || b.y2 >= H - M;
    const px = Math.max(8, bw * 0.07), py = Math.max(6, bh * 0.12);
    const cx1 = Math.max(0, Math.round(b.x1 - px)), cy1 = Math.max(0, Math.round(b.y1 - py));
    const cx2 = Math.min(W, Math.round(b.x2 + px)), cy2 = Math.min(H, Math.round(b.y2 + py));
    const crop = createCanvas(cx2 - cx1, cy2 - cy1);
    crop.getContext('2d').drawImage(img, cx1, cy1, cx2 - cx1, cy2 - cy1, 0, 0, cx2 - cx1, cy2 - cy1);
    const r = await reader.read(crop);
    let hit = -1;
    if (labels) {
      hit = labels.findIndex((l, i) => !matchedK.has(i) && iou(b, l) >= 0.5);
      if (hit >= 0) { matchedK.add(hit); K.tp++; if (!edge) { matchedR.add(hit); R_.tp++; } } else { K.fp++; if (!edge) R_.fp++; }
    }
    // phân loại để vẽ + tính điểm OCR (chỉ tính box KHÔNG chạm mép và khớp một biển trong nhãn)
    let kind, col;
    if (edge) { kind = 'edge'; col = '#94a3b8'; nEdge++; }
    else if (labels && hit < 0) { kind = 'stray'; col = '#f59e0b'; nStray++; }
    else if (answers.includes(r.text)) { kind = 'ok'; col = '#22c55e'; ocrOk++; }
    else if (nUncertain(f) > 0) { kind = 'unk'; col = '#a78bfa'; nUnk++; }   // biển loá sáng, chưa có đáp án -> không tính
    else { kind = 'bad'; col = '#ef4444'; ocrBad++; }
    g.lineWidth = lw; g.strokeStyle = col; if (edge) g.setLineDash([lw * 2, lw * 2]);
    g.strokeRect(b.x1, b.y1, bw, bh); g.setLineDash([]);
    const tag = { ok: '', bad: '', edge: 'MÉP-bỏ · ', stray: '? · ', unk: 'CHƯA CÓ ĐÁP ÁN · ' }[kind];
    const label = `${tag}${r.text || '(trống)'}  ${(r.conf * 100).toFixed(0)}%  · box ${(b.score * 100).toFixed(0)}%`;
    g.font = `bold ${fs1}px ${FONT}`;
    const tw = g.measureText(label).width + 16, th = fs1 + 12;
    const lx = Math.min(Math.max(0, b.x1), W - tw), ly = b.y1 - th > 0 ? b.y1 - th : b.y2;
    g.fillStyle = col; g.fillRect(lx, ly, tw, th);
    g.fillStyle = '#04130a'; g.fillText(label, lx + 8, ly + fs1);
    rows.push({ f, text: r.text, kind });
  }
  if (labels) { K.fn += labels.length - matchedK.size; R_.fn += labels.length - matchedR.size; }
  // chú thích góc trái trên
  g.font = `bold ${fs1}px ${FONT}`; g.fillStyle = 'rgba(2,6,23,.75)'; g.fillRect(0, 0, W * 0.62, fs1 + 20);
  g.fillStyle = '#f8fafc';
  g.fillText(`${f} — ${boxes.length} biển (đáp án: ${labels ? labels.length : '?'})  ${(performance.now() - t0).toFixed(0)}ms`, 10, fs1 + 4);
  fs.writeFileSync(path.join(OUT, f.replace(/\.[^.]+$/, '.jpg')), cv.toBuffer('image/jpeg', 88));
  rep.log(`${f.padEnd(22)} tìm ${boxes.length}/${labels ? labels.length : '?'} biển | ` +
    rows.filter((r) => r.f === f).map((r) => `${r.text}${{ ok: '✅', bad: '❌', edge: '(mép)', stray: '(?)', unk: '(chưa có đáp án)' }[r.kind]}`).join('  '));
}
const pr = (m) => `TP ${m.tp} · FP ${m.fp} · FN ${m.fn} | precision ${(m.tp / Math.max(1, m.tp + m.fp) * 100).toFixed(1)}% · recall ${(m.tp / Math.max(1, m.tp + m.fn) * 100).toFixed(1)}%`;
rep.log(`\n== TÌM BIỂN (YOLO, ngưỡng ${THR}, IoU≥0.5)`);
rep.log(`   giữ mọi box      : ${pr(K)}`);
rep.log(`   bỏ box chạm mép  : ${pr(R_)}   <- edgePolicy='reject'`);
rep.log(`== ĐỌC BIỂN (OCR, chỉ tính box không chạm mép & khớp nhãn): đúng ${ocrOk} · sai ${ocrBad} | ${(ocrOk / Math.max(1, ocrOk + ocrBad) * 100).toFixed(1)}%`);
rep.log(`   (không tính: ${nEdge} box chạm mép, ${nUnk} biển loá sáng chưa có đáp án, ${nStray} box không khớp nhãn nào)`);
rep.log(`Ảnh đã lưu vào: ${OUT}`);
rep.save();
