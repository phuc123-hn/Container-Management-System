"""
Cắt VIDEO thành ẢNH để gán nhãn / train, có lọc ảnh mờ và ảnh trùng.

Một video chỉ là chuỗi ảnh. OpenCV đọc từng khung ra thành mảng ảnh trong RAM; script này chọn một phần để lưu.
Không nên lưu mọi khung: 25 khung/giây thì 2 khung liên tiếp gần như giống hệt, train không thêm gì mà tốn công gán nhãn.

Chạy:
  python python/extract_frames.py --video clip.mp4 --fps 2                    # 2 ảnh mỗi giây
  python python/extract_frames.py --video "D:\\videos_cong" --fps 3 --out data/my_frames
  python python/extract_frames.py --video clip.mp4 --fps 3 --min-sharp 60     # bỏ ảnh mờ (xem phân bố độ nét trong báo cáo để chọn ngưỡng)
Kết quả: <out>/<tên video>_<mili-giây>.jpg, <out>/index.csv, result/10_extract_frames.txt
"""
import argparse, csv, sys, time
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import cv2, numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "result"; RESULT.mkdir(exist_ok=True)
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".ts", ".m4v", ".wmv"}

def sharpness(bgr):
    """Phương sai Laplacian: càng cao càng nét. So sánh trong CÙNG camera/độ phân giải, không so tuyệt đối giữa nguồn khác nhau."""
    return float(cv2.Laplacian(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

def small_gray(bgr): return cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (64, 36)).astype(np.float32)

def process(video, out, fps_out, min_sharp, dup_thr, quality, rows, log):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened(): log(f"  KHÔNG MỞ ĐƯỢC: {video}"); return
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0; n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    log(f"\n{video.name}: {fps:.1f} fps gốc, ~{n / fps:.0f}s, {int(cap.get(3))}x{int(cap.get(4))}")
    step = 1.0 / fps_out; next_t = 0.0; idx = 0; saved = skipped_blur = skipped_dup = 0; last = None; sharps = []
    while True:
        if not cap.grab(): break                              # grab() chỉ giải mã, rẻ hơn read(); chỉ retrieve khi cần lấy
        t = idx / fps; idx += 1
        if t + 1e-9 < next_t: continue
        ok, f = cap.retrieve()
        if not ok: continue
        next_t += step
        s = sharpness(f); sharps.append(s)
        if s < min_sharp: skipped_blur += 1; continue
        g = small_gray(f)
        if last is not None and float(np.mean(np.abs(g - last))) < dup_thr: skipped_dup += 1; continue
        last = g
        name = f"{video.stem}_{int(t * 1000):08d}.jpg"
        cv2.imwrite(str(out / name), f, [cv2.IMWRITE_JPEG_QUALITY, quality]); saved += 1
        rows.append([name, video.name, f"{t:.3f}", f"{s:.1f}"])
    cap.release()
    q = np.percentile(sharps, [10, 50, 90]) if sharps else [0, 0, 0]
    log(f"  xem {len(sharps)} khung (cứ {1 / fps_out:.2f}s lấy một) -> LƯU {saved} · bỏ vì mờ {skipped_blur} · bỏ vì giống khung trước {skipped_dup}")
    log(f"  độ nét (Laplacian): p10 {q[0]:.0f} · p50 {q[1]:.0f} · p90 {q[2]:.0f}   (đặt --min-sharp quanh p10-p25 nếu muốn bỏ ảnh mờ)")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, help="File video hoặc thư mục chứa nhiều video")
    ap.add_argument("--out", default=str(ROOT / "data" / "my_frames"))
    ap.add_argument("--fps", type=float, default=2.0, help="Số ảnh lấy mỗi giây (mặc định 2)")
    ap.add_argument("--min-sharp", type=float, default=0.0, help="Bỏ ảnh có độ nét thấp hơn ngưỡng (0 = tắt)")
    ap.add_argument("--dup-thr", type=float, default=3.0, help="Bỏ ảnh giống khung trước (khác biệt trung bình nhỏ hơn ngưỡng, 0 = tắt)")
    ap.add_argument("--quality", type=int, default=95)
    a = ap.parse_args()
    src = Path(a.video); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    videos = sorted(p for p in src.iterdir() if p.suffix.lower() in VIDEO_EXT) if src.is_dir() else [src]
    if not videos: sys.exit("Không thấy video nào.")
    lines = []; log = lambda s: (print(s), lines.append(s)); rows = []
    t0 = time.time(); log(f"Lưu ảnh vào: {out}")
    for v in videos: process(v, out, a.fps, a.min_sharp, a.dup_thr, a.quality, rows, log)
    with open(out / "index.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if f.tell() == 0: w.writerow(["ảnh", "video", "giây", "độ_nét"])
        w.writerows(rows)
    log(f"\nTổng: {len(rows)} ảnh từ {len(videos)} video trong {time.time() - t0:.1f}s")
    (RESULT / "10_extract_frames.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f">> Đã ghi: {RESULT / '10_extract_frames.txt'}")

if __name__ == "__main__":
    main()
