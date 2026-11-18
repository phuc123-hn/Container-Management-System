"""
KIỂM TRA ĐƯỜNG ỐNG:  VIDEO -> cắt khung ảnh -> chạy MÔ HÌNH ĐÃ TRAIN -> vẽ kết quả + cắt vùng + báo cáo.

Mặc định dùng Ultralytics với file .pt/.onnx của bạn (ví dụ result/train_container/thu/weights/best.pt).

Chạy:
  # 1) Chưa có video? Tạo video thử từ ảnh val (mỗi ảnh giữ 1 giây; chỉ để thử đường ống, không giống video thật)
  python python/test_video_model.py --make-test-video result/test_video.mp4 --images data/container_clean/valid/images
  # 2) Chạy mô hình trên video, mỗi giây lấy 3 khung
  python python/test_video_model.py --source result/test_video.mp4 --model result/train_container/thu/weights/best.pt --imgsz 960 --fps 3
  # 3) Video thật từ camera/điện thoại, có theo dõi ID từng xe (tuỳ chọn)
  python python/test_video_model.py --source "D:/videos/clip.mp4" --model best.pt --imgsz 960 --fps 3 --track
Kết quả (result/12_video_test/):
  annotated.mp4        video chỉ gồm các khung đã xử lý, có khung + nhãn
  frames/_tong_hop.jpg ảnh tổng hợp các khung mẫu     crops/  vùng cắt tốt nhất mỗi lớp (dùng cho bước đọc chữ)
  và result/12_video_test.txt (báo cáo: số khung, số vùng, thời gian)
"""
import argparse, json, re, sys, time
from collections import Counter, defaultdict
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import cv2, numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "result"; RESULT.mkdir(exist_ok=True)
COLORS = [(80, 200, 80), (60, 200, 250), (250, 160, 60), (200, 90, 220), (90, 90, 240)]   # BGR

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
class ImageCap:
    """Một ẢNH đơn lẻ chạy qua đúng đường ống video (coi như video chỉ có 1 khung)."""
    def __init__(self, path): self.img = cv2.imread(str(path)); self.done = False
    def isOpened(self): return self.img is not None
    def get(self, prop): return {cv2.CAP_PROP_FPS: 1.0, cv2.CAP_PROP_FRAME_COUNT: 1, 3: self.img.shape[1], 4: self.img.shape[0]}.get(prop, 0)
    def grab(self):
        if self.done: return False
        self.done = True; return True
    def retrieve(self): return True, self.img
    def release(self): pass

# ---------------------------------------------------------------- backend 1: Ultralytics (.pt / .onnx của bạn)
class UltralyticsDet:
    def __init__(self, path, imgsz, conf, device, track):
        from ultralytics import YOLO
        if device is None:
            try:
                import torch; device = 0 if torch.cuda.is_available() else "cpu"
            except Exception: device = "cpu"
        self.m = YOLO(str(path)); self.imgsz, self.conf, self.device, self.track = imgsz, conf, device, track
        self.half = False   # tham số half bị Ultralytics đánh dấu lỗi thời và in cảnh báo mỗi khung
        self.names = self.m.names; self.info = f"Ultralytics · {Path(path).name} · imgsz {imgsz} · thiết bị {device}"
    def __call__(self, bgr):
        kw = dict(imgsz=self.imgsz, conf=self.conf, device=self.device, verbose=False)
        if self.half: kw["half"] = True
        r = (self.m.track(bgr, persist=True, tracker="bytetrack.yaml", **kw) if self.track else self.m.predict(bgr, **kw))[0]
        if r.boxes is None or len(r.boxes) == 0: return []
        xyxy = r.boxes.xyxy.cpu().numpy(); cf = r.boxes.conf.cpu().numpy(); cl = r.boxes.cls.cpu().numpy().astype(int)
        ids = r.boxes.id.cpu().numpy().astype(int) if (self.track and r.boxes.id is not None) else [None] * len(cl)
        return [(*map(float, b), float(c), int(k), (int(i) if i is not None else None)) for b, c, k, i in zip(xyxy, cf, cl, ids)]

