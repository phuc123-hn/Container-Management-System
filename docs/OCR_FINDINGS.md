# OCR (CCT-S v2) — phát hiện & quyết định kỹ thuật

> Test thật trên 33/36 biển (3 biển loại khỏi tính điểm vì ảnh loá sáng, tự đọc bằng mắt
> không chắc chắn — xem `ocr_crops/clip3.2_new_{16,17,18}__*`). Ground truth đọc thủ công từ
> ảnh gốc, không phải suy luận ngược từ output model.

## Quyết định chính: bỏ `gheHang` (ghép hàng trên/dưới)

| Cách | Exact-match | Char-acc |
|---|---|---|
| CCT + ghép hàng (đúng alpr.js hiện có) | 0% | 52.4% |
| **CCT, resize thẳng (không ghép)** | **97.0% (Python) / 93.9% (Node thật)** | 97.6% / 97.3% |
| Tesseract PSM=6 (đúng config alpr.js) | 0% | 16.8% |

Nguyên nhân nhiều khả năng: mỗi nửa biển 2 dòng tỉ lệ ~2.4:1, ép vào ô vuông 64×64 méo chữ
nặng; resize thẳng cả biển (~1.2:1) vào 128×64 chỉ méo nhẹ. Đã xem ảnh 128×64 sau tiền xử lý
bằng mắt, ghép đúng vị trí — không phải bug code, nhiều khả năng là đặc tính model.

**Tin tốt:** code thật (`docBienChuyen`) vốn đã thử CẢ 2 cách cho mỗi candidate 2 dòng, lấy
confidence cao nhất — hệ thống production nhiều khả năng đã tự né được phần tệ này. Khuyến
nghị: bỏ hẳn nhánh `ghe:true` — nhanh hơn (bớt 1 lần inference/candidate), và theo số liệu
không có lý do giữ lại.

## Độ bền (robustness) — CCT chịu mờ/thiếu sáng khá tốt

| Điều kiện | Exact-match |
|---|---|
| Gốc | 97.0% |
| Blur nặng (radius=4) | 84.8% |
| Thu nhỏ còn 25% rồi phóng lại | 87.9% |
| Thiếu sáng nặng (×0.3 brightness) | 93.9% |

OCR bền hơn nhiều so với detection khi mô phỏng "xe xa" — vì OCR luôn nhận 1 crop đã cố định
kích thước 128×64, không phải tìm vật nhỏ trong ảnh lớn như detection. Củng cố kết luận trước:
ROI (crop đúng vùng xe/biển trước) là đòn bẩy chính, không phải cải thiện OCR tự thân.

## Tốc độ

~26ms/ảnh (Python, chỉ inference) · ~23ms/ảnh (Node thật, gồm cả decode canvas) — nhanh, không
phải điểm nghẽn của pipeline.

## Lệch nhẹ Python vs Node (minh bạch, không giấu)

2/33 ảnh cho kết quả khác nhau giữa test Python (PIL resize) và test Node thật
(`@napi-rs/canvas` resize) — "66P180575" thay vì "66P189575", "8436217" thay vì "84B136217".
Cách resize khác nhau một chút ở vài pixel biên có thể đẩy quyết định argmax lệch ở model vốn
đã khá nhạy. Không ảnh hưởng kết luận chính, nhưng cần nhớ: số đo CHÍNH XÁC phụ thuộc runtime
thật (browser canvas) cuối cùng dùng, không chỉ tin theo 1 lần test duy nhất.

## Giới hạn

- Chỉ 6 biển vật lý khác nhau (33 crop lặp lại qua nhiều khung hình) — chưa đủ đa dạng để
  khẳng định chắc "97% là con số thật cho sản xuất", chỉ đủ để khẳng định "ghép hàng tệ hơn
  hẳn không ghép" (so sánh tương đối, ít nhạy với cỡ mẫu nhỏ hơn số tuyệt đối).
- Chưa test trên biển ô tô/xe tải 1 dòng (use-case chính của SmartPort) — toàn bộ data vẫn là
  xe máy 2 dòng mượn tạm.
- Chưa test trong browser thật (ORT Web/WebGPU), chỉ Node (`onnxruntime-node`, CPU).
