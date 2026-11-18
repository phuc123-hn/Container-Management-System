"""
Đo thử khả năng ĐỌC CHỮ của OCR có sẵn (Tesseract, RapidOCR) trên vùng container-number THẬT (khung nhãn của dataset).
Đây là mốc (baseline) để biết bước đọc chữ khó cỡ nào. Chưa phải model của dự án.

Chấm bằng số kiểm tra ISO 6346: "hợp lệ" = đúng định dạng 4 chữ + 7 số và khớp số kiểm tra.
LƯU Ý: hợp lệ chưa chắc ĐÚNG (chuỗi sai vẫn lọt qua khoảng 2-12%), nhưng chuỗi không hợp lệ thì chắc chắn sai/chưa đủ tin cậy.

Cài:    pip install pillow numpy rapidocr-onnxruntime pytesseract     (Tesseract không bắt buộc, thiếu thì bỏ qua)
Chạy:   python python/baseline_container_ocr.py --src "...\\Container OCR.v8i.yolov8" --n 60
Kết quả: result/08_baseline_ocr.txt  và  result/08_baseline_visual/_tong_hop.jpg
"""
import argparse, random, re, sys, time, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "result"; RESULT.mkdir(exist_ok=True)
lines = []
def log(s=""): print(s); lines.append(s)

