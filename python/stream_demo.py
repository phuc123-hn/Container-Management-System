"""
Xử lý VIDEO / RTSP theo thời gian thực, KHÔNG lưu ảnh ra đĩa:
  luồng đọc (thread riêng) -> khung hình MỚI NHẤT trong RAM -> YOLO tìm vùng -> cắt -> CCT đọc chữ -> vẽ + đo thời gian.
Hiện dùng model BIỂN SỐ XE MÁY (models/plate_yolo.onnx + cct_s_v2_global.onnx) vì container chưa có model.
Khi có model container: đổi 2 file model và lớp cần giữ, phần luồng/đo thời gian giữ nguyên.

Chạy:
  python python/stream_demo.py --make-test-video result/test_video.mp4            # tạo video thử từ ảnh trong data/frames
  python python/stream_demo.py --source result/test_video.mp4 --max-seconds 15    # chạy như thời gian thực
  python python/stream_demo.py --source rtsp://user:pass@IP:554/stream            # camera thật
  python python/stream_demo.py --source video.mp4 --no-realtime                   # xử lý MỌI khung, nhanh hết mức (offline)
Kết quả: result/09_stream_timing.txt (+ result/09_stream_overlay.mp4 nếu bật --save-overlay)
"""
import argparse, sys, threading, time
from collections import Counter
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import cv2, numpy as np, onnxruntime as ort

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "result"; RESULT.mkdir(exist_ok=True)
S = 320                                   # cỡ ảnh YOLO biển số (container sẽ cần 960+)
PROV = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]   # có GPU thì dùng GPU
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"

class Grabber(threading.Thread):
    """Đọc liên tục; chỉ giữ khung MỚI NHẤT. Xử lý chậm thì khung cũ bị bỏ, độ trễ không tích luỹ."""
    def __init__(self, src, realtime):
        super().__init__(daemon=True)
        self.cap = cv2.VideoCapture(src)
        if not self.cap.isOpened(): sys.exit(f"Không mở được nguồn: {src}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.realtime = realtime; self.lock = threading.Lock()
        self.frame = None; self.idx = -1; self.ts = 0.0; self.total = 0; self.ended = False; self.stop = False
    def run(self):
        period = 1.0 / self.fps; nxt = time.perf_counter()
        while not self.stop:
            ok, f = self.cap.read()
            if not ok: self.ended = True; break
            with self.lock:
                self.idx += 1; self.frame = f; self.ts = time.perf_counter(); self.total += 1
            if self.realtime:                       # giả lập camera: phát đúng tốc độ gốc của video
                nxt += period; d = nxt - time.perf_counter()
                if d > 0: time.sleep(d)
                else: nxt = time.perf_counter()
    def latest(self, last_idx):
        with self.lock:
            if self.frame is None or self.idx == last_idx: return None
            return self.idx, self.frame, self.ts

class Detector:
    def __init__(self, path):
        self.s = ort.InferenceSession(str(path), providers=PROV); self.inp = self.s.get_inputs()[0].name
    def __call__(self, bgr, thr=0.25):
        h, w = bgr.shape[:2]; sc = min(S / w, S / h); nw, nh = round(w * sc), round(h * sc); dx, dy = (S - nw) // 2, (S - nh) // 2
        can = np.full((S, S, 3), 114, np.uint8); can[dy:dy + nh, dx:dx + nw] = cv2.resize(bgr, (nw, nh))
        x = (can[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32)) / 255.0
        out = self.s.run(None, {self.inp: np.ascontiguousarray(x)})[0][0]
        res = []
        for x1, y1, x2, y2, sc_, _ in out:
            if sc_ < thr: continue
            res.append((max(0, (x1 - dx) / sc), max(0, (y1 - dy) / sc), min(w, (x2 - dx) / sc), min(h, (y2 - dy) / sc), float(sc_)))
        return res

class Reader:
    def __init__(self, path):
        self.s = ort.InferenceSession(str(path), providers=PROV); self.inp = self.s.get_inputs()[0].name
    def __call__(self, bgr):
        a = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), (128, 64))[None].astype(np.uint8)
        o = self.s.run(["plate"], {self.inp: a})[0][0]; txt = ""; sc = []
        for i in range(10):
            b = int(np.argmax(o[i]))
            if ALPHABET[b] != "_": txt += ALPHABET[b]; sc.append(float(o[i][b]))
        return txt, (sum(sc) / len(sc) if sc else 0.0)

def make_test_video(path):
    files = sorted((ROOT / "data" / "frames").glob("*.jpg"))
    if not files: sys.exit("Không có ảnh trong data/frames")
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (1920, 1080))
    for f in files:
        img = cv2.resize(cv2.imread(str(f)), (1920, 1080))
        for _ in range(25): vw.write(img)             # mỗi ảnh giữ 1 giây
    vw.release(); print(f"Đã tạo video thử {len(files)} giây (slideshow, chỉ để thử đường ống): {path}")

