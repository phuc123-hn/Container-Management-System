"""
Lấy dataset từ Roboflow qua API (không bấm tải tay), thống kê, và đóng gói bộ nhỏ để gửi cho Claude.

Cài:      pip install roboflow pillow
API key:  Roboflow -> Settings -> API Keys -> copy "Private API Key"
          Đặt vào biến môi trường (KHÔNG dán vào chat, KHÔNG ghi vào file):
              PowerShell:  $env:ROBOFLOW_API_KEY = "xxxxxxxx"
Chạy:
    python python/roboflow_fetch.py                       # tải version mới nhất, định dạng yolov8
    python python/roboflow_fetch.py --version 1           # chọn version
    python python/roboflow_fetch.py --subset 300          # kích thước bộ nhỏ đóng gói (mặc định 300)
    python python/roboflow_fetch.py --local C:\\duong\\dan  # BỎ QUA API, chỉ phân tích thư mục đã giải nén
Kết quả:
    data/container_roboflow/            dataset đã tải
    result/06_roboflow_dataset.txt      thống kê (số ảnh, số khung mỗi lớp, kích thước khung...)
    result/roboflow_subset.zip          bộ nhỏ (ảnh + nhãn + data.yaml) -> gửi file này cho Claude
"""
import argparse, os, random, re, sys, zipfile
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "result"
RESULT.mkdir(exist_ok=True)
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
lines = []
def log(s=""):
    print(s); lines.append(s)

# ------------------------------------------------------------------ tải qua API
def fetch(args):
    try:
        from roboflow import Roboflow
    except ImportError:
        sys.exit("Chưa cài thư viện: pip install roboflow")
    key = os.environ.get("ROBOFLOW_API_KEY")
    if not key:
        import getpass
        key = getpass.getpass("Nhập Roboflow Private API Key (không hiện khi gõ): ").strip()
    try:
        rf = Roboflow(api_key=key)
        project = rf.workspace(args.workspace).project(args.project)
        versions = project.versions()
    except Exception as e:
        sys.exit(f"Không kết nối được project '{args.workspace}/{args.project}': {type(e).__name__}: {e}\n"
                 "Kiểm tra: (1) API key đúng, (2) slug workspace/project đúng (xem trên thanh địa chỉ app.roboflow.com/<workspace>/<project>/...).")
    if not versions:
        sys.exit("Project CHƯA có version nào để tải. Vào Roboflow -> Versions -> Create New Version "
                 "(Preprocessing: để trống/không resize, Augmentation: KHÔNG chọn) -> chờ tạo xong rồi chạy lại.\n"
                 "Lưu ý: nếu trang Dataset còn báo 'media is being added', đợi nhập đủ 6473 ảnh rồi hãy tạo version.")
    nums = sorted(int(str(v.version).split("/")[-1]) for v in versions)
    ver = args.version or nums[-1]
    log(f"Các version hiện có: {nums} -> dùng version {ver}")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    try:
        ds = project.version(ver).download(args.format, location=str(out), overwrite=False)
    except Exception as e:
        sys.exit(f"Tải thất bại: {type(e).__name__}: {e}")
    return Path(ds.location)

# ------------------------------------------------------------------ đọc dataset
def read_names(yaml_path):
    txt = yaml_path.read_text(encoding="utf-8", errors="replace")
    try:
        import yaml
        d = yaml.safe_load(txt); n = d.get("names")
        return [n[i] for i in sorted(n)] if isinstance(n, dict) else list(n)
    except Exception:
        pass
    m = re.search(r"names:\s*\[(.*?)\]", txt, re.S)
    if m:
        return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    block = re.findall(r"^\s+(\d+):\s*(.+)$", txt, re.M)
    return [v.strip().strip("'\"") for _, v in sorted(block, key=lambda t: int(t[0]))]

def find_splits(root):
    sp = {}
    for name, alias in (("train", "train"), ("valid", "valid"), ("val", "valid"), ("test", "test")):
        d = root / name
        if (d / "images").is_dir():
            sp[alias] = d
    return sp

