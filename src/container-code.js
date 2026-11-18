// Mã container theo ISO 6346 — kiểm tra, chuẩn hoá, sửa lỗi OCR, bỏ phiếu nhiều khung hình.
// Không phụ thuộc thư viện nào: chạy được cả Node lẫn browser.
//
// Định dạng 11 ký tự:  AAAU 123456 7
//   AAA = mã chủ sở hữu (3 chữ) · U/J/Z/R = loại thiết bị (U = container) · 6 số serial · 1 số kiểm tra

const LETTER_VALUE = {};
'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').forEach((c, i) => {
  // Bảng giá trị ISO 6346: A=10, rồi bỏ qua 11, 22, 33 (bội của 11) -> B=12 ... L=23 ... V=34 ... Z=38
  LETTER_VALUE[c] = 10 + i + (i === 0 ? 0 : i <= 10 ? 1 : i <= 20 ? 2 : 3);
});

/** Số kiểm tra tính từ 10 ký tự đầu. */
export function checkDigit(first10) {
  let sum = 0;
  for (let i = 0; i < 10; i++) {
    const ch = first10[i];
    const v = /[A-Z]/.test(ch) ? LETTER_VALUE[ch] : Number(ch);
    sum += v * 2 ** i;
  }
  return (sum % 11) % 10;
}

/** Bỏ khoảng trắng/ký tự lạ, viết hoa. */
export const clean = (raw) => String(raw ?? '').toUpperCase().replace(/[^A-Z0-9]/g, '');

const SHAPE = /^[A-Z]{3}[UJZR]\d{7}$/;

/** true nếu đúng dạng 3 chữ + U/J/Z/R + 7 số VÀ số kiểm tra khớp. */
export function isValid(raw) {
  const s = clean(raw);
  return s.length === 11 && SHAPE.test(s) && checkDigit(s.slice(0, 10)) === Number(s[10]);
}

// Nhầm lẫn hay gặp khi OCR, theo từng LOẠI vị trí.
const TO_DIGIT = { O: '0', Q: '0', D: '0', I: '1', L: '1', Z: '2', S: '5', B: '8', G: '6' };
const TO_LETTER = { 0: 'O', 1: 'I', 2: 'Z', 5: 'S', 8: 'B', 6: 'G', 4: 'A' };
// Cặp dễ nhầm về hình dạng (dùng khi thử sửa 1 ký tự)
const LOOKALIKE = {
  0: ['8', '6', 'O', 'D', 'Q'], 1: ['7', 'I', 'L'], 2: ['Z'], 3: ['8'], 4: ['9', 'A'],
  5: ['6', 'S'], 6: ['5', '8', 'G'], 7: ['1'], 8: ['0', '3', '6', 'B'], 9: ['4'],
  O: ['0', 'Q', 'D'], I: ['1', 'L'], L: ['1', 'I'], Z: ['2'], S: ['5'], B: ['8'], G: ['6', 'C'],
  C: ['G'], D: ['0', 'O'], Q: ['0', 'O'], U: ['V'], V: ['U'], A: ['4'],
};

/** Ép từng vị trí về đúng loại (3 đầu + vị trí 4 là chữ; 7 ký tự sau là số). */
export function normalize(raw) {
  const s = clean(raw);
  if (s.length !== 11) return s;
  return [...s].map((ch, i) => {
    const wantLetter = i < 4;
    if (wantLetter) return /[0-9]/.test(ch) ? (TO_LETTER[ch] ?? ch) : ch;
    return /[A-Z]/.test(ch) ? (TO_DIGIT[ch] ?? ch) : ch;
  }).join('');
}

/**
 * Kiểm tra một chuỗi OCR. KHÔNG tự đoán/sửa ký tự (xem suggestRepairs bên dưới và lý do).
 * Trả { code, status, note }:
 *   'valid'      : đúng định dạng + số kiểm tra khớp
 *   'normalized' : hợp lệ sau khi ép đúng LOẠI ký tự theo vị trí (O↔0, B↔8 ...)
 *   'invalid'    : không hợp lệ -> bỏ, đợi khung hình khác
 * Lưu ý: số kiểm tra chỉ 1 chữ số nên chuỗi SAI vẫn lọt qua với xác suất ~2% (sai 1 ký tự)
 * đến ~12% (sai 2 ký tự). Vì vậy kết quả cuối phải qua vote() nhiều khung hình.
 */
