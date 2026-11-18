// Phần dùng chung cho mọi script: đường dẫn, đáp án, ghi báo cáo UTF-8 vào result/.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const P = {
  cctModel: path.join(ROOT, 'models', 'cct_s_v2_global.onnx'),
  yoloModel: path.join(ROOT, 'models', 'plate_yolo.onnx'),
  crops: path.join(ROOT, 'data', 'ocr_crops'),
  frames: path.join(ROOT, 'data', 'frames'),
  labels: path.join(ROOT, 'data', 'labels'),
  gt: path.join(ROOT, 'data', 'ground_truth.json'),
  result: path.join(ROOT, 'result'),
};

/** Đáp án: { 'clip3_2_new_0__0': '75H135792', ..., 'clip3_2_new_16__1': null (không chắc) } */
export const loadGT = () => (fs.existsSync(P.gt) ? JSON.parse(fs.readFileSync(P.gt, 'utf8')) : {});
/** 'clip3.2_new_0__0.png' -> 'clip3_2_new_0__0' */
export const keyOf = (filename) => filename.replace(/\.[^.]+$/, '').replaceAll('.', '_');

/** In ra màn hình VÀ gom lại để ghi file UTF-8 (không phụ thuộc mã hoá của PowerShell). */
export function makeReport(fileName) {
  const lines = [];
  fs.mkdirSync(P.result, { recursive: true });
  return {
    log(s = '') { console.log(s); lines.push(s); },
    save() {
      const out = path.join(P.result, fileName);
      fs.writeFileSync(out, lines.join('\n') + '\n', 'utf8');
      console.log(`\n>> Đã ghi: ${out}`);
    },
  };
}

export const naturalSort = (a, b) => a.localeCompare(b, undefined, { numeric: true });
