// Kiểm tra logic mã container ISO 6346 (src/container-code.js) -> result/05_container_check.txt
// Phần này KHÔNG cần model: nó là lớp "kiểm tra và quyết định" đặt sau bước OCR chữ.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, makeReport } from './_common.mjs';
import { checkDigit, isValid, recover, vote, suggestRepairs, normalizeType, isValidType, decodeType } from '../src/container-code.js';

const rep = makeReport('05_container_check.txt');
let fails = 0;
const expect = (name, ok, extra = '') => { if (!ok) fails++; rep.log(`${ok ? 'ĐẠT ' : 'LỖI '} ${name} ${extra}`); };

// ---- 1. Ảnh mẫu data/container/sample_rear.png
const gt = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'container', 'ground_truth.json'), 'utf8')).sample_rear;
rep.log('=== 1. ẢNH MẪU data/container/sample_rear.png (cửa sau thùng 20ft)');
rep.log(`Đáp án mã container : ${gt.container.slice(0, 4)} ${gt.container.slice(4, 10)} ${gt.container[10]}`);
rep.log(`Số kiểm tra tính ra : ${checkDigit(gt.container.slice(0, 10))}  (ảnh ghi: ${gt.container[10]})`);
expect('Mã COLU2008412 hợp lệ theo ISO 6346', isValid(gt.container));
expect('Ví dụ chuẩn CSQU3054383 hợp lệ (kiểm chứng công thức)', isValid('CSQU3054383'));
const t = decodeType(gt.type);
rep.log(`Mã loại ${gt.type}        : ${t.length}, cao ${t.height}, ${t.kind}`);

// ---- 2. Chuẩn hoá lỗi nhầm LOẠI ký tự (an toàn, theo vị trí)
rep.log('\n=== 2. CHUẨN HOÁ THEO VỊ TRÍ (3 ký tự đầu + U là chữ; 7 ký tự sau là số)');
for (const [raw, want] of [['C0LU 200841 2', 'COLU2008412'], ['COLU 2O0841 2', 'COLU2008412'], ['COLU 200B41 2', 'COLU2008412'], ['COLU-200841-2', 'COLU2008412'], ['c o l u 200841 2', 'COLU2008412']]) {
  const r = recover(raw);
  expect(`"${raw}" -> ${r.code ?? 'từ chối'}`, r.code === want, `[${r.status}]`);
}

// ---- 3. Các kết quả OCR thật đã đo trên ảnh mẫu
rep.log('\n=== 3. KẾT QUẢ OCR HIỆN CÓ TRÊN ẢNH MẪU (ảnh 198x183, rất nhỏ)');
for (const [engine, raw] of [['Tesseract x4 psm11', '200842 2'], ['Tesseract x4 đảo màu', '20082 2'], ['Tesseract x8', '00842 NGT']]) {
  const r = recover(raw);
  expect(`${engine}: đọc "${raw}" -> ${r.code ?? 'TỪ CHỐI'}`, r.code === null, `(${r.note})`);
}
const ct = normalizeType('2261');
expect(`CCT biển số đọc dòng mã loại "2261" -> chuẩn hoá "${ct}"`, ct === gt.type && isValidType(ct), '(đúng nhờ ép G là chữ ở vị trí 3)');
rep.log(`Gợi ý (CHỈ cho người duyệt) với chuỗi sai COLU2008422: ${JSON.stringify(suggestRepairs('COLU2008422'))}  <- KHÔNG PHẢI mã đúng (COLU2008412)`);

// ---- 4. Vote nhiều khung hình
rep.log('\n=== 4. BỎ PHIẾU NHIỀU KHUNG HÌNH');
const v1 = vote(['COLU2008422', 'COLU2008412', 'C0LU 200841 2', 'COLU2008472', 'COLU2008412']);
expect('5 khung (3 đúng, 2 sai) -> chọn COLU2008412', v1?.code === 'COLU2008412', `votes=${v1?.votes}/${v1?.of}`);
expect('1 khung duy nhất -> chưa đủ tin cậy, không chốt', vote(['COLU2008412']) === null);

// ---- 5. Mô phỏng độ an toàn (dữ liệu giả lập, seed cố định)
rep.log('\n=== 5. MÔ PHỎNG ĐỘ AN TOÀN (20.000 mã ngẫu nhiên; mỗi ký tự đọc sai độc lập với xác suất p)');
let seed = 20260101; const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32;
const L = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', D = '0123456789', pick = (s) => s[Math.floor(rnd() * s.length)];
const randomCode = () => { let s = pick(L) + pick(L) + pick(L) + 'U'; for (let i = 0; i < 6; i++) s += pick(D); return s + checkDigit(s); };
const noisy = (t, p) => [...t].map((c, i) => (rnd() < p ? (i < 4 ? pick(L) : pick(D)) : c)).join('');
const N = 20000;
rep.log('p = tỉ lệ đọc sai MỖI KÝ TỰ.  "ĐÚNG/SAI/KHÔNG RA" tính trên tổng số mã.');
rep.log('p      cách làm                          ĐÚNG    SAI(nguy hiểm)  KHÔNG RA');
for (const p of [0.03, 0.06, 0.10]) {
  for (const [name, frames, mode] of [['1 khung, chỉ cần hợp lệ', 1, 'single'], ['3 khung, vote ≥2', 3, 'vote'], ['5 khung, vote ≥2', 5, 'vote'], ['8 khung, vote ≥2', 8, 'vote']]) {
    let ok = 0, bad = 0, none = 0;
    for (let k = 0; k < N; k++) {
      const t = randomCode(); const reads = Array.from({ length: frames }, () => noisy(t, p));
      const res = mode === 'single' ? (recover(reads[0]).code ? { code: recover(reads[0]).code } : null) : vote(reads, 2);
      if (!res) none++; else if (res.code === t) ok++; else bad++;
    }
    const f = (x) => (x / N * 100).toFixed(1).padStart(5) + '%';
    rep.log(`${String(p).padEnd(6)} ${name.padEnd(32)} ${f(ok)}   ${f(bad).padStart(8)}        ${f(none)}`);
  }
}
rep.log('\nKết luận: 1 khung cho phép lọt mã sai (cột SAI > 0). Bỏ phiếu ≥2 khung đưa cột SAI về gần 0,');
rep.log('đổi lại có lúc "KHÔNG RA" — nên chọn: thà không ra kết quả (nhờ bảo vệ nhập tay) còn hơn ra mã sai.');
rep.log(fails ? `\n${fails} kiểm tra LỖI` : '\nTất cả kiểm tra ĐẠT');
rep.save();
if (fails) process.exitCode = 1;
