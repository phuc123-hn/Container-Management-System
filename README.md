# SmartPort ALPR — test & xuất ảnh kết quả

Gộp 2 phần vào 1 project:
- **YOLO** (`models/plate_yolo.onnx`): tìm vị trí biển số trên ảnh toàn cảnh.
- **CCT-S v2** (`models/cct_s_v2_global.onnx`) + `src/plate-reader.js`: đọc ký tự trên biển.

Mọi kết quả tự ghi vào thư mục **`result/`** (file `.txt` ghi bằng UTF-8, không bị lỗi font/mã hoá như khi dùng `>` trong PowerShell).

## 1. Cài đặt (làm 1 lần)

Mở PowerShell **trong thư mục project này** (thư mục có `package.json`):

```powershell
npm run setup                                 # cài onnxruntime-node + @napi-rs/canvas
pip install onnxruntime pillow numpy          # chỉ cần nếu muốn chạy phần Python
```

> Mẹo: nếu đã có `node_modules` từ thư mục `smartport-ocr` cũ, chép nguyên thư mục đó sang đây rồi bỏ qua `npm run setup`.

Tesseract **không bắt buộc**. Chưa cài thì phần so sánh với Tesseract tự bỏ qua, không báo lỗi.

## 2. Chạy

```powershell
npm run all                       # chạy cả 3 phần Node bên dưới, ~10 giây
python python\test_python.py      # phần Python (so sánh cách ghép hàng, Tesseract, độ bền)
```

Chạy lẻ từng phần:

| Lệnh | Làm gì |
|---|---|
| `npm test` | Đọc 36 crop biển, chấm exact-match / char-acc |
| `npm run visual` | Mỗi crop thành 1 ảnh có chữ OCR, đáp án, tô đỏ ký tự sai |
| `npm run pipeline` | **Ảnh toàn cảnh**: YOLO vẽ khung + CCT đọc chữ ghi ngay trên ảnh |
| `npm run container` | **Thùng container**: kiểm tra/chốt mã ISO 6346 (không cần model) |

## 3. Kết quả nằm ở đâu

| Đường dẫn trong `result/` | Nội dung |
|---|---|
| `01_test_ocr.txt` | Bảng từng crop: đáp án, chữ đọc được, conf, ĐÚNG/SAI |
| `02_ocr_visual/_tong_hop.png` | Ảnh tổng hợp 36 crop. Các ảnh lẻ cùng thư mục |
| `02_ocr_visual.txt` | Log của phần trên |
| `03_pipeline/*.jpg` | 19 ảnh toàn cảnh có khung và chữ OCR. **Xem ảnh này để đối chiếu bằng mắt** |
| `03_pipeline.txt` | Số liệu tìm biển (TP/FP/FN) và đọc biển |
| `04_python_tests.txt`, `04_python_results.json` | Kết quả phần Python |
| `05_container_check.txt` | Kiểm tra mã container + mô phỏng độ an toàn khi bỏ phiếu nhiều khung |

Màu khung trong `03_pipeline/`: **xanh** = đọc đúng · **đỏ** = đọc sai · **xám nét đứt** = biển chạm mép ảnh (bị cắt, bỏ qua) · **tím** = biển loá sáng chưa có đáp án · **xanh dương nét đứt** = khung nhãn thật.

## 4. Số liệu kỳ vọng (để biết chạy đúng)

Kết quả của bạn phải **trùng** các số này (thời gian ms thì mỗi máy mỗi khác):

- `npm test`: exact-match **31/33 = 93.9%**, char-acc **285/293 = 97.3%**
- `npm run pipeline`: bỏ box chạm mép → TP 31 · FP 0 · FN 5; đọc biển **26 đúng · 2 sai = 92.9%**
- `npm run container`: dòng cuối phải là **Tất cả kiểm tra ĐẠT**
- Python: ghép hàng 0/33, resize thẳng 32/33 = 97.0%; blur radius=4 còn 84.8%; thu nhỏ 25% còn 87.9%

Hai kết quả có thể lệch nhẹ giữa Python và Node (2/33 ảnh) vì khác cách resize. Tesseract lệch theo phiên bản cài.

## 5. Thử với ảnh của bạn

