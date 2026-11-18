"""
Train YOLO tìm vùng mã trên container (container-number, iso-type, seal), chỉnh cho GPU 4 GB (RTX 3050 Laptop).

Cần: dataset đã làm sạch bằng prepare_container_dataset.py  ->  data/container_clean/data.yaml
Cài PyTorch bản CÓ CUDA (xem README mục 12) rồi:  pip install ultralytics

Chạy:
  python python/train_container_yolo.py --check                     # kiểm tra GPU/PyTorch
  python python/train_container_yolo.py --epochs 3 --name thu        # chạy thử 3 epoch để ĐO thời gian 1 epoch
  python python/train_container_yolo.py --epochs 60                  # train thật
  python python/train_container_yolo.py --epochs 60 --batch -1       # để ultralytics tự chọn batch theo bộ nhớ GPU
Hết bộ nhớ ("CUDA out of memory") thì giảm --batch (8 -> 4 -> 2) hoặc --imgsz (960 -> 800).
Kết quả: result/train_container/<name>/ (weights/best.pt, biểu đồ, ảnh val_batch*_pred.jpg), result/11_train_container.txt
"""
import argparse, sys, time
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "result"; RESULT.mkdir(exist_ok=True)

def check():
    try:
        import torch
    except ImportError:
        print("Chưa cài PyTorch. Xem README mục 12 (cài bản có CUDA)."); return False
    print(f"PyTorch {torch.__version__} | CUDA build: {torch.version.cuda} | GPU dùng được: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print(f"GPU 0: {p.name} | VRAM {p.total_memory / 1e9:.1f} GB")
        return True
    print("PyTorch đang là bản CPU hoặc thiếu driver. Train trên CPU sẽ rất chậm.")
    print("Cài lại bản CUDA theo lệnh trên pytorch.org (chọn Windows, Pip, CUDA), nhớ gỡ bản cũ: pip uninstall torch torchvision")
    return False

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data" / "container_clean" / "data.yaml"))
    ap.add_argument("--model", default="yolov8n.pt", help="yolov8n.pt (khuyên dùng cho 4GB) hoặc yolov8s.pt (cần --batch nhỏ)")
    ap.add_argument("--imgsz", type=int, default=960); ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=60); ap.add_argument("--patience", type=int, default=15)
    ap.add_argument("--workers", type=int, default=2, help="Windows: 0-2 cho ổn định")
    ap.add_argument("--name", default="container"); ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--check", action="store_true"); ap.add_argument("--no-onnx", action="store_true")
    a = ap.parse_args()
    ok = check()
    if a.check: return
    if not ok and not a.cpu: sys.exit("Dừng: không có GPU CUDA. Muốn chạy CPU thật sự thì thêm --cpu (rất chậm).")
    if not Path(a.data).exists(): sys.exit(f"Không thấy {a.data}. Chạy prepare_container_dataset.py trước.")
    try: from ultralytics import YOLO
    except ImportError: sys.exit("Chưa cài ultralytics: pip install ultralytics")

    device = "cpu" if a.cpu else 0
    out = RESULT / "train_container"; lines = []
    log = lambda s: (print(s), lines.append(s))
    log(f"Dữ liệu: {a.data}\nModel {a.model} · imgsz {a.imgsz} · batch {a.batch} · epochs {a.epochs} · thiết bị {device}")
    t0 = time.time()
    model = YOLO(a.model)
    model.train(
        data=a.data, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device=device, workers=a.workers, amp=True,
        patience=a.patience, project=str(out), name=a.name, exist_ok=True, seed=0, plots=True, close_mosaic=10,
        fliplr=0.0,        # KHÔNG lật ngang: chữ bị soi gương, không có thật ngoài đời
        degrees=3.0,       # xoay nhẹ (chữ dọc đã có sẵn trong dữ liệu, không cần xoay mạnh)
        scale=0.4, hsv_v=0.5,   # co giãn vừa phải; thay đổi độ sáng mạnh hơn vì cảnh ban đêm
    )
    log(f"Train xong sau {(time.time() - t0) / 60:.1f} phút")
    best = out / a.name / "weights" / "best.pt"
    if not best.exists(): log("Không thấy best.pt"); return
    m = YOLO(str(best))
    for split in ("val", "test"):
        try:
            r = m.val(data=a.data, imgsz=a.imgsz, batch=max(2, a.batch if a.batch > 0 else 4), split=split, device=device, plots=False, verbose=False)
        except Exception as e:
            log(f"[{split}] bỏ qua: {type(e).__name__}"); continue
        b = r.box
        log(f"\n[{split}] mAP50 {b.map50:.3f} · mAP50-95 {b.map:.3f} · precision {b.mp:.3f} · recall {b.mr:.3f}")
        try:
            for i, c in enumerate(b.ap_class_index):
                p, rc, ap50, ap = b.class_result(i); log(f"   {r.names[int(c)]:<18} P {p:.3f} · R {rc:.3f} · mAP50 {ap50:.3f} · mAP50-95 {ap:.3f}")
        except Exception: pass
    if not a.no_onnx:
        try: path = m.export(format="onnx", imgsz=a.imgsz, nms=True, simplify=True); log(f"\nĐã xuất ONNX (có NMS): {path}")
        except Exception as e:
            log(f"\nXuất ONNX có NMS lỗi ({type(e).__name__}); thử không NMS")
            try: path = m.export(format="onnx", imgsz=a.imgsz, simplify=True); log(f"Đã xuất ONNX (KHÔNG NMS, cần tự lọc khung): {path}")
            except Exception as e2: log(f"Xuất ONNX lỗi: {type(e2).__name__}: {e2}")
    log(f"\nẢnh minh hoạ dự đoán trên tập val: {out / a.name}  (xem val_batch*_pred.jpg đối chiếu val_batch*_labels.jpg)")
    (RESULT / "11_train_container.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f">> Đã ghi: {RESULT / '11_train_container.txt'}")

if __name__ == "__main__":
    main()
