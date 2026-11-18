"""
Đọc chữ từ ảnh BIỂN SỐ XE và ảnh GIẤY TỜ (lệnh giao/nhận, giấy giới thiệu, phiếu đăng ký... có tên tài xế và số điện thoại).
Dùng RapidOCR (pip install rapidocr-onnxruntime). Kết quả chỉ là GỢI Ý: người dùng luôn phải đối chiếu bằng mắt.
Lưu ý: bộ nhận dạng chung này đọc chữ có dấu tiếng Việt chưa tốt; số điện thoại và biển số (chữ + số) đọc tốt hơn tên.
Phần phân tích (parse_*) là hàm thuần, không cần thư viện OCR.
"""
import re, unicodedata

_ENGINE = None
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "6": "G", "2": "Z"}

def read_lines(path):
    """Trả danh sách dòng chữ (từ trên xuống dưới). Ném RuntimeError có lời nhắn dễ hiểu nếu thiếu thư viện."""
    global _ENGINE
    try:
        import numpy as np
        from PIL import Image
        if _ENGINE is None:
            from rapidocr_onnxruntime import RapidOCR
            _ENGINE = RapidOCR()
    except ImportError as e:
        raise RuntimeError("Chưa cài thư viện đọc chữ. Chạy: python -m pip install rapidocr-onnxruntime pillow") from e
    img = Image.open(path).convert("RGB")
    if max(img.size) > 1800:
        k = 1800 / max(img.size); img = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))))
    res, _ = _ENGINE(np.asarray(img))
    if not res: return []
    return [r[1] for r in sorted(res, key=lambda r: (min(p[1] for p in r[0]) // 20, min(p[0] for p in r[0])))]

def _alnum(s): return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKD", str(s).upper()).encode("ascii", "ignore").decode())

def _fmt_plate(prov, letters, sdig, num):
    tail = f"{num[:3]}.{num[3:]}" if len(num) == 5 else num
    return f"{prov}{letters}-{tail}" if not sdig else f"{prov}-{letters}{sdig} {tail}"

def _plate_match(s):
    """s: chuỗi đã bỏ ký tự lạ. Trả biển số định dạng đẹp hoặc None."""
    m = re.search(r"(\d{2})([A-Z]{1,2})(\d{4,6})", s)
    if not m: return None
    prov, letters, rest = m.groups()
    if not 11 <= int(prov) <= 99: return None
    if len(rest) == 6: return _fmt_plate(prov, letters, rest[0], rest[1:])
    return _fmt_plate(prov, letters, "", rest)

def parse_plate(lines):
    """Tìm biển số kiểu Việt Nam (51C-123.45, 29A-1234, 29-B1 123.45). Trả (biển, cách_tìm).
    Biển 2 dòng phải ghép dòng trên + dòng dưới nên độ tin cậy thấp hơn biển 1 dòng: UI luôn bắt kiểm tra bằng mắt."""
    lines = [l for l in lines if l and l.strip()]; cands = []
    for i, l in enumerate(lines):
        cands.append((_alnum(l), "một dòng"))
        if i + 1 < len(lines): cands.append((_alnum(l) + _alnum(lines[i + 1]), "ghép 2 dòng"))
    cands.append(("".join(_alnum(l) for l in lines), "ghép nhiều dòng"))
    for c, how in cands:
        p = _plate_match(c)
        if p: return p, how
    for c, how in cands:                              # thử sửa nhầm lẫn O/0, I/1... theo vị trí
        for k in range(0, max(1, len(c) - 5)):
            w = c[k:k + 9]; head = "".join(_TO_DIGIT.get(x, x) for x in w[:2])
            if len(w) < 6 or not head.isdigit(): continue
            rest = w[2:]; letter = rest[0]; letter = _TO_LETTER.get(letter, letter) if letter.isdigit() else letter
            p = _plate_match(head + letter + "".join(_TO_DIGIT.get(x, x) for x in rest[1:]))
            if p: return p, how + ", đã sửa nhầm ký tự"
    return "", ""

_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)[\s.\-]?(?:\d[\s.\-]?){8,9}(?!\d)")
def parse_phone(lines):
    """Số di động Việt Nam 10 số (03/05/07/08/09...). Trả '0912345678' hoặc ''."""
    for l in lines:
        for m in _PHONE.finditer(l):
            d = re.sub(r"\D", "", m.group()); d = "0" + d[2:] if d.startswith("84") else d
            if len(d) == 10 and d[:2] in ("03", "05", "07", "08", "09"): return d
    return ""

_NAME_LABEL = re.compile(r"(h[oọ]\s*(v[aà]\s*)?t[eê]n|t[aà]i\s*x[eế]|l[aá]i\s*x[eế]|ch[uủ]\s*xe|driver|full\s*name|name)\s*[:\-]?\s*(.*)", re.I)
_SKIP = ("CONG HOA", "CỘNG HÒA", "DOC LAP", "ĐỘC LẬP", "CAN CUOC", "CĂN CƯỚC", "GIAY PHEP", "GIẤY PHÉP", "SOCIALIST", "REPUBLIC", "VIETNAM", "VIỆT NAM", "PHIEU", "PHIẾU", "CONTAINER", "BIEN SO", "BIỂN SỐ", "LENH", "LỆNH")
def parse_name(lines):
    """Ưu tiên dòng sau nhãn 'Tài xế / Lái xe / Họ tên / Driver'. OCR hay làm mất khoảng trắng nên có thể trả tên dính liền
    (ví dụ NGUYENVANAN): khi đó người dùng phải gõ lại cho đúng."""
    def ok(t, strict):
        t = re.sub(r"\s+", " ", t).strip(" :.-_")
        pat = r"[^\W\d_]+(?: [^\W\d_]+){1,5}" if strict else r"[^\W\d_]+(?: [^\W\d_]+){0,5}"
        return t if re.fullmatch(pat, t) and 4 <= len(t) <= 40 and not any(k in t.upper() for k in _SKIP) else ""
    for i, l in enumerate(lines):
        m = _NAME_LABEL.search(l)
        if m:
            t = ok(m.group(3), False) or (ok(lines[i + 1], True) if i + 1 < len(lines) else "")
            if t: return t.title() if " " in t else t.upper()
    return ""

def parse_paper(lines):
    return {"name": parse_name(lines), "phone": parse_phone(lines), "raw": [l.strip() for l in lines[:14]]}

_CCT = None
def _plate_cct(path):
    """Bộ đọc biển số của dự án (models/plate_yolo.onnx + cct_s_v2_global.onnx), dùng lại lớp trong stream_demo.py."""
    global _CCT
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cv2
    import stream_demo as S
    dp, rp = S.ROOT / "models" / "plate_yolo.onnx", S.ROOT / "models" / "cct_s_v2_global.onnx"
    if not (dp.exists() and rp.exists()): raise FileNotFoundError("thiếu models/plate_yolo.onnx hoặc models/cct_s_v2_global.onnx")
    if _CCT is None: _CCT = (S.Detector(dp), S.Reader(rp))
    det, rd = _CCT; img = cv2.imread(str(path))
    if img is None: raise ValueError("không mở được ảnh")
    boxes = det(img); crop = img
    if boxes:
        x1, y1, x2, y2, _ = max(boxes, key=lambda b: b[4]); px, py = max(8, (x2 - x1) * .07), max(6, (y2 - y1) * .12)
        c = img[max(0, int(y1 - py)):int(y2 + py), max(0, int(x1 - px)):int(x2 + px)]
        crop = c if c.size else img
    txt, conf = rd(crop)
    return txt, conf

def extract_plate(path):
    """Trả {plate, how, source, raw, note}. Ưu tiên bộ đọc CCT của dự án; không dùng được thì rơi về OCR chung."""
    note = ""
    try:
        txt, conf = _plate_cct(path); p = _plate_match(_alnum(txt))
        if p: return {"plate": p, "how": f"bộ đọc CCT, độ tin cậy {conf:.2f}", "source": "CCT", "raw": [txt], "note": ""}
        note = f"Bộ đọc CCT ra '{txt}' (không đúng dạng biển Việt Nam), thử OCR chung."
    except Exception as e:
        note = f"Chưa dùng được bộ đọc CCT ({type(e).__name__}: {e}); dùng OCR chung, độ tin cậy thấp hơn."
    lines = read_lines(path); p, how = parse_plate(lines)
    return {"plate": p, "how": how, "source": "OCR chung", "raw": [l.strip() for l in lines[:6]], "note": note}

def extract_paper(path):
    return parse_paper(read_lines(path))