def source_of(stem):
    """'CAM_OCR_REAR_2025_09_11_..._jpg.rf.abc' -> 'CAM_OCR_REAR'; 'Container-151' -> 'Container'."""
    stem = re.sub(r"[_.]?(jpg|jpeg|png)\.rf\.[0-9a-fA-F]+$", "", stem, flags=re.I)
    toks = [t for t in re.split(r"[_\-.]", stem) if t]
    keep = []
    for t in toks:
        if t.isdigit() and len(t) >= 3 or re.fullmatch(r"\d{2}", t) and keep and len(keep) >= 2:
            break
        if t.isdigit():
            if not keep: break
            keep.append(t); continue
        keep.append(t)
    return "_".join(keep) if keep else "(tên bắt đầu bằng số)"

def analyse(root):
    yamls = list(root.glob("data.yaml")) or list(root.rglob("data.yaml"))
    if not yamls: sys.exit(f"Không thấy data.yaml trong {root}")
    names = read_names(yamls[0])
    splits = find_splits(yamls[0].parent)
    if not splits: sys.exit("Không thấy thư mục train/valid có images/ và labels/")
    log(f"\nDataset: {yamls[0].parent}")
    log(f"Các lớp ({len(names)}): {names}")
    info = {}
    src_count = {}
    total_boxes = Counter(); box_w = defaultdict(list); box_h = defaultdict(list); poly = 0; poly_cls = Counter()
    for sp, d in splits.items():
        imgs = sorted(p for p in (d / "images").iterdir() if p.suffix.lower() in IMG_EXT)
        per_cls = Counter(); has_cls = Counter(); no_label = 0; per_image = {}
        for im in imgs:
            lab = d / "labels" / (im.stem + ".txt")
            boxes = []
            if lab.exists():
                for ln in lab.read_text().splitlines():
                    t = ln.split()
                    if len(t) > 5: poly += 1; poly_cls[int(float(t[0]))] += 1; continue
                    if len(t) == 5:
                        c = int(float(t[0])); boxes.append(c)
                        total_boxes[c] += 1; box_w[c].append(float(t[3])); box_h[c].append(float(t[4]))
            if not boxes: no_label += 1
            for c in boxes: per_cls[c] += 1
            for c in set(boxes): has_cls[c] += 1
            per_image[im] = set(boxes)
        info[sp] = (imgs, per_cls, has_cls, no_label, per_image)
        src_count[sp] = Counter(source_of(im.stem) for im in imgs)
        log(f"\n[{sp}] {len(imgs)} ảnh | không có khung nào: {no_label}")
        for c, n in enumerate(names):
            log(f"   {n:<18} {per_cls[c]:>6} khung | có mặt trong {has_cls[c]:>5} ảnh ({has_cls[c] / max(1, len(imgs)) * 100:4.1f}%)")
    log("\nNGUỒN ẢNH theo tên file (cùng nguồn + cùng ngày ở nhiều tập = nguy cơ rò rỉ train/valid/test):")
    allsrc = sorted(set().union(*[set(c) for c in src_count.values()]), key=lambda k: -sum(c[k] for c in src_count.values()))
    log("   " + "nguồn".ljust(26) + "".join(sp.rjust(8) for sp in src_count))
    for k in allsrc[:12]:
        log("   " + k[:25].ljust(26) + "".join(str(src_count[sp][k]).rjust(8) for sp in src_count))
    if len(allsrc) > 12: log(f"   ... và {len(allsrc) - 12} nguồn khác")
    only_eval = [k for k in allsrc if src_count.get("train", Counter())[k] == 0]
    if only_eval: log(f"   Nguồn KHÔNG có trong train (chỉ ở valid/test): {only_eval[:6]} — tốt cho việc đo khả năng tổng quát")
    log("\nKích thước khung (tỉ lệ so với ảnh, trung bình):")
    for c, n in enumerate(names):
        if box_w[c]:
            log(f"   {n:<18} rộng {sum(box_w[c]) / len(box_w[c]):.3f} · cao {sum(box_h[c]) / len(box_h[c]):.3f}  (n={len(box_w[c])})")
    if poly:
        log(f"\nCẢNH BÁO: {poly} dòng nhãn dạng đa giác (>5 số) KHÔNG nằm trong số khung ở trên — theo lớp: " + ", ".join(f"{names[c]} {n}" for c, n in poly_cls.items()))
        log("   Ultralytics sẽ bỏ cả file nhãn nếu trộn khung + đa giác. Chạy python/prepare_container_dataset.py để đổi đa giác thành khung.")
    # kích thước ảnh
    try:
        from PIL import Image
        sizes = Counter()
        allimgs = [p for sp in info for p in info[sp][0]]
        for im in random.Random(0).sample(allimgs, min(600, len(allimgs))):   # mẫu NGẪU NHIÊN trên mọi tập
            sizes[Image.open(im).size] += 1
        tot = sum(sizes.values()); pano = sum(n for (w, h), n in sizes.items() if w / h > 2.6)
        log(f"\nKích thước ảnh (mẫu ngẫu nhiên {tot}): " + ", ".join(f"{w}x{h}: {n}" for (w, h), n in sizes.most_common(6)) + f" | panorama (rộng/cao>2.6): {pano / tot * 100:.0f}%")
    except Exception:
        pass
    return yamls[0], names, info