# ---------------------------------------------------------------- backend 2: ONNX có NMS sẵn [1,300,6] (để thử không cần PyTorch)
class OnnxNmsDet:
    def __init__(self, path, imgsz, conf, names):
        import onnxruntime as ort
        prov = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
        self.s = ort.InferenceSession(str(path), providers=prov); self.inp = self.s.get_inputs()[0].name
        self.S, self.conf = imgsz, conf; self.names = {i: n for i, n in enumerate(names)}
        self.info = f"ONNX (NMS sẵn) · {Path(path).name} · imgsz {imgsz} · {self.s.get_providers()[0]}"
    def __call__(self, bgr):
        S = self.S; h, w = bgr.shape[:2]; sc = min(S / w, S / h); nw, nh = round(w * sc), round(h * sc); dx, dy = (S - nw) // 2, (S - nh) // 2
        can = np.full((S, S, 3), 114, np.uint8); can[dy:dy + nh, dx:dx + nw] = cv2.resize(bgr, (nw, nh))
        x = np.ascontiguousarray(can[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        out = self.s.run(None, {self.inp: x})[0][0]; res = []
        for x1, y1, x2, y2, c, k in out:
            if c >= self.conf: res.append((max(0, (x1 - dx) / sc), max(0, (y1 - dy) / sc), min(w, (x2 - dx) / sc), min(h, (y2 - dy) / sc), float(c), int(k), None))
        return res

# ---------------------------------------------------------------- đọc chữ trên vùng cắt (mốc tạm: RapidOCR/Tesseract + kiểm tra ISO 6346)
def make_reader():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import baseline_container_ocr as B
    except Exception as e:
        print(f"CẢNH BÁO: không nạp được bộ đọc chữ: {type(e).__name__}: {e}", flush=True); return None
    eng = B.make_engines()
    if not eng: print("CẢNH BÁO: chưa có engine OCR (pip install rapidocr-onnxruntime); bỏ qua bước đọc chữ", flush=True); return None
    print(f"Bộ đọc chữ: {list(eng)} (mốc tạm, chưa phải mô hình riêng của dự án)", flush=True); return B, eng

def read_crop(rd, crop_bgr):
    from PIL import Image
    B, eng = rd; pil = Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)); vert = pil.height > 1.5 * pil.width; raws = []
    for name, fn in eng.items():
        try: raws.append(fn(pil, vert))
        except Exception as e: print(f"  engine {name} lỗi: {type(e).__name__}", flush=True)
    cat, info = B.classify(raws)
    if cat == "A": return cat, info, "HỢP LỆ"
    if cat in ("B1", "B2"): return cat, info, "CHƯA XÁC NHẬN"
    raw = " ".join(re.sub(r"\s+", " ", r).strip() for r in raws).strip()[:30]
    return cat, raw, ("MỘT PHẦN" if cat == "C" else "KHÔNG ĐỌC ĐƯỢC")
ASCII = {"HỢP LỆ": "HOP LE", "CHƯA XÁC NHẬN": "CHUA XAC NHAN", "MỘT PHẦN": "MOT PHAN", "KHÔNG ĐỌC ĐƯỢC": "KHONG DOC DUOC", "KHÔNG CÓ VÙNG": "KHONG CO VUNG"}

# ---------------------------------------------------------------- tiện ích
def make_test_video(path, images_dir, hold):
    files = sorted(p for p in Path(images_dir).iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not files: sys.exit(f"Không có ảnh trong {images_dir}")
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (1920, 1080))
    for f in files:
        im = cv2.imread(str(f)); h, w = im.shape[:2]; s = min(1920 / w, 1080 / h)
        r = cv2.resize(im, (round(w * s), round(h * s))); can = np.zeros((1080, 1920, 3), np.uint8)
        y0, x0 = (1080 - r.shape[0]) // 2, (1920 - r.shape[1]) // 2; can[y0:y0 + r.shape[0], x0:x0 + r.shape[1]] = r
        for _ in range(int(25 * hold)): vw.write(can)
    vw.release(); print(f"Đã tạo video thử từ {len(files)} ảnh (~{len(files) * hold:.0f}s): {path}\nLưu ý: đây là slideshow ảnh tĩnh, KHÔNG có chuyển động/nhoè như video thật.")