- **Crop sát biển**: bỏ `.png` vào `data/ocr_crops/`. Muốn chấm điểm thì thêm đáp án vào `data/ground_truth.json` (key = tên file, thay dấu `.` bằng `_`, ví dụ `"clip3_2_new_0__0": "75H135792"`; đặt `null` nếu không chắc). Chạy `npm test` và `npm run visual`.
- **Ảnh toàn cảnh**: `node scripts/03-pipeline.mjs "C:\duong\dan\thu_muc_anh" "C:\duong\dan\ra" 0.3` (số cuối là ngưỡng score của YOLO, mặc định 0.25). Ảnh không có nhãn vẫn chạy, chỉ không tính TP/FP.
- **Thử "có chạy thật không"**: sửa 1 đáp án trong `ground_truth.json` thành giá trị sai, chạy lại `npm test`, dòng đó phải thành SAI và exact-match tụt còn 30/33.

## 6. Lỗi thường gặp

| Lỗi | Cách xử lý |
|---|---|
| `npm` không nhận | Cài Node.js (bản 18 trở lên), mở lại PowerShell |
| `Cannot find package 'onnxruntime-node'` | Chưa chạy `npm run setup` trong đúng thư mục |
| Chữ trong `.txt` bị `Γ£à` | Mở file bằng Notepad/VS Code (UTF-8). Đừng dùng `>` để ghi, script đã tự ghi file |
| Chữ trên ảnh bị ô vuông | Máy thiếu font Segoe UI/Arial, hiếm gặp trên Windows |
| Python báo `charmap` | Đã xử lý trong script. Nếu vẫn gặp: `$env:PYTHONUTF8="1"` rồi chạy lại |

## 7. Thùng container (bản nâng cấp bước 1)

**Đã có (chạy được, đã kiểm chứng):** `src/container-code.js`
- Tính và kiểm tra số kiểm tra ISO 6346. Ảnh mẫu `COLU 200841 2` hợp lệ (số kiểm tra tính ra = 2, đúng chữ số cuối trong ảnh).
- Chuẩn hoá theo vị trí (4 ký tự đầu là chữ, 7 ký tự sau là số): `C0LU` → `COLU`, `2O0841` → `200841`. Mã loại `2261` → `22G1`.
- `vote()`: chỉ chốt mã khi **≥2 khung hình** cùng ra một mã hợp lệ.
- `decodeType('22G1')`: 20ft, cao 8ft6in, hàng tổng hợp.

**Chưa có (cần làm tiếp):**
1. Model **tìm vùng mã** trên thùng (YOLO lớp mới: số container, mã loại). YOLO hiện tại chỉ biết `bien_so`.
2. Model **đọc chữ** cho dòng mã. CCT biển số đọc tối đa 10 ký tự, còn mã container có 11. Trên ảnh mẫu, CCT trả rỗng cho dòng mã và Tesseract đọc sai (`200842`), nên chưa dùng tạm được.
3. Ảnh thật từ camera cổng có gán nhãn để đo.

**Đừng tự động "sửa" ký tự dựa vào số kiểm tra.** Mô phỏng (`05_container_check.txt`) cho thấy cách đó trả ra mã hợp lệ nhưng SAI khoảng 35% khi OCR đọc sai một chữ số. Số kiểm tra chỉ đủ để **loại** kết quả sai. Cách an toàn là bỏ phiếu nhiều khung hình, và nếu không đủ chắc thì để nhập tay.

## 8. Lấy dataset container từ Roboflow bằng API

Nguồn: Roboflow Universe `aditya017/container-ocr-byxl7` (CC BY 4.0, ghi nguồn khi dùng; 3 lớp `container-number`, `iso-type`, `seal`).

```powershell
pip install roboflow pillow
$env:ROBOFLOW_API_KEY = "dán_private_api_key_vào_đây"     # chỉ gõ trong cửa sổ PowerShell này
python python\roboflow_fetch.py
```
- Key lấy ở Roboflow → Settings → API Keys. **Không gửi key cho ai, không ghi vào file.**
- Project cần có ít nhất 1 **version**: Roboflow → Versions → Create New Version (không chọn augmentation). Đợi nhập đủ 6.473 ảnh rồi hãy tạo.
- Script tải bản `yolov8` vào `data/container_roboflow/`, thống kê vào `result/06_roboflow_dataset.txt`, và đóng bộ nhỏ `result/roboflow_subset.zip`.
- Đã tải tay rồi? Chạy `python python\roboflow_fetch.py --local "đường\dẫn\thư_mục_đã_giải_nén"`.
- Phần phân tích/đóng gói đã test trên dataset giả; **phần gọi API chưa test được** (môi trường dựng không truy cập được Roboflow), nếu báo lỗi thì gửi nguyên thông báo.

