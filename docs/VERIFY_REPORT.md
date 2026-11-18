# Verify độc lập bộ fix (data.yaml, train_yolo.py, colab_train.py, plate-detector.js)

> Không tin theo báo cáo — chạy lại thật từng phần trong sandbox, có real ultralytics 8.4.161,
> Node v22, best.onnx thật. Kết quả dưới đây từ các lệnh chạy thật, xem lại trong lịch sử tool
> call của phiên làm việc.

## 1. Python (`train_yolo.py`) — chạy thật 3 epoch, PASS toàn bộ

```
python3 train_yolo.py --epochs 3 --imgsz 320 --device cpu --name verify_run
```

- ✅ `data.yaml` không có `path:` tuyệt đối — Ultralytics tự resolve đúng theo thư mục chứa
  file, train/val tương đối chạy được, không lỗi.
- ✅ `Path(model.trainer.save_dir) / "weights" / "best.pt"` — lấy đúng path thật, không phải
  đường dẫn viết cứng như bản cũ.
- ✅ Export `nms=True` → ONNX ra đúng `input [1,3,320,320]`, `output [1,300,6]`.
- ✅ `verify_onnx()` tự chạy, in đúng dòng xác nhận `✅ ONNX hợp lệ...`.

Không phát hiện lỗi nào trong 3 điểm reviewer báo là "chưa kiểm chứng vì hết đĩa".

## 2. JS (`plate-detector.js` + `test-node.mjs`) — reproduce chính xác

Cài `onnxruntime-node` qua `npm i --ignore-scripts` (đúng như reviewer làm) — có sẵn binary
CPU cho `linux/x64` trong chính package, không cần postinstall tải thêm gì. Chạy
`test-node.mjs` với `best.onnx` thật (cùng file dùng để đánh giá trước đó):

| | TP | FP | FN | P | R |
|---|---|---|---|---|---|
| `edgePolicy='keep'` | 36 | 20 | 0 | 0.643 | 1.000 |
| `edgePolicy='reject'` (mặc định) | 32 | 0 | 4 | 1.000 | 0.889 |

**Khớp chính xác 100%** với số reviewer báo cáo — kể cả timing (~20ms/ảnh). Phần mô phỏng
"xe ở xa" (thu nhỏ 0.35/0.25/0.15, so ROI vs cả khung) cũng ra đúng số y hệt.

## 3. Đối chiếu claim tích hợp với `alpr.js` THẬT (tải lại, không dùng trí nhớ cũ)

```
md5sum alpr.js  →  f9a2f41388d6f42941ca9dfe884e4c54  (giống hệt bản đọc lần trước, chưa đổi)
```

| Claim trong `plate-detector.js` | Thực tế trong `alpr.js` | Khớp? |
|---|---|---|
| Output `o.dims[1]`, dạng `[1,300,6]` | Dòng 231: `for (var k = 0; k < o.dims[1]; k++)` | ✅ |
| Letterbox `scale = min(S/w, S/h)` | Dòng 210: `sc = Math.min(INPUT/w, INPUT/h)` | ✅ |
| Letterbox `padX/padY` = `(S-newW)/2` | Dòng 212: `dx = (INPUT-nw)/2, dy = (INPUT-nh)/2` | ✅ |

**Phát hiện thêm (chưa ai nhắc tới):** hàm phát hiện xe thật trả về đúng
`{x1,y1,x2,y2,score,loai}` (dòng ~234) — **khớp chính xác** format `roi` mà
`PlateDetector.detect(img, {roi})` đang nhận. Tích hợp thật sự chỉ là:

```js
const vehicleBox = await detectVehicle(imgEl);       // hàm có sẵn trong alpr.js
const { plates } = await plateDetector.detect(imgEl, { roi: vehicleBox });  // cắm thẳng
```

Không cần lớp chuyển đổi toạ độ nào ở giữa.

## 4. `results.csv` lặp cặp epoch — điều tra thêm, CHƯA tìm ra nguyên nhân gốc

Đọc source `ultralytics/engine/trainer.py` dòng 638:
`if self.args.val or final_epoch or self.stopper.possible_stop or self.stop:` — điều kiện
validate mỗi epoch, không thấy logic "cứ 2 epoch mới validate 1 lần" tường minh.

**Test thực nghiệm để kiểm chứng:** run 3-epoch vừa làm ở mục 1 — **KHÔNG hề lặp cặp**, cả
3 dòng khác nhau hoàn toàn. Vậy hiện tượng lặp cặp ở bản 50-epoch gốc không phải hành vi mặc
định đơn giản theo epoch chẵn/lẻ — có yếu tố khác (nghi vấn: tương tác giữa EMA
`decay=0.9999, tau=2000` với dataset quá nhỏ, nhưng chưa chứng minh được bằng công thức).

**Kết luận thật:** không tìm ra nguyên nhân gốc trong thời gian đã bỏ ra. Không ảnh hưởng tới
tính hợp lệ của số cuối cùng (đã reproduce độc lập qua ONNX ở mục 2), chỉ ảnh hưởng tới việc
nói chính xác "epoch nào" đạt số đó — epoch 48 và 49 có số giống hệt nhau nên chỉ nên nói
"khoảng epoch 48-49", không nên chỉ đích danh epoch 48.

## Việc chưa làm

- Chưa test `plate-detector.js` thật trong trình duyệt (ORT Web/WebGPU) — chỉ mới Node/CPU.
- License AGPL-3.0 vẫn treo, chưa ai (kể cả mình) có tư cách quyết định — cần hỏi người có
  chuyên môn pháp lý như đã thống nhất.
