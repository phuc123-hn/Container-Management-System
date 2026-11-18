// Test OCR (CCT-S v2) trên 36 crop biển số -> result/01_test_ocr.txt
// Dùng ĐÚNG src/plate-reader.js. Đáp án (data/ground_truth.json) chỉ để chấm điểm, không ảnh hưởng chữ đọc ra.
import fs from 'node:fs';
import path from 'node:path';
import * as ort from 'onnxruntime-node';
import { createCanvas, loadImage } from '@napi-rs/canvas';
import { PlateReader } from '../src/plate-reader.js';
import { P, loadGT, keyOf, makeReport } from './_common.mjs';

const rep = makeReport('01_test_ocr.txt');
const GT = loadGT();
const reader = await PlateReader.create({
  ort, modelUrl: P.cctModel, createCanvas, sessionOptions: { executionProviders: ['cpu'] },
});

const files = fs.readdirSync(P.crops).filter((f) => /\.(png|jpe?g)$/i.test(f)).sort();
let exact = 0, scored = 0, charOk = 0, charTot = 0;
const t0 = performance.now();
for (const f of files) {
  const key = keyOf(f), gt = GT[key];
  const { text, conf } = await reader.read(await loadImage(path.join(P.crops, f)));
  const mark = gt === undefined ? '?' : gt == null ? '—' : text === gt ? 'ĐÚNG' : 'SAI ';
  rep.log(`${key.padEnd(22)} đáp án=${String(gt ?? '(không chắc)').padEnd(12)} đọc được=${text.padEnd(11)} conf=${conf.toFixed(3)}  ${mark}`);
  if (gt) {
    scored++; if (text === gt) exact++;
    charTot += Math.max(gt.length, text.length);
    for (let i = 0; i < Math.min(gt.length, text.length); i++) if (gt[i] === text[i]) charOk++;
  }
}
const ms = performance.now() - t0;
rep.log('');
rep.log(`Exact-match   : ${exact}/${scored} = ${(exact / scored * 100).toFixed(1)}%`);
rep.log(`Character-acc : ${charOk}/${charTot} = ${(charOk / charTot * 100).toFixed(1)}%`);
rep.log(`Thời gian     : ${ms.toFixed(0)}ms cho ${files.length} ảnh (~${(ms / files.length).toFixed(1)}ms/ảnh, gồm decode)`);
rep.save();