def pct(a, p): return float(np.percentile(a, p)) if len(a) else 0.0

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source"); ap.add_argument("--make-test-video"); ap.add_argument("--max-seconds", type=float, default=20)
    ap.add_argument("--no-realtime", action="store_true"); ap.add_argument("--save-overlay", action="store_true")
    a = ap.parse_args()
    if a.make_test_video: return make_test_video(a.make_test_video)
    if not a.source: ap.error("cần --source hoặc --make-test-video")
    src = int(a.source) if a.source.isdigit() else a.source
    is_file = isinstance(src, str) and not src.lower().startswith(("rtsp://", "http://", "https://", "rtmp://"))
    det = Detector(ROOT / "models" / "plate_yolo.onnx"); rd = Reader(ROOT / "models" / "cct_s_v2_global.onnx")
    print(f"Thiết bị suy luận: {det.s.get_providers()[0]}")
    det(np.zeros((1080, 1920, 3), np.uint8))          # chạy nháp 1 lần cho nóng máy
    g = Grabber(src, realtime=is_file and not a.no_realtime); g.start()
    writer = None; last = -1; processed = 0; t_det = []; t_rd = []; lat = []; reads = Counter(); n_boxes = 0
    t_start = time.perf_counter()
    while time.perf_counter() - t_start < a.max_seconds:
        item = g.latest(last)
        if item is None:
            if g.ended: break
            time.sleep(0.002); continue
        last, frame, ts = item
        try:                                          # 1 khung lỗi không được làm dừng cả luồng
            t0 = time.perf_counter(); boxes = det(frame); t1 = time.perf_counter(); vis = frame.copy() if a.save_overlay else None
            for x1, y1, x2, y2, sc in boxes:
                bw, bh = x2 - x1, y2 - y1; px, py = max(8, bw * .07), max(6, bh * .12)
                crop = frame[max(0, int(y1 - py)):int(y2 + py), max(0, int(x1 - px)):int(x2 + px)]
                if crop.size == 0: continue
                txt, cf = rd(crop); n_boxes += 1; reads[txt] += 1
                if vis is not None:
                    cv2.rectangle(vis, (int(x1), int(y1)), (int(x2), int(y2)), (80, 200, 80), 3)
                    cv2.putText(vis, f"{txt} {cf:.2f}", (int(x1), max(30, int(y1) - 8)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (80, 200, 80), 3)
            t2 = time.perf_counter()
        except Exception as e:
            print(f"khung {last} lỗi, bỏ qua: {type(e).__name__}: {e}", file=sys.stderr); continue
        processed += 1; t_det.append((t1 - t0) * 1000); t_rd.append((t2 - t1) * 1000); lat.append((t2 - ts) * 1000)
        if vis is not None:
            if writer is None:
                writer = cv2.VideoWriter(str(RESULT / "09_stream_overlay.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 5, (1280, 720))
            writer.write(cv2.resize(vis, (1280, 720)))
    g.stop = True; el = time.perf_counter() - t_start
    if writer: writer.release()
    dropped = max(0, g.total - processed)
    L = [f"Nguồn: {a.source}  | tốc độ gốc {g.fps:.1f} fps | chế độ: {'thời gian thực (phát đúng tốc độ gốc)' if g.realtime else 'nhanh hết mức / luồng sống'}",
         f"Thời gian chạy {el:.1f}s | đọc được {g.total} khung | XỬ LÝ {processed} khung ({processed / el:.1f} fps) | BỎ {dropped} khung ({dropped / max(1, g.total) * 100:.0f}%)",
         f"Tìm vùng (YOLO): trung bình {np.mean(t_det) if t_det else 0:.0f} ms | p95 {pct(t_det, 95):.0f} ms",
         f"Đọc chữ (CCT), cả khung: trung bình {np.mean(t_rd) if t_rd else 0:.0f} ms | p95 {pct(t_rd, 95):.0f} ms | tổng {n_boxes} vùng",
         f"ĐỘ TRỄ (từ lúc khung vào RAM đến lúc có kết quả): p50 {pct(lat, 50):.0f} ms | p95 {pct(lat, 95):.0f} ms | tối đa {max(lat) if lat else 0:.0f} ms",
         "Kết quả đọc nhiều nhất: " + ", ".join(f"{t or '(trống)'}×{n}" for t, n in reads.most_common(6)),
         "Ghi chú: model là BIỂN SỐ XE MÁY; số liệu thời gian là của MÁY BẠN chạy, không phải của sandbox."]
    print("\n".join(L)); (RESULT / "09_stream_timing.txt").write_text("\n".join(L) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
