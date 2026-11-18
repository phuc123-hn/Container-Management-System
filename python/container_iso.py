"""
Mã container ISO 6346 + chuẩn hoá biển số (bản Python của src/container-code.js, cùng bảng giá trị chữ cái).
Chỉ KIỂM TRA và giải thích lỗi, không tự đoán/sửa ký tự (số kiểm tra chỉ 1 chữ số nên sửa theo nó sẽ ra mã hợp lệ nhưng SAI).
Định dạng 11 ký tự: AAA U 123456 7 = 3 chữ chủ sở hữu + U/J/Z/R + 6 số serial + 1 số kiểm tra.
"""
import re

# A=10, bỏ qua các bội của 11 (11, 22, 33): B=12 ... K=21, L=23 ... U=32, V=34 ... Z=38
_LV = {c: 10 + i + (0 if i == 0 else 1 if i <= 10 else 2 if i <= 20 else 3) for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}


def clean(raw):
    """Viết hoa, bỏ mọi ký tự không phải chữ/số (khoảng trắng, gạch, chấm)."""
    return re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())


plate_norm = clean      # biển số '51C-123.45' và '51c 12345' cùng ra '51C12345' để so khớp/tìm kiếm


def check_digit(first10):
    """Số kiểm tra tính từ 10 ký tự đầu (chữ + số)."""
    s = sum((_LV[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(first10[:10]))
    return (s % 11) % 10


def problems(raw):
    """Danh sách lý do mã KHÔNG hợp lệ (tiếng Việt). Rỗng = hợp lệ."""
    s = clean(raw)
    if len(s) != 11:
        return [f"Mã container phải đủ 11 ký tự (đang có {len(s)})."]
    errs = []
    if not s[:3].isalpha():
        errs.append("3 ký tự đầu (mã chủ sở hữu) phải là chữ.")
    if not s[3].isalpha() or s[3] not in "UJZR":
        errs.append("Ký tự thứ 4 phải là U, J, Z hoặc R.")
    if not s[4:].isdigit():
        errs.append("7 ký tự cuối phải là số.")
    if not errs:
        want = check_digit(s[:10])
        if want != int(s[10]):
            errs.append(f"Số kiểm tra sai: 10 ký tự đầu cho số kiểm tra {want}, mã nhập là {s[10]}. Có ít nhất 1 ký tự đọc/gõ sai.")
    return errs


def is_valid(raw):
    return not problems(raw)