export function recover(raw) {
  const s = clean(raw);
  if (isValid(s)) return { code: s, status: 'valid', note: '' };
  const n = normalize(s);
  if (isValid(n)) return { code: n, status: 'normalized', note: `${s} → ${n}` };
  if (n.length !== 11) return { code: null, status: 'invalid', note: `độ dài ${n.length} (cần 11)` };
  return { code: null, status: 'invalid', note: 'sai số kiểm tra' };
}

/**
 * CHỈ ĐỂ GỢI Ý cho người xem duyệt: các mã hợp lệ cách chuỗi OCR đúng 1 ký tự (thay bằng ký tự giống hình).
 * KHÔNG dùng làm kết quả tự động: mô phỏng cho thấy cách này trả ra mã hợp lệ-nhưng-SAI tới ~35% khi lỗi OCR
 * là chữ số bất kỳ. Số kiểm tra chỉ đủ để LOẠI kết quả sai, không đủ để TÌM ra kết quả đúng.
 */
export function suggestRepairs(raw) {
  const n = normalize(raw);
  if (n.length !== 11) return [];
  const found = new Set();
  for (let i = 0; i < 11; i++) {
    for (const alt of LOOKALIKE[n[i]] ?? []) {
      const t = n.slice(0, i) + alt + n.slice(i + 1);
      if (isValid(t)) found.add(t);
    }
  }
  return [...found];
}

/** Tìm mã trong một đoạn chữ dài (ghép các dòng OCR). Trả danh sách mã hợp lệ. */
export function findInText(text) {
  const s = clean(text), out = new Set();
  for (let i = 0; i + 11 <= s.length; i++) { const r = recover(s.slice(i, i + 11)); if (r.code) out.add(r.code); }
  return [...out];
}

/** Bỏ phiếu qua nhiều khung hình: chỉ đếm kết quả HỢP LỆ, trả mã xuất hiện nhiều nhất. */
export function vote(readings, minVotes = 2) {
  const count = new Map();
  for (const r of readings) { const { code } = recover(r); if (code) count.set(code, (count.get(code) ?? 0) + 1); }
  const top = [...count.entries()].sort((a, b) => b[1] - a[1])[0];
  return top && top[1] >= minVotes ? { code: top[0], votes: top[1], of: readings.length } : null;
}

const LEN = { 2: '20ft', 3: '30ft', 4: '40ft', L: '45ft', M: '48ft' };
const HEIGHT = { 0: '8ft', 2: '8ft6in', 4: '9ft', 5: '9ft6in (high cube)', 6: 'trên 9ft6in', 8: 'nửa chiều cao', 9: 'thấp hơn nửa chiều cao' };
const KIND = { G: 'hàng tổng hợp', R: 'lạnh (reefer)', U: 'mở nóc (open top)', P: 'sàn/flat rack', T: 'bồn (tank)', B: 'hàng rời', S: 'chuyên dụng', H: 'cách nhiệt' };

/** Ép mã loại 4 ký tự về đúng loại theo vị trí: [số|L|M][số][chữ][số]. Ví dụ '2261' -> '22G1'. */
export function normalizeType(raw) {
  const s = clean(raw);
  if (s.length !== 4) return s;
  const c0 = /[0-9LM]/.test(s[0]) ? s[0] : (TO_DIGIT[s[0]] ?? s[0]);
  const c1 = /[0-9]/.test(s[1]) ? s[1] : (TO_DIGIT[s[1]] ?? s[1]);
  const c2 = /[A-Z]/.test(s[2]) ? s[2] : (TO_LETTER[s[2]] ?? s[2]);
  const c3 = /[0-9]/.test(s[3]) ? s[3] : (TO_DIGIT[s[3]] ?? s[3]);
  return c0 + c1 + c2 + c3;
}
export const isValidType = (raw) => /^[2-4LM][0-9][A-Z][0-9]$/.test(clean(raw));

/** Giải mã mã kích thước/loại, ví dụ '22G1' -> 20ft, cao 8ft6in, hàng tổng hợp. */
export function decodeType(raw) {
  const s = clean(raw);
  if (!/^[0-9A-Z]{4}$/.test(s)) return null;
  return {
    code: s,
    length: LEN[s[0]] ?? `không rõ (${s[0]})`,
    height: HEIGHT[s[1]] ?? `không rõ (${s[1]})`,
    kind: KIND[s[2]] ?? `không rõ (${s[2]})`,
    ghi_chu: s === '45G1' ? 'mã cũ; chuẩn mới ghi L5G1' : '',
  };
}
