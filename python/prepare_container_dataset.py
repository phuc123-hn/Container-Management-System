"""
Chuẩn bị dataset container (định dạng YOLOv8 của Roboflow) để train Ultralytics YOLO (detect).

Vì sao cần:
  * Dataset trộn 2 kiểu nhãn: khung (5 số) và ĐA GIÁC xoay/nghiêng (>5 số), nhiều khi trong CÙNG một file.
    Ultralytics bản mới coi file như vậy là hỏng ("labels mix segment and detection rows") và BỎ ảnh đó.
    Script đổi mọi đa giác thành khung chữ nhật bao ngoài để không mất ảnh nào.
  * Có ảnh PANORAMA rất rộng (ví dụ 7000x2048). Thu về 960-1280 px thì chữ chỉ còn vài pixel.
    --drop-panorama bỏ chúng ra khỏi bộ train (tuỳ chọn).

Chạy:
    python python/prepare_container_dataset.py --src "C:\\duong\\dan\\Container OCR.v8i.yolov8" --drop-panorama
Kết quả:
    data/container_clean/              dataset sạch (ảnh dùng hard-link nếu cùng ổ đĩa, không tốn thêm dung lượng)
    result/07_prepare_container.txt    báo cáo: nhãn đã đổi, cỡ ảnh, khung dọc, khung nhỏ ở từng imgsz
"""
import argparse, os, random, shutil, sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))
from roboflow_fetch import read_names, find_splits, IMG_EXT   # dùng lại hàm đọc data.yaml

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "result"; RESULT.mkdir(exist_ok=True)
lines = []
def log(s=""):
    print(s); lines.append(s)

def to_box(vals, min_box):
    """vals = [cx,cy,w,h] hoặc [x1,y1,x2,y2,...] -> (cx,cy,w,h) chuẩn hoá, hoặc None nếu suy biến."""
    if len(vals) == 4:
        cx, cy, w, h = vals
        x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    elif len(vals) >= 6 and len(vals) % 2 == 0:
        xs, ys = vals[0::2], vals[1::2]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    else:
        return None
    x1, y1, x2, y2 = max(0.0, x1), max(0.0, y1), min(1.0, x2), min(1.0, y2)
    w, h = x2 - x1, y2 - y1
    if w < min_box or h < min_box:
        return None
    return (x1 + w / 2, y1 + h / 2, w, h)


COLORS = [(34, 197, 94), (250, 204, 21), (56, 189, 248)]      # container-number, iso-type, seal
POLY = (236, 72, 153)

