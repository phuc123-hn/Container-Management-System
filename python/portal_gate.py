"""
Logic phiếu điện tử ra/vào bãi (không có HTTP ở đây): kiểm tra mã container ISO 6346, tạo/xác nhận phiếu, đối chiếu lúc ra,
tính tiền bãi theo bậc ngày, tìm kiếm, và chạy mô hình YOLO (test_video_model.py) ở luồng nền cho chế độ TỰ ĐỘNG.
"""
import html, json, math, re, secrets, shutil, sqlite3, subprocess, sys, threading, time
from pathlib import Path
import portal_db as D

ROOT = D.ROOT
EVID = ROOT / "data" / "evidence"; JOBS_DIR = ROOT / "data" / "gate_jobs"
SIZES = ("20", "40", "45")
FEE_PARTIES = {"chu_xe": "Chủ xe", "chu_hang": "Chủ hàng", "hang_tau": "Hãng tàu", "khac": "Khác"}
PASS_STATUS = {"pending": "Chờ xác nhận vào bãi", "inside": "Đang trong bãi", "closed": "Đã ra bãi", "rejected": "Đã huỷ"}
STAFF = ("admin", "gate")     # được XEM mọi phiếu/dòng thời gian/công nợ
OPS = ("gate",)               # được THAO TÁC cổng và thanh toán (Admin boss chỉ giám sát, không làm phiếu hay cho xe ra vào)
NOT_OPS = "Chỉ Quản trị cổng được thao tác cổng và thanh toán. Admin boss chỉ xem và quản lý."
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
UPLOAD_EXT = IMG_EXT | {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
SIG_DIR = ROOT / "data" / "signatures"
PAY_METHODS = {"cash": "Tiền mặt", "transfer": "Chuyển khoản", "other": "Khác", "free": "Miễn phí"}

# ---------------------------------------------------------------- mã container ISO 6346 (bản Python của src/container-code.js)
_LV = {c: 10 + i + (0 if i == 0 else 1 if i <= 10 else 2 if i <= 20 else 3) for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
def clean(s): return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())
def check_digit(first10): return (sum((_LV[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(first10[:10])) % 11) % 10
def shape_ok(s): return bool(re.fullmatch(r"[A-Z]{4}\d{7}", s))
def is_valid_container(s):
    s = clean(s); return bool(re.fullmatch(r"[A-Z]{3}[UJZR]\d{7}", s)) and check_digit(s) == int(s[10])
def clean_plate(s): return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 .\-]", "", str(s or "")).upper()).strip()[:15]

def marks(expected, got):
    """HTML hai chuỗi, ký tự khác nhau (so theo vị trí) tô đỏ. Trả (html_expected, html_got, giống_nhau)."""
    e, g = clean(expected), clean(got)
    he = "".join(f'<span class="x">{html.escape(c)}</span>' if i >= len(g) or g[i] != c else html.escape(c) for i, c in enumerate(e))
    hg = "".join(f'<span class="x">{html.escape(c)}</span>' if i >= len(e) or e[i] != c else html.escape(c) for i, c in enumerate(g))
    return he, hg, e == g

# ---------------------------------------------------------------- tiền bãi
def money(n): return (f"{int(n):,}".replace(",", ".") + " đ") if n is not None else "—"
def dur_text(sec):
    sec = int(max(0, sec)); d, r = divmod(sec, 86400); h, r = divmod(r, 3600); m, s = divmod(r, 60)
    return (f"{d} ngày " if d else "") + f"{h:02d}:{m:02d}:{s:02d}"

def uncovered_days(rows, upto):
    """Các dải ngày trong 1..upto CHƯA có bậc giá: [(từ, đến), ...]."""
    out, start = [], None
    for d in range(1, upto + 1):
        c = any(t["day_from"] <= d <= (t["day_to"] or 10 ** 9) for t in rows)
        if not c and start is None: start = d
        if c and start is not None: out.append((start, d - 1)); start = None
    if start is not None: out.append((start, upto))
    return out

def fee_calc(db, size, in_at, end):
    """Tiền bãi = (số NGÀY TRỌN theo bậc giá ngày) + (PHẦN DƯ chưa tròn 24 giờ theo đơn giá GIỜ của bậc ngày kế tiếp).
    Đơn giá giờ để trống thì lấy đơn giá ngày / 24. Phần dư không bao giờ vượt đơn giá một ngày trọn của bậc đó.
    Cách làm tròn giờ (cài đặt hour_round): up = mỗi giờ bắt đầu tính trọn, down = chỉ giờ trọn, exact = theo phút."""
    el = max(0.0, end - in_at); full = int(el // 86400); rem = el - full * 86400
    rows = db.execute("SELECT * FROM tariff_tiers WHERE size=? ORDER BY day_from", (size,)).fetchall() or db.execute("SELECT * FROM tariff_tiers WHERE size='all' ORDER BY day_from").fetchall()
    lines, storage, covered = [], 0, 0
    for t in rows:
        lo, hi = t["day_from"], min(t["day_to"] or full, full); n = hi - lo + 1
        if n > 0:
            amt = n * t["rate"]; storage += amt; covered = max(covered, hi)
            lines.append({"label": f"Ngày {lo}" if lo == hi else f"Ngày {lo}–{hi}", "qty": n, "unit": "ngày", "rate": t["rate"], "amount": amt})
    unc = uncovered_days(rows, full)
    warn = (f"Bảng giá cỡ {size} feet chưa có bậc cho " + ", ".join(f"ngày {a}" if a == b else f"ngày {a}–{b}" for a, b in unc) + ": các ngày này đang tính 0 đ. (Bảng giá tính riêng từng cỡ.)") if unc else ""
    rem_amt = 0
    if rem > 0:
        day_no = full + 1; tier = next((t for t in rows if t["day_from"] <= day_no <= (t["day_to"] or 10 ** 9)), None)
        mode = D.get_setting(db, "hour_round", "up")
        hrs = math.ceil(rem / 3600) if mode == "up" else (math.floor(rem / 3600) if mode == "down" else rem / 3600)
        if tier is not None:
            hr = tier["hour_rate"] if tier["hour_rate"] is not None else tier["rate"] / 24
            raw = hrs * hr; rem_amt = int(round(min(raw, tier["rate"]))); capped = raw > tier["rate"]
            q = int(hrs) if mode != "exact" else round(hrs, 2)
            if rem_amt or q:
                lines.append({"label": f"Phần dư {int(rem // 3600)} giờ {int(rem % 3600 // 60):02d} phút (ngày {day_no})" + (", tối đa bằng 1 ngày" if capped else ""), "qty": q, "unit": "giờ", "rate": int(round(hr)), "amount": rem_amt})
        elif rows and not warn: warn = f"Bảng giá cỡ {size} feet chưa có bậc cho ngày {day_no}: phần dư đang tính 0 đ. (Bảng giá tính riêng từng cỡ.)"
    if not rows: warn = f"Chưa có bảng giá cho cỡ {size} feet."
    lift = int(D.get_setting(db, f"lift_fee_{size}", "0") or 0)
    return {"days": full, "rem_seconds": int(rem), "elapsed": el, "lines": lines, "storage": storage + rem_amt, "lift": lift, "total": storage + rem_amt + lift, "warn": warn}

def tariff_gaps(db, size):
    """Các khoảng ngày CHƯA có giá của một cỡ (đang bị tính 0 đ). Trả danh sách chữ, rỗng nếu phủ kín."""
    rows = db.execute("SELECT * FROM tariff_tiers WHERE size=? ORDER BY day_from", (size,)).fetchall() or db.execute("SELECT * FROM tariff_tiers WHERE size='all' ORDER BY day_from").fetchall()
    if not rows: return ["chưa có bảng giá nào"]
    out, cur = [], 1
    for t in rows:
        if t["day_from"] > cur: out.append(f"ngày {cur}" if t["day_from"] - 1 == cur else f"ngày {cur}–{t['day_from'] - 1}")
        if t["day_to"] is None: return out
        cur = max(cur, t["day_to"] + 1)
    return out + [f"từ ngày {cur} trở đi"]

# ---------------------------------------------------------------- phiếu
def can_view(user, p): return user["role"] in STAFF or (user["role"] == "customer" and p["customer_id"] == user["id"])
def qr_payload(p): return f"SPASS|{p['pass_no']}|{p['token']}"

def parse_scan(text):
    """Nhận nội dung quét: 'SPASS|số phiếu|token' hoặc chỉ số phiếu gõ tay. Trả (số_phiếu, token|None)."""
    t = (text or "").strip()
    m = re.fullmatch(r"SPASS\|(PASS-\d{8}-\d{4})\|([0-9A-F]{10})", t.upper())
    if m: return m.group(1), m.group(2)
    m = re.fullmatch(r"(PASS-\d{8}-\d{4})", t.upper())
    return (m.group(1), None) if m else (None, None)

def find_by_scan(db, text):
    """Trả (phiếu|None, cách, thông_báo). cách: 'qr' nếu token khớp, 'tay' nếu chỉ nhập số phiếu."""
    no, tok = parse_scan(text)
    if not no: return None, "", "Không nhận ra mã. Quét lại mã QR hoặc gõ số phiếu dạng PASS-20261029-0001."
    p = db.execute("SELECT * FROM gate_passes WHERE pass_no=?", (no,)).fetchone()
    if p is None: return None, "", f"Không có phiếu {no}."
    if tok is not None and tok != (p["token"] or ""): return None, "", "Mã QR không khớp với phiếu (có thể là mã giả hoặc phiếu đã bị thay). Không cho qua."
    return p, ("qr" if tok else "tay"), ""

def _evidence_copy(src, pass_no, name):
    if not src or not Path(src).exists(): return None
    d = EVID / pass_no; d.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, d / name); return f"{pass_no}/{name}"

def _ev(db, pid, direction, user_id, note, read=None, votes=None, frames=None, image=None, run_id=None, override=0):
    db.execute("INSERT INTO gate_events(pass_id,direction,ts,container_read,votes,of_frames,image_path,run_id,confirmed_by,manual_override,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (pid, direction, time.time(), read, votes, frames, image, run_id, user_id, override, note))

def create_pass(db, user, d, mode="manual", job=None, confirm_now=False):
    """d: dict từ form. Trả (pass_id|None, [lỗi])."""
    if user["role"] not in OPS: return None, [NOT_OPS]
    errs = []; cont = clean(d.get("container_no")); plate = clean_plate(d.get("truck_plate")); size = d.get("size", "40")
    if not shape_ok(cont): errs.append("Số container gồm 4 chữ cái + 7 số (ví dụ EITU1841398).")
    elif not is_valid_container(cont) and not d.get("accept_invalid"):
        errs.append(f"Số container {cont} không hợp lệ theo ISO 6346 (số kiểm tra phải là {check_digit(cont[:10])}, bạn nhập {cont[10]}; hoặc chữ thứ 4 không phải U/J/Z/R). Xem lại bằng mắt; nếu chắc đúng như trên thùng thì tích ô xác nhận bên dưới.")
    if len(clean(plate)) < 4: errs.append("Nhập biển số xe (ít nhất 4 ký tự).")
    if size not in SIZES: errs.append("Chọn cỡ container 20 / 40 / 45.")
    party = d.get("fee_party", "chu_xe")
    if party not in FEE_PARTIES: errs.append("Bên trả phí không hợp lệ.")
    cust = None
    if d.get("customer_id"):
        r = db.execute("SELECT id FROM users WHERE id=? AND role='customer' AND status='active'", (d.get("customer_id"),)).fetchone()
        if r is None: errs.append("Tài khoản khách hàng không hợp lệ.")
        else: cust = r["id"]
    iso = clean(d.get("iso_type"))[:4] or None
    phone = re.sub(r"[^0-9+ .\-]", "", d.get("owner_phone", ""))[:20] or None
    if not errs:
        op = db.execute("SELECT pass_no, status FROM gate_passes WHERE container_no=? AND status IN ('pending','inside')", (cont,)).fetchone()
        if op: errs.append(f"Container {cont} đang có phiếu mở: {op['pass_no']} ({PASS_STATUS[op['status']]}). Phải cho ra bãi hoặc huỷ phiếu đó trước.")
    if errs: return None, errs
    now = time.time(); day = time.strftime("%Y%m%d", time.localtime(now)); pid = None
    for _ in range(8):
        n = (db.execute("SELECT COUNT(*) FROM gate_passes WHERE pass_no LIKE ?", (f"PASS-{day}-%",)).fetchone()[0]) + 1 + _
        no, tok = f"PASS-{day}-{n:04d}", secrets.token_hex(5).upper()
        try:
            cur = db.execute("INSERT INTO gate_passes(pass_no,customer_id,container_no,truck_plate,status,created_by,created_at,mode,token,size,iso_type,plate_key,owner_name,owner_phone,fee_party,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (no, cust, cont, plate, "pending", user["id"], now, mode, tok, size, iso, clean(plate), (d.get("owner_name") or "").strip()[:100] or None, phone, party, (d.get("note") or "").strip()[:300] or None))
            pid = cur.lastrowid; break
        except sqlite3.IntegrityError: continue
    if pid is None: return None, ["Không tạo được số phiếu, thử lại."]
    img = None; read = None; votes = None; frames = None; override = 1 if d.get("accept_invalid") else 0
    if job and job.get("result"):
        r = job["result"]; read, votes, frames = r.get("code") or None, r.get("votes"), r.get("frames_n")
        img = _evidence_copy(r.get("proc_path"), no, "in.jpg")
        if img: db.execute("UPDATE gate_passes SET in_image=? WHERE id=?", (img, pid))
        pimg = _evidence_copy(r.get("plate_path"), no, "plate.jpg")
        if pimg: db.execute("UPDATE gate_passes SET plate_image=? WHERE id=?", (pimg, pid))
        if read and clean(read) != cont: override = 1
    _ev(db, pid, "in", user["id"], "Tạo phiếu (" + ("tự động bằng mô hình" if mode == "auto" else "nhập thủ công") + ")" + ("; ĐÃ TÍCH xác nhận mã sai số kiểm tra" if d.get("accept_invalid") else ""),
        read or cont, votes, frames, img, job.get("id") if job else None, override)
    db.commit(); D.audit(db, user["id"], "pass_create", no, "")
    if confirm_now: confirm_in(db, user, pid)
    return pid, []

def sys_msg(db, p, kind, now, extra=""):
    """Thư hệ thống cho TÀI KHOẢN khách của phiếu (khách vãng lai không có hộp thư). Tự xoá sau sysmsg_days ngày."""
    if not p["customer_id"]: return
    when = time.strftime("%H:%M %d/%m/%Y", time.localtime(now)); base = f"Xe {p['truck_plate']} chở container {p['container_no']} ({p['size']} feet)"
    if kind == "in": title, body = "Xe đã vào bãi", f"{base} đã vào bãi lúc {when}. Số phiếu {p['pass_no']}."
    else: title, body = "Xe đã ra bãi", f"{base} đã ra bãi lúc {when}. Số phiếu {p['pass_no']}. {extra}".strip()
    db.execute("INSERT INTO system_msgs(user_id,pass_id,kind,title,body,created_at) VALUES(?,?,?,?,?,?)", (p["customer_id"], p["id"], kind, title, body, now))

def confirm_in(db, user, pid):
    if user["role"] not in OPS: return [NOT_OPS]
    p = db.execute("SELECT * FROM gate_passes WHERE id=?", (pid,)).fetchone()
    if p is None: return ["Không có phiếu."]
    now = time.time()
    cur = db.execute("UPDATE gate_passes SET status='inside', in_at=?, in_by=? WHERE id=? AND status='pending'", (now, user["id"], pid))
    if cur.rowcount != 1: db.rollback(); return [f"Phiếu {p['pass_no']} đang ở trạng thái '{PASS_STATUS[p['status']]}', không xác nhận vào bãi được."]
    _ev(db, pid, "in", user["id"], "XÁC NHẬN VÀO BÃI", p["container_no"]); sys_msg(db, p, "in", now); db.commit(); D.audit(db, user["id"], "pass_in", p["pass_no"], ""); return []

def compare_out(p, container_read, plate_read):
    rows = []
    for label, exp, got in (("Số container", p["container_no"], container_read), ("Biển số xe", p["truck_plate"], plate_read)):
        he, hg, same = marks(exp, got); empty = not clean(got)
        rows.append({"label": label, "expected": exp, "got": got, "he": he, "hg": hg or "<i>chưa nhập</i>", "ok": same and not empty})
    return rows

def pay_terms_of(db, p):
    """Khách vãng lai (không tài khoản) và khách trả trước phải thanh toán trước khi ra; khách công nợ được ra rồi thanh toán trong hạn."""
    if not p["customer_id"]: return "prepaid", 0
    u = db.execute("SELECT pay_terms, credit_days FROM users WHERE id=?", (p["customer_id"],)).fetchone()
    return (u["pay_terms"], u["credit_days"]) if u else ("prepaid", 0)

def exit_quote(db, p, now=None):
    """(bảng tính tiền tới giờ, điều khoản, số ngày công nợ, có phải thanh toán trước khi ra không)."""
    fee = fee_calc(db, p["size"], p["in_at"] or p["created_at"], now or time.time()); terms, days = pay_terms_of(db, p)
    return fee, terms, days, (fee["total"] > 0 and terms != "credit")

def confirm_out(db, user, pid, container_read, plate_read, scan, job=None, reason="", pay=None):
    if user["role"] not in OPS: return [NOT_OPS]
    p = db.execute("SELECT * FROM gate_passes WHERE id=?", (pid,)).fetchone()
    if p is None: return ["Không có phiếu."]
    rows = compare_out(p, container_read, plate_read); bad = [r["label"] for r in rows if not r["ok"]]; reason = (reason or "").strip()
    if bad and len(reason) < 5: return [f"Lệch ở: {', '.join(bad)}. Muốn cho ra phải ghi lý do (ít nhất 5 ký tự); việc này được lưu để chủ kiểm tra."]
    now = time.time(); fee, terms, cdays, prepay = exit_quote(db, p, now); free = fee["total"] == 0; pay = pay or {}
    if prepay:
        if pay.get("method") not in ("cash", "transfer", "other"): return ["Khách trả trước/vãng lai: chọn hình thức thanh toán trước khi cho ra."]
        if not (pay.get("received") and pay.get("confirmed")): return ["Phải tích đủ 2 xác nhận: bãi đã nhận tiền VÀ khách đã xác nhận thanh toán."]
        try: exp = int(pay.get("expected"))
        except (TypeError, ValueError): exp = -1
        if exp != fee["total"]: return [f"Tiền bãi đã đổi từ {money(exp) if exp >= 0 else '—'} thành {money(fee['total'])} (qua mốc giờ). Kiểm tra lại số tiền rồi xác nhận lại."]
    if prepay: paid = (1, now, user["id"], pay["method"], (pay.get("ref") or "").strip()[:60] or None, now, user["id"], "counter", "")
    elif free: paid = (1, now, user["id"], "free", None, None, None, None, None)
    else: paid = (0, None, None, None, None, None, None, None, None)
    due = now + cdays * 86400 if (not prepay and not free) else None
    cur = db.execute("UPDATE gate_passes SET status='closed', out_at=?, out_by=?, fee_total=?, fee_detail=?, staff_sig=?, fee_paid=?, paid_at=?, paid_by=?, pay_method=?, pay_ref=?, cust_confirmed_at=?, cust_confirmed_by=?, cust_mode=?, cust_sig=?, due_at=? WHERE id=? AND status='inside'",
                     (now, user["id"], fee["total"], json.dumps(fee, ensure_ascii=False), snapshot_signature(user["id"], pid, "staff"), *paid, due, pid))
    if cur.rowcount != 1: db.rollback(); return [f"Phiếu {p['pass_no']} không ở trạng thái 'đang trong bãi' (đã ra hoặc chưa vào)."]
    img = None; read = clean(container_read)
    if job and job.get("result"):
        img = _evidence_copy(job["result"].get("proc_path"), p["pass_no"], "out.jpg")
        if img: db.execute("UPDATE gate_passes SET out_image=? WHERE id=?", (img, pid))
    how = "thanh toán trước tại cổng" if prepay else ("công nợ, hạn " + time.strftime("%d/%m/%Y", time.localtime(due)) if due else "miễn phí")
    note = f"XÁC NHẬN RA BÃI (xác minh {'QR' if scan == 'qr' else 'nhập số phiếu tay'}; biển đọc: {clean(plate_read)}; {how})" + (f"; LỆCH [{', '.join(bad)}], cho ra bởi {user['full_name']}: {reason}" if bad else "")
    _ev(db, pid, "out", user["id"], note, read, (job or {}).get("result", {}).get("votes") if job else None, None, img, (job or {}).get("id"), 1 if bad else 0)
    sys_msg(db, p, "out", now, f"Ở bãi {dur_text(now - (p['in_at'] or p['created_at']))}. " + ("Miễn phí lưu bãi." if free else (f"Tiền bãi {money(fee['total'])}, đã thanh toán tại cổng." if prepay else f"Tiền bãi {money(fee['total'])}, hạn thanh toán {time.strftime('%d/%m/%Y', time.localtime(due))}.")))
    db.commit(); D.audit(db, user["id"], "pass_out", p["pass_no"], ("LỆCH: " + reason) if bad else ""); return []

def cancel_pass(db, user, pid, reason):
    if user["role"] not in OPS: return [NOT_OPS]
    p = db.execute("SELECT * FROM gate_passes WHERE id=?", (pid,)).fetchone()
    if p is None or len((reason or "").strip()) < 3: return ["Phải ghi lý do huỷ."]
    cur = db.execute("UPDATE gate_passes SET status='rejected', cancel_reason=? WHERE id=? AND status='pending'", (reason.strip()[:200], pid))
    if cur.rowcount != 1: db.rollback(); return ["Chỉ huỷ được phiếu đang chờ xác nhận vào bãi."]
    _ev(db, pid, "in", user["id"], "HUỶ PHIẾU: " + reason.strip()[:200]); db.commit(); D.audit(db, user["id"], "pass_cancel", p["pass_no"], reason[:100]); return []

# ---------------------------------------------------------------- chữ ký (ảnh tải lên)
def sig_file(uid): return SIG_DIR / f"{int(uid)}.png"
def has_sig(uid): return sig_file(uid).exists()
def delete_signature(uid):
    try: sig_file(uid).unlink()
    except FileNotFoundError: pass

def save_signature(uid, data):
    """Nhận ảnh PNG/JPG chữ ký, bỏ nền trắng (nét ký thành mực xanh trên nền trong suốt), cắt sát, thu về tối đa 360x140. Trả (ok, lỗi)."""
    if len(data) > 1_500_000: return False, "Ảnh quá lớn (tối đa 1,5 MB)."
    if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"): return False, "Chỉ nhận ảnh PNG hoặc JPG."
    SIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import io
        from PIL import Image, ImageOps
    except ImportError:
        if data[:4] == b"\x89PNG": sig_file(uid).write_bytes(data); return True, ""
        return False, "Cần cài Pillow để nhận ảnh JPG: python -m pip install pillow (hoặc dùng ảnh PNG)."
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
        if im.width * im.height > 25_000_000: return False, "Ảnh quá lớn."
        al = im.split()[3]
        if al.getextrema()[0] >= 250: al = im.convert("L").point(lambda v: 0 if v >= 235 else (255 if v <= 170 else int((235 - v) * 255 / 65)))   # ảnh chụp trên giấy trắng
        box = al.getbbox()
        if box is None or al.point(lambda v: 255 if v > 128 else 0).histogram()[255] < 40: return False, "Không thấy nét ký trong ảnh (ảnh trắng hoặc quá nhạt). Ký đậm trên giấy trắng rồi chụp lại."
        out = Image.new("RGBA", im.size, (10, 20, 90, 0)); out.putalpha(al)
        m = 8; out = out.crop((max(0, box[0] - m), max(0, box[1] - m), min(im.width, box[2] + m), min(im.height, box[3] + m))); out.thumbnail((360, 140), Image.LANCZOS)
        out.save(sig_file(uid), "PNG", optimize=True)
    except Exception: return False, "Không đọc được ảnh này. Hãy thử ảnh PNG/JPG khác."
    return True, ""

def snapshot_signature(uid, pass_id, who):
    """Chép chữ ký hiện tại vào bản lưu riêng của phiếu để về sau đổi chữ ký không làm đổi phiếu cũ. Trả đường dẫn tương đối hoặc None."""
    src = sig_file(uid)
    if not src.exists(): return None
    d = SIG_DIR / "snap"; d.mkdir(parents=True, exist_ok=True); name = f"{int(pass_id)}_{who}.png"; shutil.copyfile(src, d / name); return f"snap/{name}"

# ---------------------------------------------------------------- thanh toán
def voucher_no(p): return p["pass_no"].replace("PASS-", "PT-", 1)
def voucher_state(p):
    """(nhãn, nhóm) nhóm: free | wait | cust | bai | done"""
    paid, conf = bool(p["fee_paid"]), bool(p["cust_confirmed_at"])
    if (p["fee_total"] or 0) == 0: return "Miễn phí lưu bãi", "free"
    if paid and conf: return "Đã thanh toán đầy đủ", "done"
    if conf: return "Khách đã xác nhận, chờ bãi nhận tiền", "cust"
    if paid: return "Bãi đã nhận tiền, chờ khách xác nhận", "bai"
    return "Chờ thanh toán", "wait"

def receive_payment(db, user, pid, method, ref=""):
    if user["role"] not in OPS: return [NOT_OPS]
    if method not in ("cash", "transfer", "other"): return ["Chọn hình thức thanh toán."]
    cur = db.execute("UPDATE gate_passes SET fee_paid=1, paid_at=?, paid_by=?, pay_method=?, pay_ref=? WHERE id=? AND status='closed' AND fee_paid=0 AND COALESCE(fee_total,0)>0",
                     (time.time(), user["id"], method, (ref or "").strip()[:60] or None, pid))
    if cur.rowcount != 1: db.rollback(); return ["Phiếu chưa ra bãi, đã thu tiền rồi, hoặc không phát sinh tiền."]
    db.commit(); D.audit(db, user["id"], "pay_receive", str(pid), method); return []

def cust_confirm(db, user, pid, counter=False):
    """Khách tự xác nhận (chữ ký của tài khoản khách in vào phiếu, không có thì đóng dấu đỏ) hoặc nhân viên ghi nhận tại quầy (luôn đóng dấu đỏ)."""
    p = db.execute("SELECT * FROM gate_passes WHERE id=?", (pid,)).fetchone()
    if p is None: return ["Không có phiếu."]
    if counter:
        if user["role"] not in OPS: return [NOT_OPS]
        sig, mode = "", "counter"
    else:
        if user["role"] != "customer" or p["customer_id"] != user["id"]: return ["Chỉ khách hàng của phiếu này mới tự xác nhận được."]
        sig, mode = snapshot_signature(user["id"], pid, "cust") or "", "self"
    cur = db.execute("UPDATE gate_passes SET cust_confirmed_at=?, cust_confirmed_by=?, cust_mode=?, cust_sig=? WHERE id=? AND status='closed' AND cust_confirmed_at IS NULL AND COALESCE(fee_total,0)>0",
                     (time.time(), user["id"], mode, sig, pid))
    if cur.rowcount != 1: db.rollback(); return ["Phiếu chưa ra bãi, đã xác nhận rồi, hoặc không phát sinh tiền."]
    db.commit(); D.audit(db, user["id"], "pay_confirm_" + mode, p["pass_no"], ""); return []

# ---------------------------------------------------------------- công nợ, hạn thanh toán, gia hạn
def due_of(p): return p["due_at"] or ((p["out_at"] or 0) + 30 * 86400)
def is_done(p): return bool(p["fee_paid"]) and bool(p["cust_confirmed_at"])

def debts(db, user, cust="", q="", urgent=False, warn_days=15):
    """Phiếu đã ra bãi, có tiền, CHƯA đủ 2 xác nhận. Khách chỉ thấy của mình."""
    sql, args = "SELECT * FROM gate_passes WHERE status='closed' AND COALESCE(fee_total,0)>0", []
    if user["role"] == "customer": sql += " AND customer_id=?"; args.append(user["id"])
    elif cust == "walkin": sql += " AND customer_id IS NULL"
    elif str(cust).isdigit(): sql += " AND customer_id=?"; args.append(int(cust))
    k = clean(q)
    if q.strip(): sql += " AND (pass_no LIKE ? OR owner_name LIKE ?" + (" OR container_no LIKE ? OR plate_key LIKE ?" if k else "") + ")"; args += [f"%{q.strip()}%"] * 2 + ([f"%{k}%"] * 2 if k else [])
    now = time.time(); rows = [r for r in db.execute(sql + " ORDER BY out_at", args) if not is_done(r)]
    if urgent: rows = [r for r in rows if not r["cust_confirmed_at"] and due_of(r) - now <= warn_days * 86400]
    return rows

def urgent(db):
    """(số phiếu khách chưa xác nhận mà còn <= warn_days tới hạn hoặc quá hạn, hạn gần nhất). Dùng cho cục đỏ của nhân viên."""
    wd = int(D.get_setting(db, "warn_days", "15") or 15); rows = [r for r in db.execute("SELECT * FROM gate_passes WHERE status='closed' AND COALESCE(fee_total,0)>0 AND cust_confirmed_at IS NULL")
                                                              if due_of(r) - time.time() <= wd * 86400]
    return len(rows), (min(due_of(r) for r in rows) if rows else None)

def bulk(db, user, ids, fn):
    ok, errs = 0, []
    for i in dict.fromkeys(int(x) for x in ids if str(x).isdigit()):
        e = fn(i)
        if e: errs.append(e[0])
        else: ok += 1
    return ok, errs

def extend_due(db, user, ids, days, reason):
    """Chỉ chủ (admin boss): gia hạn thêm N ngày cho các phiếu chưa đủ xác nhận. Lý do bắt buộc và được lưu."""
    if user["role"] != "admin": return ["Chỉ Admin boss được gia hạn."]
    if not (1 <= days <= 365) or len((reason or "").strip()) < 5: return ["Số ngày gia hạn 1-365 và phải ghi lý do (ít nhất 5 ký tự)."]
    n = 0
    for i in dict.fromkeys(int(x) for x in ids if str(x).isdigit()):
        p = db.execute("SELECT * FROM gate_passes WHERE id=? AND status='closed' AND COALESCE(fee_total,0)>0", (i,)).fetchone()
        if p is None or is_done(p): continue
        db.execute("UPDATE gate_passes SET due_at=?, due_ext_by=?, due_ext_reason=? WHERE id=?", (due_of(p) + days * 86400, user["id"], reason.strip()[:200], i)); n += 1
        D.audit(db, user["id"], "due_extend", p["pass_no"], f"+{days} ngày: {reason.strip()[:100]}")
    db.commit()
    return [] if n else ["Không có phiếu nào gia hạn được (đã đủ xác nhận hoặc chưa ra bãi)."]

SORTS = {"created": "created_at", "in": "in_at", "out": "out_at", "container": "container_no", "plate": "plate_key", "status": "status", "fee": "fee_total", "pass": "id"}
def search(db, user, q="", status="", d_from="", d_to="", limit=300, size="", mode="", paid="", party="", sort="created", direction="desc"):
    sql, args = "SELECT * FROM gate_passes WHERE 1=1", []
    if user["role"] == "customer": sql += " AND customer_id=?"; args.append(user["id"])
    q = (q or "").strip()
    if q:
        k = clean(q); like = f"%{q}%"
        sql += " AND (pass_no LIKE ? OR owner_name LIKE ? OR owner_phone LIKE ?" + (" OR container_no LIKE ? OR plate_key LIKE ?" if k else "") + ")"
        args += [like, like, like] + ([f"%{k}%", f"%{k}%"] if k else [])
    if status in PASS_STATUS: sql += " AND status=?"; args.append(status)
    if size in SIZES: sql += " AND size=?"; args.append(size)
    if mode in ("manual", "auto"): sql += " AND mode=?"; args.append(mode)
    if party in FEE_PARTIES: sql += " AND fee_party=?"; args.append(party)
    if paid == "paid": sql += " AND status='closed' AND fee_paid=1"
    elif paid == "unpaid": sql += " AND status='closed' AND fee_paid=0"
    for v, op in ((d_from, ">="), (d_to, "<")):
        try:
            t = time.mktime(time.strptime(v, "%Y-%m-%d")) + (86400 if op == "<" else 0)
            sql += f" AND created_at {op} ?"; args.append(t)
        except (ValueError, TypeError): pass
    col = SORTS.get(sort, "created_at"); dr = "ASC" if direction == "asc" else "DESC"
    return db.execute(sql + f" ORDER BY ({col} IS NULL), {col} {dr}, id DESC LIMIT ?", (*args, limit)).fetchall()

# ---------------------------------------------------------------- chạy mô hình YOLO nền (chế độ TỰ ĐỘNG)
JOBS = {}; _RUN_LOCK = threading.Lock()

def real_runner(job, model, imgsz, conf):
    """Gọi python/test_video_model.py giống công cụ cũ (kết quả cố định ở result/12_video_test rồi chép vào thư mục job)."""
    import os
    cmd = [sys.executable, "-u", str(ROOT / "python" / "test_video_model.py"), "--source", str(job["src"]), "--model", model, "--imgsz", str(imgsz), "--fps", "3",
           "--conf", str(conf), "--backend", "ultralytics", "--read", "--save-cut"]
    job["log"].append("Lệnh: " + " ".join(cmd))
    out = ROOT / "result" / "12_video_test"; shutil.rmtree(out, ignore_errors=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
    t0 = time.time()
    for line in p.stdout:
        job["log"].append(line.rstrip()[:300]); del job["log"][:-120]
        if time.time() - t0 > 600: p.kill(); job["log"].append("Quá 10 phút, đã dừng."); break
    rc = p.wait()
    if rc != 0: raise RuntimeError(f"Mô hình thoát với mã {rc}. Xem nhật ký bên dưới (thường là thiếu thư viện hoặc sai đường dẫn model).")
    dst = Path(job["dir"]) / "out"; shutil.rmtree(dst, ignore_errors=True); shutil.copytree(out, dst, ignore=shutil.ignore_patterns("annotated.mp4"))
    return dst

def summarize(outdir):
    """Đọc results.json của test_video_model.py -> dict gọn."""
    outdir = Path(outdir); data = json.loads((outdir / "results.json").read_text(encoding="utf-8")); frames = data.get("frames", []); final = data.get("final", [])
    f0 = final[0] if final else {}; pick = next((f for f in frames if f.get("cat") == "A"), frames[0] if frames else None)
    proc = outdir / "frames_processed" / pick["file"] if pick else None; cut = outdir / "frames_cut" / pick["file"] if pick else None
    crops = sorted((outdir / "crops").glob("container-number_00_*.jpg")) or sorted((outdir / "crops").glob("container-number_*.jpg"))
    raw = pick["text"] if pick else ""
    return {"code": f0.get("code", ""), "votes": f0.get("votes", 0), "note": f0.get("note", ""), "frames_n": len(frames), "raw_text": raw, "status": pick["status"] if pick else "",
            "proc_path": str(proc) if proc and proc.exists() else None, "cut_path": str(cut) if cut and cut.exists() else None, "crop_path": str(crops[0]) if crops else None}

RUNNER = real_runner   # test thay bằng hàm giả
PLATE_OCR = lambda p: __import__("portal_ocr").extract_plate(p)
PAPER_OCR = lambda p: __import__("portal_ocr").extract_paper(p)

def start_job(user_id, purpose, filename, data, pass_id=None, scan="", extras=None):
    """extras: {'plate': (tên file, bytes), 'paper': (tên file, bytes)} (đều tuỳ chọn, chỉ ảnh)."""
    jid = secrets.token_hex(6); d = JOBS_DIR / jid; d.mkdir(parents=True, exist_ok=True)
    src = d / ("source" + (Path(filename).suffix.lower() if Path(filename).suffix.lower() in UPLOAD_EXT else ".jpg")); src.write_bytes(data)
    paths = {}
    for k, (fn, b) in (extras or {}).items():
        if b and Path(fn).suffix.lower() in IMG_EXT: paths[k] = d / (k + Path(fn).suffix.lower()); paths[k].write_bytes(b)
    job = {"id": jid, "user_id": user_id, "purpose": purpose, "pass_id": pass_id, "scan": scan, "src": str(src), "dir": str(d), "status": "queued", "log": [], "result": None, "error": "", "t0": time.time(),
           "has_plate": "plate" in paths, "has_paper": "paper" in paths}
    JOBS[jid] = job
    def work():
        with _RUN_LOCK:
            job["status"] = "running"
            try:
                conn = D.connect()
                try: model, imgsz, conf = D.get_setting(conn, "model_path"), D.get_setting(conn, "imgsz", "960"), D.get_setting(conn, "conf", "0.25")
                finally: conn.close()
                mp = Path(model); mp = mp if mp.is_absolute() else ROOT / mp
                if not mp.exists(): raise RuntimeError(f"Không thấy file model: {mp}. Sửa đường dẫn ở trang 'Bảng giá & mô hình'.")
                out = RUNNER(job, str(mp), imgsz, conf); res = summarize(out); res["ocr_notes"] = []
                if "plate" in paths:
                    res["plate_path"] = str(paths["plate"])
                    try:
                        r = PLATE_OCR(str(paths["plate"])); res.update(plate_text=r.get("plate", ""), plate_how=r.get("how", ""), plate_source=r.get("source", ""), plate_raw=r.get("raw", []))
                        if r.get("note"): res["ocr_notes"].append(r["note"])
                    except Exception as e: res["ocr_notes"].append(f"Không đọc được biển số: {e}")
                if "paper" in paths:
                    try:
                        r = PAPER_OCR(str(paths["paper"])); res.update(owner_name=r.get("name", ""), owner_phone=r.get("phone", ""), paper_raw=r.get("raw", []))
                    except Exception as e: res["ocr_notes"].append(f"Không đọc được giấy tờ: {e}")
                    finally:
                        try: paths["paper"].unlink()          # không giữ ảnh giấy tờ tuỳ thân; chỉ giữ tên + SĐT người dùng xác nhận
                        except OSError: pass
                job["result"] = res; job["status"] = "done"
            except Exception as e:
                job["status"] = "error"; job["error"] = f"{type(e).__name__}: {e}"
                for k in ("paper",):
                    try: paths[k].unlink()
                    except (KeyError, OSError): pass
    threading.Thread(target=work, daemon=True).start(); return job
