"""
Gộp 4 file Python cũ (test_cct_ocr, test_compare_ocr, test_ocr_robustness) thành 1 file.
Chạy từ bất kỳ thư mục nào:   python python/test_python.py
Ghi kết quả vào:               result/04_python_tests.txt  (UTF-8)  và  result/04_python_results.json

Gồm 3 phần:
  A. Ghép hàng (logic cũ alpr.js) so với resize thẳng (cách mới)
  B. CCT so với Tesseract  -> TỰ BỎ QUA nếu máy chưa cài Tesseract (không báo lỗi)
  C. Độ bền: mờ / xe ở xa (thu nhỏ) / thiếu sáng
Cần: pip install onnxruntime pillow numpy      (pytesseract + Tesseract: tuỳ chọn)
"""
import glob, json, os, re, sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageFilter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # tránh lỗi 'charmap' trên Windows
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "cct_s_v2_global.onnx"
CROPS = ROOT / "data" / "ocr_crops"
GT_FILE = ROOT / "data" / "ground_truth.json"
OUT_DIR = ROOT / "result"
OUT_DIR.mkdir(exist_ok=True)

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
SLOTS, W, H = 10, 128, 64
GT = json.loads(GT_FILE.read_text(encoding="utf-8"))
sess = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
INPUT = sess.get_inputs()[0].name

lines = []
def log(s=""):
    print(s)
    lines.append(s)

def key_of(path):  # 'clip3.2_new_0__0.png' -> 'clip3_2_new_0__0'
    return Path(path).stem.replace(".", "_")

def decode(plate_out):
    """Argmax 10 slot, bỏ '_', nối chuỗi (KHÔNG phải CTC) — đúng logic plate-reader.js."""
    text, scores = "", []
    for s in range(SLOTS):
        bi = int(np.argmax(plate_out[s]))
        if ALPHABET[bi] != "_":
            text += ALPHABET[bi]
            scores.append(float(plate_out[s][bi]))
    return text, (sum(scores) / len(scores) if scores else 0.0)

def run_model(img):
    arr = np.asarray(img.convert("RGB").resize((W, H)), dtype=np.uint8)[None]
    return decode(sess.run(["plate"], {INPUT: arr})[0][0])

def run_ghep_hang(img):
    img = img.convert("RGB"); w, h = img.size
    top = img.crop((0, 0, w, h // 2)).resize((W // 2, H))
    bot = img.crop((0, h // 2, w, h)).resize((W // 2, H))
    out = Image.new("RGB", (W, H)); out.paste(top, (0, 0)); out.paste(bot, (W // 2, 0))
    arr = np.asarray(out, dtype=np.uint8)[None]
    return decode(sess.run(["plate"], {INPUT: arr})[0][0])

def score(pairs):
    sc = [(g, p) for g, p in pairs if g]
    exact = sum(g == p for g, p in sc)
    tot = sum(max(len(g), len(p)) for g, p in sc)
    ok = sum(sum(1 for i in range(min(len(g), len(p))) if g[i] == p[i]) for g, p in sc)
    return exact, len(sc), ok, tot

def fmt(name, pairs):
    e, n, ok, tot = score(pairs)
    return f"{name:<34} exact={e}/{n} = {e/n*100:5.1f}%   char-acc={ok}/{tot} = {ok/tot*100:5.1f}%"

files = sorted(glob.glob(str(CROPS / "*.png")))
log(f"Số crop: {len(files)} | model: {MODEL.name}\n")

# ---------------- A. ghép hàng vs resize thẳng ----------------
log("=== A. GHÉP HÀNG (logic cũ) so với RESIZE THẲNG (cách mới) ===")
results, A_old, A_new = [], [], []
for fp in files:
    k = key_of(fp); gt = GT.get(k); img = Image.open(fp)
    old, _ = run_ghep_hang(img); new, conf = run_model(img)
    A_old.append((gt, old)); A_new.append((gt, new))
    results.append({"name": k, "gt": gt, "pred_ghep_hang": old, "pred_resize_thang": new, "conf": conf})
log(fmt("Ghép hàng (cũ)", A_old))
log(fmt("Resize thẳng (mới)", A_new))

# ---------------- B. Tesseract (tuỳ chọn) ----------------
log("\n=== B. CCT so với TESSERACT ===")
try:
    import pytesseract
    for cand in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if os.path.exists(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
    pytesseract.get_tesseract_version()
    B = []
    for fp in files:
        g = Image.open(fp).convert("L")
        sc = max(2, min(6, round(150 / max(12, g.height))))  # đúng công thức scale trong alpr.js
        g = g.resize((g.width * sc, g.height * sc))
        txt = pytesseract.image_to_string(g, config="--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        B.append((GT.get(key_of(fp)), re.sub(r"[^0-9A-Z]", "", txt.upper())))
    log(fmt("CCT (resize thẳng)", A_new))
    log(fmt("Tesseract PSM=6", B))
except Exception as e:
    log(f"BỎ QUA: chưa dùng được Tesseract ({type(e).__name__}). Không ảnh hưởng phần còn lại.")
    log("Muốn chạy: cài Tesseract cho Windows (bản UB Mannheim) rồi chạy lại.")

# ---------------- C. độ bền ----------------
log("\n=== C. ĐỘ BỀN (CCT, resize thẳng) ===")
def cond(name, tf):
    pairs = [(GT.get(key_of(fp)), run_model(tf(Image.open(fp)))[0]) for fp in files]
    log(fmt(name, pairs))

def shrink(f):
    def t(im):
        w, h = im.size
        s = im.resize((max(1, int(w * f)), max(1, int(h * f))), Image.BILINEAR)
        return s.resize((w, h), Image.BILINEAR)
    return t

def darken(f):
    return lambda im: Image.fromarray((np.asarray(im.convert("RGB"), dtype=np.float32) * f).clip(0, 255).astype(np.uint8))

cond("Ảnh gốc", lambda im: im)
log("-- Mờ (Gaussian blur)")
for r in (1, 2, 3, 4):
    cond(f"  blur radius={r}", lambda im, r=r: im.filter(ImageFilter.GaussianBlur(r)))
log("-- Xe ở xa (thu nhỏ rồi phóng lại)")
for f in (0.75, 0.5, 0.35, 0.25):
    cond(f"  thu nhỏ còn {int(f*100)}%", shrink(f))
log("-- Thiếu sáng")
for f in (0.7, 0.5, 0.3):
    cond(f"  brightness x{f}", darken(f))

(OUT_DIR / "04_python_tests.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
(OUT_DIR / "04_python_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n>> Đã ghi: {OUT_DIR / '04_python_tests.txt'}")