### Chuẩn bị dataset trước khi train (bắt buộc)

```powershell
python python\prepare_container_dataset.py --src "đường\dẫn\Container OCR.v8i.yolov8" --drop-panorama
```
Vì sao: ~10% nhãn là **đa giác** (xoay/nghiêng) và nằm lẫn với khung trong cùng file. Ultralytics sẽ **bỏ cả file** đó ("labels mix segment and detection rows"). Script đổi đa giác thành khung, tạo `data/container_clean/` (ảnh dùng hard-link, không tốn thêm dung lượng nếu cùng ổ đĩa) và báo cáo `result/07_prepare_container.txt` (cỡ ảnh, tỉ lệ số container nằm dọc, % khung quá nhỏ ở imgsz 640/960/1280).
**Ảnh minh hoạ nhãn** ở `result/07_prepare_visual/` (mở `_tong_hop.jpg` trước): đa giác gốc màu hồng, khung sau khi đổi màu theo lớp, kèm vài panorama bị bỏ. Tắt bằng `--no-visual`.

## 9. Đo thử đọc chữ container (baseline)

```powershell
pip install rapidocr-onnxruntime pytesseract
python python\baseline_container_ocr.py --src "đường\dẫn\Container OCR.v8i.yolov8" --n 100
```
Đọc chữ trên vùng `container-number` **thật** (khung lấy từ nhãn) bằng Tesseract và RapidOCR, chấm bằng số kiểm tra ISO 6346. Kết quả: `result/08_baseline_ocr.txt` và ảnh `result/08_baseline_visual/_tong_hop.jpg`. Đây là mốc để so sánh, chưa phải model của dự án. Hợp lệ ≠ chắc chắn đúng (chuỗi sai vẫn lọt qua khoảng 2-12%).

## 10. Xử lý video thời gian thực (không lưu ảnh)

```powershell
pip install opencv-python-headless
python python\stream_demo.py --make-test-video result\test_video.mp4         # video thử (slideshow từ data/frames)
python python\stream_demo.py --source result\test_video.mp4 --max-seconds 15 --save-overlay
python python\stream_demo.py --source "rtsp://user:pass@IP:554/stream"        # camera thật
```
Luồng đọc chạy thread riêng và chỉ giữ **khung mới nhất** trong RAM; xử lý chậm thì bỏ khung cũ, độ trễ không tích luỹ. Báo cáo `result/09_stream_timing.txt`: fps xử lý, số khung bị bỏ, thời gian từng bước, độ trễ p50/p95. Hiện dùng model biển số xe máy; khi có model container thì đổi file model, phần luồng giữ nguyên.

## 11. Cắt video thành ảnh để gán nhãn/train

```powershell
python python\extract_frames.py --video "D:\videos_cong" --fps 2 --out data\my_frames
python python\extract_frames.py --video clip.mp4 --fps 3 --min-sharp 60      # bỏ ảnh mờ
```
Một video chỉ là chuỗi ảnh; script chỉ lưu một phần (mặc định 2 ảnh/giây), bỏ ảnh giống khung trước, tuỳ chọn bỏ ảnh mờ (xem phân bố độ nét trong `result/10_extract_frames.txt` để chọn ngưỡng). Mỗi ảnh có tên theo video và mili-giây, kèm `index.csv`. Ảnh này dùng để gán nhãn; đừng đưa cả khung gần giống nhau vào cả train lẫn test.

## 12. Train trên GPU (RTX 3050 Laptop 4 GB)

```powershell
python -c "import torch;print(torch.__version__, torch.cuda.is_available())"
```
Nếu in `False`: đang là PyTorch bản CPU. Cài lại bản CUDA: vào pytorch.org → Get Started → chọn Windows / Pip / CUDA, chép đúng lệnh; trước đó `pip uninstall torch torchvision`. Driver NVIDIA phải mới (gõ `nvidia-smi` xem dòng CUDA Version).