def get_font(size):
    for f in ("DejaVuSans.ttf", "segoeui.ttf", "arial.ttf", "C:/Windows/Fonts/segoeui.ttf",
              "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try: return ImageFont.truetype(f, size)
        except Exception: pass
    return ImageFont.load_default()

def read_rows(lab):
    return [r.split() for r in lab.read_text().splitlines() if r.strip()] if lab.exists() else []

def draw_one(img_path, lab, min_box, tag):
    im = Image.open(img_path); W, H = im.size
    k = min(1.0, 1600 / max(W, H)); w, h = max(1, int(W * k)), max(1, int(H * k))
    try: im.draft("RGB", (w, h))
    except Exception: pass
    im = im.convert("RGB").resize((w, h)); dr = ImageDraw.Draw(im); lw = max(2, round(max(w, h) / 450))
    npoly = 0
    for r in read_rows(lab):
        c = int(float(r[0])) % 3; v = [float(x) for x in r[1:]]
        if len(r) > 5:
            npoly += 1; pts = [(v[i] * w, v[i + 1] * h) for i in range(0, len(v) - 1, 2)]
            dr.line(pts + [pts[0]], fill=POLY, width=lw)
        b = to_box(v, min_box)
        if b: dr.rectangle([(b[0] - b[2] / 2) * w, (b[1] - b[3] / 2) * h, (b[0] + b[2] / 2) * w, (b[1] + b[3] / 2) * h], outline=COLORS[c], width=lw)
    fs = max(13, round(w / 38))                              # chữ tỉ lệ theo ảnh để còn đọc được sau khi thu nhỏ vào ảnh tổng hợp
    dr.rectangle([0, 0, w, fs + 12], fill=(15, 23, 42))
    dr.text((6, 5), f"{img_path.name[:34]} · {W}×{H}" + (f" · {npoly} đa giác→khung" if npoly else "") + (f" · {tag}" if tag else ""), fill=(248, 250, 252), font=get_font(fs))
    return im

def make_visuals(cands, min_box, seed, out_dir):
    rnd = random.Random(seed); out_dir.mkdir(parents=True, exist_ok=True)
    has_poly = lambda c: any(len(r) > 5 for r in read_rows(c[2]))
    kept = [c for c in cands if not c[4]]
    poly = [c for c in kept if has_poly(c)]; plain = [c for c in kept if c[3] == "thường" and c not in poly]
    gone = [c for c in cands if c[4]]
    pick = [(c, "") for c in rnd.sample(poly, min(9, len(poly)))] + [(c, "") for c in rnd.sample(plain, min(6, len(plain)))] \
         + [(c, "BỊ BỎ (panorama)") for c in rnd.sample(gone, min(3, len(gone)))]
    tiles = []
    for (sp, im, lab, kind, dropped), tag in pick:
        t = draw_one(im, lab, min_box, tag); t.save(out_dir / f"{sp}_{im.stem[:60]}.jpg", quality=85); tiles.append(t)
    if not tiles: return 0
    TW, cols = 560, 3
    tiles = [t.resize((TW, max(60, int(t.height * TW / t.width)))) for t in tiles]
    rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]; rh = [max(t.height for t in r) for r in rows]
    sheet = Image.new("RGB", (cols * (TW + 6) + 6, sum(rh) + 6 * len(rows) + 70), (2, 6, 23)); d = ImageDraw.Draw(sheet)
    d.text((10, 8), "Xanh lá = container-number · Vàng = iso-type · Xanh dương = seal · HỒNG = nhãn đa giác gốc (khung màu lớp bên trong = khung SAU khi đổi)", fill=(248, 250, 252), font=get_font(15))
    d.text((10, 34), "Hàng đầu: ảnh có đa giác. Cuối: panorama bị bỏ khỏi bộ train. Kiểm tra khung màu có ôm đúng vùng chữ không.", fill=(250, 204, 21), font=get_font(15))
    y = 70
    for r, h in zip(rows, rh):
        for i, t in enumerate(r): sheet.paste(t, (6 + i * (TW + 6), y))
        y += h + 6
    sheet.save(out_dir / "_tong_hop.jpg", quality=88)
    return len(tiles)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="Thư mục dataset gốc (có data.yaml, train/, valid/, test/)")
    ap.add_argument("--dst", default=str(ROOT / "data" / "container_clean"))
    ap.add_argument("--drop-panorama", action="store_true", help="Bỏ ảnh có rộng/cao > --max-aspect")
    ap.add_argument("--max-aspect", type=float, default=2.6)
    ap.add_argument("--min-box", type=float, default=0.002, help="Bỏ khung có cạnh nhỏ hơn tỉ lệ này")
    ap.add_argument("--copy", action="store_true", help="Sao chép ảnh thay vì hard-link")
    ap.add_argument("--resize-max", type=int, default=0, help="Thu nhỏ ảnh có cạnh dài hơn giá trị này (ví dụ 1600) để train nhanh hơn; 0 = giữ nguyên (hard-link)")
    ap.add_argument("--no-visual", action="store_true", help="Không xuất ảnh minh hoạ nhãn")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    src = Path(a.src)
    ys = list(src.glob("data.yaml")) or list(src.rglob("data.yaml"))
    if not ys: sys.exit(f"Không thấy data.yaml trong {src}")
    src = ys[0].parent
    names = read_names(ys[0]); splits = find_splits(src)
    dst = Path(a.dst)
    if dst.exists():
        sys.exit(f"{dst} đã tồn tại. Xoá hoặc đổi --dst rồi chạy lại (script không ghi đè).")
    log(f"Nguồn : {src}\nĐích  : {dst}\nLớp   : {names}\nBỏ panorama: {'CÓ (rộng/cao > %.1f)' % a.max_aspect if a.drop_panorama else 'không'}")

    kinds = Counter(); sizes = Counter()
    conv = Counter(); kept_box = Counter(); degenerate = Counter(); empty_after = Counter()
    n_resized = Counter(); n_in = Counter(); n_drop = Counter(); n_out = Counter(); mixed_files = Counter()
    cands = []                                             # (split, ảnh, file nhãn, loại, bị bỏ?)
    cn_vertical = [0, 0]                                   # [số khung container-number dọc, tổng]
    small = {sz: {c: [0, 0, 0] for c in range(len(names))} for sz in (640, 960, 1280)}   # <12px, <20px, tổng

    for sp, d in splits.items():
        (dst / sp / "images").mkdir(parents=True); (dst / sp / "labels").mkdir(parents=True)
        for im in sorted(p for p in (d / "images").iterdir() if p.suffix.lower() in IMG_EXT):
            n_in[sp] += 1
            W, H = Image.open(im).size
            asp = W / H; sizes[(W, H)] += 1
            kind = "panorama" if asp > a.max_aspect else "ảnh dọc" if asp < 0.9 else "thường"
            kinds[(sp, kind)] += 1
            lab = d / "labels" / (im.stem + ".txt")
            dropped = a.drop_panorama and kind == "panorama"
            cands.append((sp, im, lab, kind, dropped))
            if dropped:
                n_drop[sp] += 1; continue
            out_lines = []
            if lab.exists():
                rows = [l.split() for l in lab.read_text().splitlines() if l.strip()]
                if any(len(r) > 5 for r in rows) and any(len(r) == 5 for r in rows): mixed_files[sp] += 1
                for r in rows:
                    c = int(float(r[0])); box = to_box([float(x) for x in r[1:]], a.min_box)
                    if box is None: degenerate[names[c]] += 1; continue
                    if len(r) > 5: conv[names[c]] += 1
                    kept_box[names[c]] += 1
                    out_lines.append(f"{c} {box[0]:.6f} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f}")
                    bw, bh = box[2] * W, box[3] * H
                    if names[c] == "container-number":
                        cn_vertical[1] += 1; cn_vertical[0] += (bh / max(bw, 1e-6) > 1.5)
                    for sz in small:
                        s = sz / max(W, H); m = min(bw, bh) * s
                        small[sz][c][2] += 1; small[sz][c][0] += (m < 12); small[sz][c][1] += (m < 20)
            if not out_lines: empty_after[sp] += 1
            (dst / sp / "labels" / (im.stem + ".txt")).write_text("\n".join(out_lines) + ("\n" if out_lines else ""))
            target = dst / sp / "images" / im.name
            if a.resize_max and max(W, H) > a.resize_max:      # ảnh 4K giải mã chậm mỗi epoch; nhãn là tỉ lệ nên không đổi
                with Image.open(im) as pi:
                    k = a.resize_max / max(W, H)
                    pi.convert("RGB").resize((round(W * k), round(H * k)), Image.LANCZOS).save(target.with_suffix(".jpg"), quality=92)
                n_resized[sp] += 1
            elif a.copy: shutil.copy2(im, target)
            else:
                try: os.link(im, target)
                except OSError: shutil.copy2(im, target)
            n_out[sp] += 1

    yaml = [f"path: {dst.resolve().as_posix()}", "train: train/images", "val: valid/images"]
    if "test" in splits: yaml.append("test: test/images")
    yaml += [f"nc: {len(names)}", "names: [" + ", ".join(f"'{n}'" for n in names) + "]"]
    (dst / "data.yaml").write_text("\n".join(yaml) + "\n", encoding="utf-8")

    log("\n== ẢNH")
    for sp in splits:
        log(f"  [{sp}] gốc {n_in[sp]} · bỏ {n_drop[sp]} · giữ {n_out[sp]} · thu nhỏ {n_resized[sp]} · không còn khung nào {empty_after[sp]} · file nhãn TRỘN khung+đa giác {mixed_files[sp]}")
    tot = sum(n_in.values())
    for kind in ("thường", "panorama", "ảnh dọc"):
        n = sum(v for (sp, k), v in kinds.items() if k == kind)
        log(f"  {kind:<9}: {n:>5} ảnh ({n / max(1, tot) * 100:4.1f}%)")
    log("  Kích thước phổ biến: " + ", ".join(f"{w}x{h} ×{n}" for (w, h), n in sizes.most_common(6)))
    log("\n== NHÃN (sau khi đổi đa giác -> khung)")
    for n in names:
        log(f"  {n:<18} giữ {kept_box[n]:>6} khung · trong đó đổi từ đa giác {conv[n]:>5} · bỏ vì suy biến {degenerate[n]}")
    if cn_vertical[1]:
        log(f"\n== SỐ CONTAINER NẰM DỌC: {cn_vertical[0]}/{cn_vertical[1]} khung container-number cao hơn rộng >1.5 lần ({cn_vertical[0] / cn_vertical[1] * 100:.0f}%)")
        log("   -> bước đọc chữ phải xử lý chữ dọc (xoay crop hoặc đọc theo cột), không thể dùng nguyên bộ đọc ngang.")
    log("\n== KHUNG QUÁ NHỎ ở từng imgsz (cạnh ngắn của khung, sau khi thu ảnh về imgsz)")
    log("   imgsz   lớp                <12px   <20px")
    for sz in small:
        for c, n in enumerate(names):
            lo, mid, t = small[sz][c]
            if t: log(f"   {sz:<7} {n:<18} {lo / t * 100:5.1f}%  {mid / t * 100:5.1f}%")
    log(f"\nĐã tạo dataset sạch: {dst / 'data.yaml'}")
    if not a.no_visual:
        vis = RESULT / "07_prepare_visual"
        n = make_visuals(cands, a.min_box, a.seed, vis)
        log(f"Đã xuất {n} ảnh minh hoạ nhãn vào: {vis}  (mở _tong_hop.jpg trước)")
    (RESULT / "07_prepare_container.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f">> Đã ghi: {RESULT / '07_prepare_container.txt'}")

if __name__ == "__main__":
    main()