# ------------------------------------------------------------------ gói bộ nhỏ
def make_subset(yaml_path, names, info, n, seed):
    rnd = random.Random(seed)
    zpath = RESULT / "roboflow_subset.zip"
    chosen = []
    for sp, share in (("train", 1.0), ("valid", 0.2)):
        if sp not in info: continue
        imgs, _, _, _, per_image = info[sp]
        have = [p for p in imgs if per_image[p]]
        want = max(1, int(n * share))
        # ưu tiên đủ cả 3 lớp: chia đều theo lớp, phần còn lại ngẫu nhiên
        picked = set()
        for c in range(len(names)):
            pool = [p for p in have if c in per_image[p] and p not in picked]
            rnd.shuffle(pool); picked.update(pool[: want // max(1, len(names)) // 2])
        rest = [p for p in have if p not in picked]; rnd.shuffle(rest)
        picked.update(rest[: max(0, want - len(picked))])
        chosen += [(sp, p) for p in sorted(picked)]
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(yaml_path, "data.yaml")
        for sp, p in chosen:
            z.write(p, f"{sp}/images/{p.name}")
            lab = p.parent.parent / "labels" / (p.stem + ".txt")
            if lab.exists(): z.write(lab, f"{sp}/labels/{lab.name}")
    mb = zpath.stat().st_size / 1e6
    log(f"\nĐã đóng gói {len(chosen)} ảnh vào {zpath} ({mb:.1f} MB)")
    if mb > 90: log("  Lớn hơn 90 MB: chạy lại với --subset nhỏ hơn (ví dụ 150) rồi mới gửi.")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="phuc-ngo-3elna")
    ap.add_argument("--project", default="container-ocr-byxl7-tuits")
    ap.add_argument("--version", type=int, default=None)
    ap.add_argument("--format", default="yolov8")
    ap.add_argument("--out", default=str(ROOT / "data" / "container_roboflow"))
    ap.add_argument("--local", default=None, help="Bỏ qua API, phân tích thư mục dataset đã có")
    ap.add_argument("--subset", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    root = Path(args.local) if args.local else fetch(args)
    yaml_path, names, info = analyse(root)
    make_subset(yaml_path, names, info, args.subset, args.seed)
    (RESULT / "06_roboflow_dataset.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n>> Đã ghi: {RESULT / '06_roboflow_dataset.txt'}")

if __name__ == "__main__":
    main()