def draw(frame, dets, names, scale, extra=None):
    vis = frame.copy(); lw = max(2, round(max(frame.shape[:2]) / 600))
    for i, (x1, y1, x2, y2, c, k, tid) in enumerate(dets):
        col = COLORS[k % len(COLORS)]; cv2.rectangle(vis, (int(x1), int(y1)), (int(x2), int(y2)), col, lw)
        lab = f"{names.get(k, k)} {c:.2f}" + (f" #{tid}" if tid is not None else "") + ((" | " + re.sub(r"[^A-Za-z0-9 +:]", "", extra[i])[:26]) if extra and i in extra else "")
        fs = max(0.6, max(frame.shape[:2]) / 1400); (tw, th), _ = cv2.getTextSize(lab, cv2.FONT_HERSHEY_SIMPLEX, fs, 2)
        ty = max(th + 6, int(y1)); cv2.rectangle(vis, (int(x1), ty - th - 6), (int(x1) + tw + 6, ty), col, -1)
        cv2.putText(vis, lab, (int(x1) + 3, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), 2)
    return vis

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source"); ap.add_argument("--model"); ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--conf", type=float, default=0.25); ap.add_argument("--fps", type=float, default=3.0, help="Số khung lấy mỗi giây video")
    ap.add_argument("--device", default=None); ap.add_argument("--track", action="store_true")
    ap.add_argument("--max-seconds", type=float, default=0, help="Chỉ xử lý N giây đầu của video (0 = hết)")
    ap.add_argument("--backend", choices=["ultralytics", "onnx"], default="ultralytics")
    ap.add_argument("--names", default="container-number,iso-type,seal", help="(backend onnx) tên lớp, cách nhau dấu phẩy")
    ap.add_argument("--read", action="store_true", help="Đọc chữ trên vùng container-number (1 ảnh, 1 chữ)"); ap.add_argument("--read-top", type=int, default=2)
    ap.add_argument("--read-classes", default="container-number"); ap.add_argument("--save-cut", action="store_true", help="Lưu ảnh cắt từ video vào frames_cut/")
    ap.add_argument("--make-test-video"); ap.add_argument("--images"); ap.add_argument("--hold", type=float, default=1.0)
    a = ap.parse_args()
    if a.make_test_video:
        if not a.images: ap.error("--make-test-video cần --images <thư mục ảnh>")
        return make_test_video(a.make_test_video, a.images, a.hold)
    if not a.source or not a.model: ap.error("cần --source và --model")
    src = int(a.source) if a.source.isdigit() else a.source
    dev = None if a.device is None else (a.device if a.device == "cpu" else int(a.device))
    try:
        det = (OnnxNmsDet(a.model, a.imgsz, a.conf, a.names.split(",")) if a.backend == "onnx" else UltralyticsDet(a.model, a.imgsz, a.conf, dev, a.track))
    except ImportError as e:
        sys.exit(f"Thiếu thư viện: {e}. Cài: pip install ultralytics")
    cap = ImageCap(src) if (isinstance(src, str) and Path(src).suffix.lower() in IMG_EXT) else cv2.VideoCapture(src)
    if not cap.isOpened(): sys.exit(f"Không mở được video: {a.source}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0; n_tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W, H = int(cap.get(3)), int(cap.get(4)); out_dir = RESULT / "12_video_test"
    for sub in ("frames", "crops", "frames_cut", "frames_processed"): (out_dir / sub).mkdir(parents=True, exist_ok=True)
    try: det(np.zeros((H, W, 3), np.uint8))                 # chạy nháp cho nóng máy
    except Exception as e:
        hint = ("File này là bộ ĐỌC CHỮ (cct_s_v2_global.onnx), KHÔNG phải mô hình tìm vùng. Chọn best.pt đã train hoặc plate_yolo.onnx." if "uint8" in str(e)
                else "Kiểm tra file model, loại model (Ultralytics/ONNX) và cỡ ảnh.")
        sys.exit(f"LỖI khi chạy thử mô hình: {type(e).__name__}: {str(e)[:300]}\n=> {hint}")
    rd = make_reader() if a.read else None; read_cls = set(a.read_classes.split(",")); recs = []
    vw = None; step = 1.0 / a.fps; next_t = 0.0; idx = 0; processed = 0; times = []
    per_cls = defaultdict(lambda: {"frames": 0, "n": 0, "conf": []}); ids = defaultdict(set); best = defaultdict(list); samples = []
    print(f"Video: {W}x{H}, {fps:.1f} fps gốc, ~{n_tot / fps:.0f}s | {det.info}", flush=True)
    while True:
        if not cap.grab(): break
        t = idx / fps; idx += 1
        if a.max_seconds and t > a.max_seconds: break
        if t + 1e-9 < next_t: continue
        ok, frame = cap.retrieve()
        if not ok: continue
        next_t += step; t0 = time.perf_counter()
        try: dets = det(frame)
        except Exception as e: print(f"khung {idx} lỗi, bỏ qua: {type(e).__name__}: {e}", file=sys.stderr); continue
        times.append((time.perf_counter() - t0) * 1000); processed += 1
        if processed % 10 == 0: print(f"  ... đã xử lý {processed} khung (video {t:.1f}s, {np.mean(times[-10:]):.0f} ms/khung)", flush=True)
        fname = f"f{processed:05d}_t{t:07.2f}.jpg"; extra = {}; bestr = None
        if rd is not None:
            cand = sorted([(i, d) for i, d in enumerate(dets) if det.names.get(d[5]) in read_cls], key=lambda x: -x[1][4])[:a.read_top]
            for i, (x1, y1, x2, y2, c, k, tid) in cand:
                bw, bh = x2 - x1, y2 - y1; crop = frame[max(0, int(y1 - .06 * bh)):int(y2 + .06 * bh), max(0, int(x1 - .06 * bw)):int(x2 + .06 * bw)]
                if crop.size == 0: continue
                cat, txt, st = read_crop(rd, crop); extra[i] = txt; rk = ("A", "B1", "B2", "C", "D").index(cat)
                if bestr is None or (rk, -c) < (bestr[0], -bestr[1]): bestr = (rk, c, cat, txt, st, tid)
            recs.append({"file": fname, "t": round(t, 2), "boxes": len(dets), "text": bestr[3] if bestr else "", "status": bestr[4] if bestr else "KHÔNG CÓ VÙNG", "cat": bestr[2] if bestr else "-", "tid": bestr[5] if bestr else None})
            print(f"  ảnh {fname}: {recs[-1]['text'] or '-'}  [{recs[-1]['status']}]", flush=True)
        vis = draw(frame, dets, det.names, 1, extra)
        if rd is not None:
            r = recs[-1]; cv2.rectangle(vis, (0, H - 90), (W, H), (0, 0, 0), -1)
            cv2.putText(vis, f"{r['text']}  [{ASCII.get(r['status'], r['status'])}]", (20, H - 28), cv2.FONT_HERSHEY_SIMPLEX, max(1.0, W / 1400), (255, 255, 255), 3)
        if a.save_cut: cv2.imwrite(str(out_dir / "frames_cut" / fname), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        cv2.imwrite(str(out_dir / "frames_processed" / fname), vis if W <= 1600 else cv2.resize(vis, (1600, int(1600 * H / W))), [cv2.IMWRITE_JPEG_QUALITY, 85])
        cv2.putText(vis, f"t={t:.2f}s  khung {idx}  {len(dets)} vung", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, max(0.8, W / 1600), (255, 255, 255), 2)
        if vw is None: vw = cv2.VideoWriter(str(out_dir / "annotated.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 5, (1280, int(1280 * H / W)))
        small = cv2.resize(vis, (1280, int(1280 * H / W))); vw.write(small)
        if dets: samples.append((len(dets), t, small))
        seen = set()
        for x1, y1, x2, y2, c, k, tid in dets:
            nm = det.names.get(k, str(k)); d = per_cls[nm]; d["n"] += 1; d["conf"].append(c); seen.add(nm)
            if tid is not None: ids[nm].add(tid)
            pad = 0.06; bw, bh = x2 - x1, y2 - y1
            crop = frame[max(0, int(y1 - pad * bh)):int(y2 + pad * bh), max(0, int(x1 - pad * bw)):int(x2 + pad * bw)]
            if crop.size: best[nm].append((c, t, crop, tid))
        for nm in seen: per_cls[nm]["frames"] += 1
    cap.release()
    if vw: vw.release()
    # ---- crops tốt nhất mỗi lớp (độ tin cậy cao nhất) + ảnh tổng hợp khung mẫu
    for nm, lst in best.items():
        for rank, (c, t, crop, tid) in enumerate(sorted(lst, key=lambda x: -x[0])[:30]):
            fn = f"{nm}_{rank:02d}_t{t:07.2f}_c{c:.2f}" + (f"_id{tid}" if tid is not None else "") + ".jpg"
            cv2.imwrite(str(out_dir / "crops" / fn), crop)
    pick = sorted(samples, key=lambda x: x[1])
    if len(pick) > 12: pick = [pick[int(i * (len(pick) - 1) / 11)] for i in range(12)]
    if pick:
        tw = 560; tiles = [cv2.resize(s[2], (tw, int(tw * s[2].shape[0] / s[2].shape[1]))) for s in pick]
        cols = 3; rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]; rh = [max(t.shape[0] for t in r) for r in rows]
        sheet = np.full((sum(rh) + 6 * len(rows) + 6, cols * (tw + 6) + 6, 3), (23, 6, 2), np.uint8); y = 6
        for r, h in zip(rows, rh):
            for i, t in enumerate(r): sheet[y:y + t.shape[0], 6 + i * (tw + 6):6 + i * (tw + 6) + t.shape[1]] = t
            y += h + 6
        cv2.imwrite(str(out_dir / "frames" / "_tong_hop.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    # ---- báo cáo
    L = [f"Video: {a.source} | {W}x{H} | {fps:.1f} fps gốc | {n_tot / fps:.0f}s", f"Mô hình: {det.info}",
         f"Cắt khung: đọc {idx} khung, LẤY {processed} khung (mục tiêu {a.fps:g} khung/giây) -> {'ĐƯỜNG ỐNG CẮT KHUNG HOẠT ĐỘNG' if processed else 'KHÔNG LẤY ĐƯỢC KHUNG NÀO'}",
         f"Thời gian mô hình mỗi khung: trung bình {np.mean(times) if times else 0:.0f} ms · p95 {np.percentile(times, 95) if times else 0:.0f} ms · tối đa {max(times) if times else 0:.0f} ms",
         f"Tốc độ thực tế: {1000 / np.mean(times) if times else 0:.1f} khung/giây (chưa tính đọc/ghi video)", "", "Kết quả theo lớp (ngưỡng conf %.2f):" % a.conf]
    for nm, d in sorted(per_cls.items()):
        L.append(f"  {nm:<18} {d['n']:>5} vùng · có mặt trong {d['frames']}/{processed} khung ({d['frames'] / max(1, processed) * 100:.0f}%) · conf trung bình {np.mean(d['conf']):.2f}" + (f" · {len(ids[nm])} ID khác nhau" if ids[nm] else ""))
    if not per_cls: L.append("  (không phát hiện gì: kiểm tra --model có đúng loại, --imgsz, hạ --conf)")
    final = []
    if rd is not None:
        from collections import Counter as _C
        grp = defaultdict(list)
        for r in recs:
            if r["cat"] == "A": grp[r["tid"] if r["tid"] is not None else "tất cả"].append(r["text"])
        for g, codes in grp.items():
            code, nv = _C(codes).most_common(1)[0]
            final.append({"group": f"xe #{g}" if g != "tất cả" else "cả video", "code": code, "votes": nv, "note": f"{nv}/{len(codes)} khung hợp lệ cùng mã" + ("" if nv >= 2 else " (mới 1 khung: chưa đủ tin cậy, cần ≥2)")})
        L += ["", "KẾT QUẢ CUỐI: " + ("; ".join(f"{f['code']} ({f['group']}, {f['note']})" for f in final) if final else "chưa có mã hợp lệ nào (xem từng ảnh trong results.csv)")]
        import csv
        with open(out_dir / "results.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh); w.writerow(["ảnh", "giây", "số vùng", "chữ đọc được", "trạng thái"]); [w.writerow([r["file"], r["t"], r["boxes"], r["text"], r["status"]]) for r in recs]
    (out_dir / "results.json").write_text(json.dumps({"final": final, "frames": recs, "cut": bool(a.save_cut)}, ensure_ascii=False), encoding="utf-8")
    L += ["", f"Ảnh cắt từ video: {out_dir / 'frames_cut'}", f"Ảnh đã xử lý: {out_dir / 'frames_processed'}", f"Ảnh: {out_dir / 'frames' / '_tong_hop.jpg'}", f"Video có khung: {out_dir / 'annotated.mp4'}", f"Vùng cắt: {out_dir / 'crops'} (30 cái tin cậy nhất mỗi lớp)"]
    print("\n".join(L)); (RESULT / "12_video_test.txt").write_text("\n".join(L) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
