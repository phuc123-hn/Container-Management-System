/**
 * plate-reader.js — đọc ký tự trên crop biển số (CCT-S v2), nối sau plate-detector.js.
 *
 * Model: Content/models/cct_s_v2_global.onnx (model thật trong SmartPort.Net10)
 *   input : "input"  [1,64,128,3] uint8 RGB — KHÔNG normalize, model tự làm
 *   output: "plate"  [1,10,37]    10 slot x alphabet "0-9A-Z_"
 *           "region" [1,66]       bỏ qua (phân loại quốc gia, không cần cho SmartPort)
 *
 * QUYẾT ĐỊNH KỸ THUẬT (có số liệu, xem OCR_FINDINGS.md):
 *   KHÔNG dùng trick "ghép hàng" (cắt đôi trên/dưới, resize mỗi nửa 64x64 rồi ghép ngang)
 *   mà alpr.js hiện có cho biển 2 dòng. Test trên 33 biển thật: ghép hàng → 0% exact-match,
 *   KHÔNG ghép (resize thẳng cả biển vào 128x64) → 97.0% exact-match. Lý do nhiều khả năng:
 *   mỗi nửa biển 2 dòng có tỉ lệ ~2.4:1, ép vào ô vuông 64x64 méo chữ rất nặng; resize thẳng
 *   cả biển (~1.2:1) vào 128x64 chỉ méo nhẹ. Module này CHỈ làm 1 cách (resize thẳng) —
 *   nhanh hơn (bớt 1 lần inference/candidate) và chính xác hơn, theo đúng số liệu đo được.
 */

export const DEFAULTS = Object.freeze({
  modelInputW: 128,
  modelInputH: 64,
  alphabet: '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_',
  slots: 10,
  blankChar: '_',
  minConfidence: 0.5,     // dưới ngưỡng này coi như đọc không tin cậy, trả plate=null
  sessionOptions: { executionProviders: ['wasm'] },
});

/** RGBA (Uint8ClampedArray) -> Uint8Array HWC RGB (bỏ kênh alpha). */
export function rgbaToHwcRgbUint8(rgba, w, h) {
  const out = new Uint8Array(w * h * 3);
  for (let i = 0, p = 0; i < w * h; i++, p += 4) {
    out[i * 3] = rgba[p];
    out[i * 3 + 1] = rgba[p + 1];
    out[i * 3 + 2] = rgba[p + 2];
  }
  return out;
}

/**
 * Giải mã output [10,37] (hoặc [1,10,37]) -> { text, conf, perSlot }.
 * Argmax từng slot, bỏ ký tự blank — KHÔNG phải CTC (không cần collapse ký tự lặp),
 * đúng cách model gốc hoạt động (xem alpr.js hàm docBienCCT).
 */
export function decodePlateOutput(data, opts = DEFAULTS) {
  const { slots, alphabet, blankChar } = opts;
  const n = alphabet.length;
  let text = '';
  const perSlot = [];
  for (let s = 0; s < slots; s++) {
    let best = -Infinity, bi = 0;
    for (let a = 0; a < n; a++) {
      const v = data[s * n + a];
      if (v > best) { best = v; bi = a; }
    }
    const ch = alphabet[bi];
    perSlot.push({ char: ch, score: best });
    if (ch !== blankChar) text += ch;
  }
  const kept = perSlot.filter((p) => p.char !== blankChar);
  const conf = kept.length ? kept.reduce((s, p) => s + p.score, 0) / kept.length : 0;
  return { text, conf, perSlot };
}

export class PlateReader {
  /**
   * @param {object} cfg
   * @param {object} cfg.ort
   * @param {string} [cfg.modelUrl]
   * @param {ArrayBuffer|Uint8Array} [cfg.modelBuffer]
   * @param {Function} [cfg.createCanvas]  (w,h)=>canvas
   */
  static async create(cfg) {
    const { ort, modelUrl, modelBuffer, createCanvas, ...rest } = cfg;
    if (!ort) throw new Error('Thiếu tham số `ort` (onnxruntime).');
    const opts = { ...DEFAULTS, ...rest };
    const src = modelBuffer ?? modelUrl;
    if (!src) throw new Error('Cần modelUrl hoặc modelBuffer.');
    const session = await ort.InferenceSession.create(src, opts.sessionOptions);
    return new PlateReader(ort, session, opts, createCanvas);
  }

  constructor(ort, session, opts, createCanvas) {
    this.ort = ort;
    this.session = session;
    this.opts = opts;
    this.createCanvas = createCanvas ?? ((w, h) => {
      if (typeof OffscreenCanvas !== 'undefined') return new OffscreenCanvas(w, h);
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      return c;
    });
    const { modelInputW: w, modelInputH: h } = opts;
    this._canvas = this.createCanvas(w, h);
    this._ctx = this._canvas.getContext('2d', { willReadFrequently: true });
  }

  /**
   * @param {CanvasImageSource} plateCrop  ảnh ĐÃ crop sát biển số (dùng PlateDetector.cropPlate)
   * @returns {{text, conf, plate, lowConfidence}}
   *   plate = text nếu conf >= minConfidence, ngược lại null (không đủ tin cậy để dùng)
   */
  async read(plateCrop) {
    const { modelInputW: w, modelInputH: h } = this.opts;
    const ctx = this._ctx;
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(plateCrop, 0, 0, w, h);  // resize THẲNG, không cắt đôi/ghép
    const rgba = ctx.getImageData(0, 0, w, h).data;
    const chw = rgbaToHwcRgbUint8(rgba, w, h);

    const tensor = new this.ort.Tensor('uint8', chw, [1, h, w, 3]);
    const results = await this.session.run({ [this.session.inputNames[0]]: tensor });
    const out = results['plate'] ?? results[this.session.outputNames[0]];

    const { text, conf } = decodePlateOutput(out.data, this.opts);
    return { text, conf, plate: conf >= this.opts.minConfidence ? text : null, lowConfidence: conf < this.opts.minConfidence };
  }
}