```powershell
pip install ultralytics
python python\train_container_yolo.py --check
python python\train_container_yolo.py --epochs 3 --name thu       # đo thời gian 1 epoch trước
python python\train_container_yolo.py --epochs 60                  # train thật (cắm sạc, chế độ hiệu năng cao)
```
Mặc định `yolov8n`, `imgsz 960`, `batch 8`; hết bộ nhớ GPU thì giảm `--batch 4` hoặc `--imgsz 800`. Không lật ngang ảnh khi train (chữ sẽ bị soi gương). Kết quả: `result/11_train_container.txt` và thư mục `result/train_container/<name>/` (có ảnh dự đoán trên tập val).

Chạy video bằng GPU: `pip uninstall onnxruntime` rồi `pip install onnxruntime-gpu` (không để cả hai); `stream_demo.py` tự dùng GPU nếu có.

## 13. Kiểm tra đường ống video → cắt khung → mô hình đã train

```powershell
# Chưa có video: tạo video thử từ ảnh val (slideshow, chỉ để thử đường ống)
python python\test_video_model.py --make-test-video result\test_video.mp4 --images data\container_clean\valid\images
# Chạy mô hình đã train trên video, mỗi giây lấy 3 khung
python python\test_video_model.py --source result\test_video.mp4 --model result\train_container\thu\weights\best.pt --imgsz 960 --fps 3
# Video thật (điện thoại/camera); thêm --track để gán ID từng xe
python python\test_video_model.py --source "D:\videos\clip.mp4" --model result\train_container\container\weights\best.pt --imgsz 960 --fps 3
```
Kết quả: `result/12_video_test.txt` (dòng "Cắt khung" phải ghi **ĐƯỜNG ỐNG CẮT KHUNG HOẠT ĐỘNG**), `result/12_video_test/frames/_tong_hop.jpg` (khung mẫu có khung + nhãn), `annotated.mp4`, và `crops/` (vùng cắt tin cậy nhất mỗi lớp, dùng cho bước đọc chữ). `--imgsz` phải trùng cỡ lúc train. Không thấy vùng nào thì thử hạ `--conf 0.1`. Cờ `--backend onnx` chạy được model ONNX có NMS sẵn mà không cần PyTorch.

## 14. Giao diện kiểm tra video (thả video, bấm nút, xem nhật ký)

```powershell
python python\app_video_test.py
```
Hoặc bấm đúp `chay_giao_dien.bat`. Trình duyệt tự mở `http://127.0.0.1:8765` (chỉ máy bạn truy cập được). Thả video, chọn model, bấm **Kiểm tra**: nhật ký hiện trực tiếp (môi trường, lệnh chạy, tiến độ từng 10 khung, lỗi), có ô **Chẩn đoán** gợi ý cách sửa và nút tải nhật ký. Mỗi lần chạy lưu ở `result/web_runs/<thời gian>/` (có `run.log`). Giao diện này là lớp vỏ gọi `test_video_model.py`.

Mỗi lần chạy có thêm: `out/frames_cut/` (ảnh cắt từ video), `out/frames_processed/` (ảnh đã vẽ khung + chữ đọc được), `out/results.csv` và `out/results.json` (mỗi ảnh một dòng: chữ đọc được, trạng thái HỢP LỆ / CHƯA XÁC NHẬN / MỘT PHẦN / KHÔNG ĐỌC ĐƯỢC) và dòng KẾT QUẢ CUỐI (mã hợp lệ xuất hiện nhiều nhất, cần ≥2 khung cùng mã). Bước đọc chữ dùng RapidOCR/Tesseract làm mốc tạm (cài `pip install rapidocr-onnxruntime pytesseract`), độ chính xác thấp như đã đo, chưa phải mô hình riêng. **Chọn đúng file**: dùng `best.pt` vừa train; `cct_s_v2_global.onnx` là bộ đọc chữ biển số nên không dùng ở đây.


## 15. Giới hạn cần nhớ

- Dữ liệu chỉ có 6 biển xe máy 2 dòng lặp qua nhiều khung hình. Chưa có test biển ô tô/xe tải 1 dòng.
- Tập val và tập train YOLO cùng một cảnh quay (cùng xe, cùng biển), nên chỉ số YOLO lạc quan.
- `conf` cao không đảm bảo đúng (có ảnh sai nhưng conf 0.999). Nên kiểm tra định dạng biển và bỏ phiếu nhiều khung hình.
- Mới test Node/CPU, chưa test trên browser (ORT Web).

Chi tiết kỹ thuật: `docs/OCR_FINDINGS.md`, `docs/VERIFY_REPORT.md`.