# ---------------- ISO 6346 (bản Python của src/container-code.js)
LV = {c: 10 + i + (0 if i == 0 else 1 if i <= 10 else 2 if i <= 20 else 3) for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
def check_digit(s): return (sum((LV[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(s[:10])) % 11) % 10
def is_valid(s): return len(s) == 11 and bool(re.fullmatch(r"[A-Z]{3}[UJZR]\d{7}", s)) and check_digit(s) == int(s[10])
TD = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
TL = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A"}
def normalize(s): return "".join((TL.get(c, c) if i < 4 and c.isdigit() else TD.get(c, c) if i >= 4 and c.isalpha() else c) for i, c in enumerate(s))
def find_valid(txt):
    s = re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKC", txt).upper()); out = []   # NFKC: đổi chữ số toàn chiều rộng ６ -> 6
    for i in range(len(s) - 10):
        w = s[i:i + 11]
        for cand in (w, normalize(w)):
            if is_valid(cand) and cand not in out: out.append(cand)
    return out

def partial_read(txt):
    """Tìm 'chủ sở hữu(4 chữ) + 6 số' (+ số thứ 7 nếu có) trong chữ OCR. Trả (owner+serial, số_kiểm_tra_đọc_được|None)."""
    c = re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKC", txt).upper())
    m = re.search(r"([A-Z]{3}[UJZR])(\d{6})(\d?)", c)
    return (m.group(1) + m.group(2), m.group(3) or None) if m else (None, None)

def classify(raws):
    """A = mã hợp lệ 11 ký tự · B1 = đủ chủ+6 số nhưng KHÔNG đọc ra số kiểm tra · B2 = đọc ra số kiểm tra nhưng KHÔNG khớp (có ký tự sai) · C = một phần · D = không đọc được."""
    for r in raws:
        v = find_valid(r)
        if v: return "A", v[0]
    cands = [partial_read(r) for r in raws]; cands = [x for x in cands if x[0]]
    if cands:
        base, chk = cands[0]
        if all(c[1] is None for c in cands): return "B1", f"{base} + số KT tính ra: {check_digit(base)}"
        return "B2", f"{base}{chk} (số KT tính ra: {check_digit(base)}, không khớp)"
    if any(re.search(r"\d{5,}|[A-Z]{3}[UJZR]", re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKC", r).upper())) for r in raws): return "C", ""
    return "D", ""

# ---------------- cắt vùng container-number từ nhãn (khung hoặc đa giác)
def collect(src, split_names=("valid", "train")):
    out = []
    for sp in split_names:
        d = src / sp
        if not (d / "images").is_dir(): continue
        for im in sorted((d / "images").iterdir()):
            lab = d / "labels" / (im.stem + ".txt")
            if im.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"} or not lab.exists(): continue
            for ln in lab.read_text().splitlines():
                t = ln.split()
                if len(t) < 5 or int(float(t[0])) != 0: continue
                v = [float(x) for x in t[1:]]
                if len(t) == 5: x1, y1, x2, y2 = v[0] - v[2] / 2, v[1] - v[3] / 2, v[0] + v[2] / 2, v[1] + v[3] / 2
                else: x1, x2, y1, y2 = min(v[0::2]), max(v[0::2]), min(v[1::2]), max(v[1::2])
                out.append((sp, im, (x1, y1, x2, y2)))
    return out

def crop_of(im_path, box):
    img = Image.open(im_path).convert("RGB"); W, H = img.size
    x1, y1, x2, y2 = box; bw, bh = (x2 - x1) * W, (y2 - y1) * H
    if bw < 8 or bh < 8: return None
    px, py = bw * 0.08, bh * 0.08
    return img.crop((max(0, int(x1 * W - px)), max(0, int(y1 * H - py)), min(W, int(x2 * W + px)), min(H, int(y2 * H + py))))

def prep(c, target=96):
    g = ImageOps.autocontrast(c.convert("L")); s = max(1.0, target / min(g.size))
    return g.resize((max(1, int(g.width * s)), max(1, int(g.height * s))), Image.LANCZOS)

# ---------------- engines
def make_engines():
    eng = {}
    try:
        import pytesseract
        for cand in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if Path(cand).exists(): pytesseract.pytesseract.tesseract_cmd = cand
        pytesseract.get_tesseract_version()
        def tess(c, vert):
            outs = []
            for inv in (False, True):
                g = prep(c); g = ImageOps.invert(g) if inv else g
                for gg in ([g] if not vert else [g.rotate(90, expand=True), g.rotate(-90, expand=True)]):
                    outs.append(pytesseract.image_to_string(gg, config="--psm 7 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            return " ".join(outs)
        eng["Tesseract"] = tess
    except Exception as e:
        log(f"(bỏ qua Tesseract: {type(e).__name__})")
    try:
        from rapidocr_onnxruntime import RapidOCR
        rapid = RapidOCR()
        def rap(c, vert):
            outs = []
            for im in ([c] if not vert else [c, c.rotate(90, expand=True), c.rotate(-90, expand=True)]):
                res, _ = rapid(np.asarray(prep(im, 96).convert("RGB")))
                if res: outs.append(" ".join(r[1] for r in res))
            return " ".join(outs)
        eng["RapidOCR"] = rap
    except Exception as e:
        log(f"(bỏ qua RapidOCR: {type(e).__name__}: pip install rapidocr-onnxruntime)")
    return eng

def font(size):
    for f in ("DejaVuSans.ttf", "segoeui.ttf", "arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try: return ImageFont.truetype(f, size)
        except Exception: pass
    return ImageFont.load_default()

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True); ap.add_argument("--n", type=int, default=60); ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    src = Path(a.src); ys = list(src.glob("data.yaml")) or list(src.rglob("data.yaml"))
    if ys: src = ys[0].parent
    items = collect(src)
    if not items: sys.exit("Không thấy nhãn container-number (lớp 0) trong dataset.")
    random.Random(a.seed).shuffle(items); engines = make_engines()
    if not engines: sys.exit("Không có engine OCR nào. Cài: pip install rapidocr-onnxruntime pytesseract")
    log(f"Mẫu ngẫu nhiên tối đa {a.n} vùng container-number (từ {len(items)} vùng). Engine: {list(engines)}\n")
    stats = defaultdict(Counter); rows = []; t0 = time.time()
    for k, (sp, im, box) in enumerate(items):
        if len(rows) >= a.n: break
        c = crop_of(im, box)
        if c is None: continue
        orient = "dọc" if c.height > 1.5 * c.width else "ngang" if c.width > 1.5 * c.height else "vuông"
        res = {}; raws = []
        for name, fn in engines.items():
            txt = fn(c, orient == "dọc"); raws.append(txt); ok = find_valid(txt); res[name] = (ok[0] if ok else None, re.sub(r"\s+", " ", txt).strip()[:26])
            for g in ("tất cả", "hướng " + orient): stats[(name, g)]["n"] += 1; stats[(name, g)]["ok"] += bool(ok)
        cat, info = classify(raws)
        for g in ("tất cả", "hướng " + orient): stats[("HỢP NHẤT", g)][cat] += 1; stats[("HỢP NHẤT", g)]["n"] += 1
        rows.append((im.name, orient, c, res, cat, info))
        if len(rows) % 10 == 0: print(f"  ... {len(rows)}/{a.n} ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
    log("Tỉ lệ vùng mà engine đọc ra ĐƯỢC MÃ HỢP LỆ ISO 6346 (khung đã đúng 100%, vì lấy từ nhãn):")
    for g in ("tất cả", "hướng ngang", "hướng dọc", "hướng vuông"):
        parts = [f"{e}: {stats[(e, g)]['ok']}/{stats[(e, g)]['n']} = {stats[(e, g)]['ok'] / stats[(e, g)]['n'] * 100:4.1f}%" for e in engines if stats[(e, g)]["n"]]
        if parts: log(f"  {g:<12} " + "  |  ".join(parts))
    log("\nHỢP NHẤT CẢ HAI ENGINE (một vùng tính là thành công nếu engine nào đó ra mã hợp lệ):")
    log("  A=mã hợp lệ · B1=đủ chủ+6 số, thiếu số kiểm tra · B2=có số kiểm tra nhưng không khớp · C=một phần · D=không đọc được")
    for g in ("tất cả", "hướng ngang", "hướng dọc", "hướng vuông"):
        st = stats[("HỢP NHẤT", g)]
        if st["n"]: log(f"  {g:<12} n={st['n']:<4} " + "  ".join(f"{k}={st[k]:>3}" for k in ("A", "B1", "B2", "C", "D")))
    log("  Lưu ý: nhóm B chưa chắc đúng; B1 chỉ là ứng viên, cần xác nhận bằng số kiểm tra đọc riêng từ ô vuông hoặc bỏ phiếu nhiều khung.")
    log("\nTừng vùng:")
    for name, orient, c, res, cat, info in rows:
        log(f"  {name[:40]:<40} {orient:<6} [{cat}] " + " | ".join(f"{e}: {r[0] or '✘ ' + r[1]}" for e, r in res.items()) + (f"  => {info}" if info and cat != 'A' else ""))
    # ---- ảnh minh hoạ
    vis = RESULT / "08_baseline_visual"; vis.mkdir(exist_ok=True)
    TW = 360; tiles = []
    for name, orient, c, res, cat, info in rows[:24]:
        s = min(TW / c.width, 300 / c.height); cc = c.resize((max(1, int(c.width * s)), max(1, int(c.height * s))))
        h = 300 + 52 + 22 * len(res); t = Image.new("RGB", (TW, h), (15, 23, 42)); d = ImageDraw.Draw(t)
        t.paste(cc, ((TW - cc.width) // 2, 4)); y = 300 + 4
        d.text((6, y), f"{orient} · {name[:34]}", fill=(148, 163, 184), font=font(11)); y += 20
        for e, r in res.items():
            d.text((6, y), f"{e}: " + (r[0] if r[0] else "x " + r[1]), fill=(34, 197, 94) if r[0] else (239, 68, 68), font=font(14)); y += 22
        d.text((6, y), f"[{cat}] " + (info if cat in ("B1", "B2") else ""), fill=(250, 204, 21) if cat.startswith("B") else (148, 163, 184), font=font(12))
        tiles.append(t)
    if tiles:
        cols = 4; rws = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
        sheet = Image.new("RGB", (cols * (TW + 6) + 6, sum(r[0].height + 6 for r in rws) + 40), (2, 6, 23)); d = ImageDraw.Draw(sheet)
        d.text((10, 10), "Xanh = mã hợp lệ ISO 6346 · Đỏ = không hợp lệ (hiện chữ OCR đọc được) · Vàng [B1/B2] = đọc được chủ+serial, số kiểm tra tính ra", fill=(248, 250, 252), font=font(15))
        y = 40
        for r in rws:
            for i, t in enumerate(r): sheet.paste(t, (6 + i * (TW + 6), y))
            y += r[0].height + 6
        sheet.save(vis / "_tong_hop.jpg", quality=88)
    (RESULT / "08_baseline_ocr.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n>> Đã ghi: {RESULT / '08_baseline_ocr.txt'} và ảnh: {vis / '_tong_hop.jpg'}")

if __name__ == "__main__":
    main()
