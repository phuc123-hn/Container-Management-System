"""
Tự kiểm tra phiếu điện tử: tiền bãi, mã QR, vào/ra bãi, đối chiếu lệch, phân quyền, tìm kiếm, luồng TỰ ĐỘNG (dùng mô hình giả).
Chạy:  python python/test_gate.py     (CSDL tạm, không đụng data/smartport.db)
"""
import http.client, json, os, re, sys, tempfile, threading, time, uuid
from http.cookies import SimpleCookie
from urllib.parse import urlencode

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
tmp = tempfile.mkdtemp(); os.environ["SMARTPORT_DB"] = os.path.join(tmp, "g.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portal_db as D, portal_gate as G, portal_app as A
from pathlib import Path
from http.server import ThreadingHTTPServer
G.EVID = Path(tmp) / "evidence"; G.JOBS_DIR = Path(tmp) / "jobs"; G.SIG_DIR = Path(tmp) / "sig"
D.init_db(); (Path(tmp) / "m.pt").write_bytes(b"x"); _c = D.connect(); D.set_setting(_c, "model_path", str(Path(tmp) / "m.pt")); _c.close()
srv = ThreadingHTTPServer(("127.0.0.1", 0), A.H); PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

class C:
    def __init__(self): self.ck = {}
    def req(self, method, path, form=None, files=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30); hd = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.ck.items())}; body = None
        if files is not None:
            b = "XBOUNDARY" + uuid.uuid4().hex; parts = b""
            for k, v in (form or {}).items(): parts += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, (fn, data) in files.items(): parts += f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + data + b"\r\n"
            body = parts + f"--{b}--\r\n".encode(); hd["Content-Type"] = f"multipart/form-data; boundary={b}"
        elif form is not None: body = urlencode(form, doseq=True); hd["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body, hd); r = c.getresponse(); raw = r.read()
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                for n, m in SimpleCookie(v).items():
                    if m.value: self.ck[n] = m.value
        return r.status, dict(r.getheaders()), raw
    def txt(self, *a, **k): s, h, b = self.req(*a, **k); return s, h, b.decode("utf-8", "replace")
    def csrf(self): return re.search(r'name="csrf" value="([^"]+)"', self.txt("GET", "/")[2]).group(1)

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print(f"  ĐẠT  {name}")
    else: bad += 1; print(f"  LỖI  {name} {extra}")

# ---------------- thuần logic
check("EITU1841398 hợp lệ ISO 6346", G.is_valid_container("EITU1841398")); check("EITU1841397 không hợp lệ", not G.is_valid_container("EITU1841397"))
check("parse QR đúng", G.parse_scan("spass|PASS-20261029-0001|0123456789") == ("PASS-20261029-0001", "0123456789") and G.parse_scan("PASS-20261029-0001") == ("PASS-20261029-0001", None) and G.parse_scan("abc") == (None, None))
he, hg, same = G.marks("EITU1841398", "EITU1841396"); check("so chuỗi: tô đỏ đúng ký tự khác", not same and hg.endswith('<span class="x">6</span>') and he.count('class="x"') == 1)
db = D.connect()
fee = lambda size, days_s: G.fee_calc(db, size, 0, days_s)
check("tiền bãi 40ft: 3 ngày trọn miễn phí, dưới 1 ngày vẫn miễn phí", fee("40", 3 * 86400)["total"] == 0 and fee("40", 100)["total"] == 0 and fee("40", 100)["days"] == 0)
check("tiền bãi 40ft: 3 ngày + 1 giây = phần dư tính 1 giờ (70.000/24 = 2.917), KHÔNG làm tròn lên cả ngày", fee("40", 3 * 86400 + 1)["total"] == 2917)
check("tiền bãi 40ft: 12 ngày = 7×70.000 + 2×140.000 = 770.000", fee("40", 12 * 86400)["total"] == 770000)
check("tiền bãi 20ft: 12 ngày = 7×40.000 + 2×80.000 = 440.000", fee("20", 12 * 86400)["total"] == 440000)
check("định dạng tiền", G.money(1234567) == "1.234.567 đ")
for u, role in (("gate1", "gate"), ("disp1", "gate"), ("boss", "admin"), ("cust1", "customer"), ("cust2", "customer")): D.create_user(db, u, u.upper(), "", "Cty " + u, "Matkhau123", role=role, status="active")
cust1 = db.execute("SELECT id FROM users WHERE username='cust1'").fetchone()[0]; db.execute("UPDATE users SET pay_terms='credit', credit_days=30 WHERE id=?", (cust1,)); db.commit(); db.close()   # cust1 = khách công nợ; cust2 = trả trước
def login(u):
    c = C(); s, _, _ = c.req("POST", "/login", {"username": u, "password": "Matkhau123"}); assert s == 303; return c
gate, disp, boss, c1, c2 = login("gate1"), login("disp1"), login("boss"), login("cust1"), login("cust2")

# ---------------- tạo phiếu thủ công
base = {"container_no": "EITU1841398", "size": "40", "truck_plate": "51c-123.45", "owner_name": "Nguyễn Văn A", "owner_phone": "0909 123 456", "customer_id": str(cust1), "fee_party": "chu_xe"}
s, _, t = gate.txt("GET", "/gate"); check("bảo vệ vào được màn hình cổng", s == 200 and "Cho xe VÀO bãi" in t)
s, _, _ = c1.txt("GET", "/gate"); check("khách hàng KHÔNG vào được màn hình cổng", s == 403)
s, _, t = gate.txt("POST", "/gate/in/manual", {"csrf": gate.csrf(), **base, "container_no": "EITU1841397", "act": "create"}); check("mã sai số kiểm tra bị chặn + gợi ý số đúng", "ISO 6346" in t and "phải là 8" in t)
s, _, t = gate.txt("POST", "/gate/in/manual", {"csrf": gate.csrf(), **base, "container_no": "EITU18", "act": "create"}); check("mã thiếu ký tự bị chặn", "4 chữ cái + 7 số" in t)
s, _, t = gate.txt("POST", "/gate/in/manual", {**base, "act": "create"}); check("tạo phiếu không có csrf bị từ chối", s == 403)
s, h, _ = gate.txt("POST", "/gate/in/manual", {"csrf": gate.csrf(), **base, "act": "create"}); check("tạo phiếu thủ công -> chuyển sang trang phiếu", s == 303 and re.fullmatch(r"/pass/\d+\?m=created", h["Location"]))
pid = int(re.search(r"/pass/(\d+)", h["Location"]).group(1)); s, _, t = gate.txt("GET", f"/pass/{pid}")
day = time.strftime("%Y%m%d"); check("số phiếu dạng PASS-ngày-0001", f"PASS-{day}-0001" in t)
check("biển số chuẩn hoá chữ hoa", "51C-123.45" in t); check("trạng thái chờ xác nhận vào bãi", "Chờ xác nhận vào bãi" in t and "Xác nhận VÀO bãi" in t)
check("trang phiếu có mã QR (SVG)", "<svg" in t and "SPASS|PASS-" in t, "(cần: pip install segno)")
s, _, t = gate.txt("POST", "/gate/in/manual", {"csrf": gate.csrf(), **base, "act": "create"}); check("trùng container đang có phiếu mở bị chặn", "đang có phiếu mở" in t)
s, h, _ = gate.txt("POST", f"/pass/{pid}/in/confirm", {"csrf": gate.csrf()}); s, _, t = gate.txt("GET", f"/pass/{pid}")
check("xác nhận VÀO bãi -> Đang trong bãi + đồng hồ + tạm tính", "ĐANG TRONG BÃI" in t and "Tiền bãi" in t and "Tạm tính" in t and 'http-equiv="refresh"' in t)
s, _, t = gate.txt("POST", f"/pass/{pid}/in/confirm", {"csrf": gate.csrf()}); check("xác nhận vào lần 2 bị từ chối", s == 409)
s, _, t = c1.txt("GET", f"/pass/{pid}"); check("khách được gắn tài khoản xem được phiếu của mình (có QR)", s == 200 and "<svg" in t and "Xác nhận VÀO" not in t and "Xác minh và cho RA" not in t)
s, _, _ = c2.txt("GET", f"/pass/{pid}"); check("khách khác KHÔNG xem được phiếu này (404)", s == 404)
s, _, t = c1.txt("GET", "/passes"); check("khách chỉ thấy phiếu của mình trong danh sách", "EITU1841398" in t); s, _, t = c2.txt("GET", "/passes"); check("khách khác thấy danh sách rỗng", "EITU1841398" not in t)
# ---------------- tìm kiếm
for q in ("EITU18", "51c12345", "123.45", "nguyễn", "0909", f"PASS-{day}-0001"):
    s, _, t = gate.txt("GET", "/passes?" + urlencode({"q": q})); check(f"tìm kiếm '{q}' ra phiếu", f"PASS-{day}-0001" in t)
s, _, t = gate.txt("GET", "/passes?q=ZZZZ9999"); check("tìm không có -> rỗng", "Không có phiếu phù hợp" in t)
s, _, t = gate.txt("GET", "/passes?status=closed"); check("lọc trạng thái 'đã ra' -> chưa có", "Không có phiếu phù hợp" in t)
# ---------------- cổng ra: quét QR
p = D.connect().execute("SELECT * FROM gate_passes WHERE id=?", (pid,)).fetchone(); payload = G.qr_payload(p)
s, h, _ = gate.txt("POST", "/gate/out/find", {"csrf": gate.csrf(), "scan": "SPASS|" + p["pass_no"] + "|0000000000"}); s2, _, t = gate.txt("POST", "/gate/out/find", {"csrf": gate.csrf(), "scan": "SPASS|" + p["pass_no"] + "|0000000000"})
check("QR có token SAI bị từ chối", s2 == 200 and "không khớp" in t)
s, h, _ = gate.txt("POST", "/gate/out/find", {"csrf": gate.csrf(), "scan": payload}); check("QR đúng -> sang trang xác minh (m=qr)", s == 303 and h["Location"] == f"/pass/{pid}/out?m=qr")
s, h, _ = gate.txt("POST", "/gate/out/find", {"csrf": gate.csrf(), "scan": p["pass_no"]}); s, _, t = gate.txt("GET", h["Location"]); check("gõ số phiếu tay -> có cảnh báo không quét QR", "KHÔNG quét QR" in t)
s, _, t = gate.txt("POST", f"/pass/{pid}/out/check", {"csrf": gate.csrf(), "container_read": "EITU1841396", "plate_read": "51C-123.45", "m": "qr"})
check("container lệch 1 ký tự: báo LỆCH + tô đỏ ký tự 6", "LỆCH Ở 1 DÒNG: Số container" in t and '<span class="x">6</span>' in t and '<span class="x">8</span>' in t)
check("lệch: nhân viên có nút 'Cho ra dù lệch' bắt buộc ghi lý do, KHÔNG có nút xác nhận thường", "Cho ra dù lệch" in t and "XÁC NHẬN RA BÃI" not in t and 'name="reason"' in t)
s, _, t = gate.txt("POST", f"/pass/{pid}/out/confirm", {"csrf": gate.csrf(), "container_read": "EITU1841396", "plate_read": "51C-123.45", "m": "qr", "reason": ""}); check("cho ra khi lệch mà KHÔNG ghi lý do -> bị chặn phía máy chủ", s == 409 and "lý do" in t)
s, _, t = gate.txt("POST", f"/pass/{pid}/out/check", {"csrf": gate.csrf(), "container_read": "EITU1841398", "plate_read": "51C-123.54", "m": "qr"})
check("biển số lệch (đảo 45/54) cũng được chỉ ra", "LỆCH Ở 1 DÒNG: Biển số xe" in t and t.count('class="x"') >= 2)
s, _, t = gate.txt("POST", f"/pass/{pid}/out/check", {"csrf": gate.csrf(), "container_read": "eitu 184139 8", "plate_read": "51c12345", "m": "qr"})
check("gõ khác hoa/thường, dấu cách, dấu chấm vẫn KHỚP", "KHỚP CẢ HAI DÒNG" in t and "XÁC NHẬN RA BÃI" in t)
# tạm sửa giờ vào để có tiền: vào cách đây 5 ngày
dbx = D.connect(); dbx.execute("UPDATE gate_passes SET in_at=? WHERE id=?", (time.time() - 5 * 86400 + 600, pid)); dbx.commit(); dbx.close()
s, _, t = gate.txt("GET", f"/pass/{pid}"); check("đang ở 4 ngày 23h: tạm tính 4-5 ngày = 70.000 × 2 = 140.000", "140.000 đ" in t and "4 ngày 23:" in t, re.findall(r"\d+\.\d+ đ", t)[:3])
s, h, _ = gate.txt("POST", f"/pass/{pid}/out/confirm", {"csrf": gate.csrf(), "container_read": "EITU1841398", "plate_read": "51C-123.45", "m": "qr"}); check("bảo vệ xác nhận RA khi khớp -> hoàn tất", s == 303 and h["Location"].endswith("m=out"))
s, _, t = gate.txt("GET", f"/pass/{pid}"); check("phiếu đã ra: Đã ra bãi + thành tiền 140.000 + chưa thu", "Đã ra bãi" in t and "140.000 đ" in t and "Chờ thanh toán" in t and "<svg" not in t)
r = D.connect().execute("SELECT * FROM gate_passes WHERE id=?", (pid,)).fetchone(); check("tiền được chốt trong CSDL", r["fee_total"] == 140000 and r["out_at"] and r["status"] == "closed")
s, _, _ = gate.txt("POST", f"/pass/{pid}/out/confirm", {"csrf": gate.csrf(), "container_read": "EITU1841398", "plate_read": "51C-123.45", "m": "qr"}); check("cho ra lần 2 bị từ chối", s == 409)
s, _, t = gate.txt("POST", "/gate/out/find", {"csrf": gate.csrf(), "scan": payload}); check("quét lại phiếu đã dùng bị từ chối", "không cho ra được" in t)
s, _, _ = gate.txt("POST", f"/voucher/{pid}/receive", {"csrf": gate.csrf(), "method": "cash", "ref": "BL-001"}); s, _, t = gate.txt("GET", f"/pass/{pid}"); check("bãi ghi nhận ĐÃ NHẬN TIỀN", "Bãi đã nhận tiền" in t)
# ---------------- ép ra khi lệch (điều độ)
b2 = {**base, "container_no": "CSQU3054383", "truck_plate": "60C-999.99", "customer_id": ""}
s, h, _ = gate.txt("POST", "/gate/in/manual", {"csrf": gate.csrf(), **b2, "act": "create_confirm"}); pid2 = int(re.search(r"/pass/(\d+)", h["Location"]).group(1)); check("'Tạo & xác nhận vào bãi' một bước -> m=in", h["Location"].endswith("m=in"))
s, _, t = disp.txt("POST", f"/pass/{pid2}/out/check", {"csrf": disp.csrf(), "container_read": "CSQU3054383", "plate_read": "60C-888.88"}); check("điều độ thấy nút 'Cho ra dù lệch'", "Cho ra dù lệch" in t)
s, _, t = disp.txt("POST", f"/pass/{pid2}/out/confirm", {"csrf": disp.csrf(), "container_read": "CSQU3054383", "plate_read": "60C-888.88", "reason": ""}); check("ép ra không ghi lý do -> chặn", s == 409 and "ghi lý do" in t)
s, _, _ = disp.txt("POST", f"/pass/{pid2}/out/confirm", {"csrf": disp.csrf(), "container_read": "CSQU3054383", "plate_read": "60C-888.88", "reason": "Xe thay biển do hỏng đèn, đã gọi chủ xe xác nhận"})
ev = D.connect().execute("SELECT * FROM gate_events WHERE pass_id=? AND direction='out'", (pid2,)).fetchone(); check("ép ra có lý do -> lưu manual_override + lý do vào nhật ký phiếu", ev and ev["manual_override"] == 1 and "Xe thay biển" in ev["note"])
# ---------------- huỷ phiếu
b3 = {**base, "container_no": "MSKU1234565", "truck_plate": "70A-111.11", "customer_id": ""}
print("  (mã MSKU1234565: số KT đúng =", G.check_digit("MSKU123456"), ")")
b3["container_no"] = "MSKU123456" + str(G.check_digit("MSKU123456"))
s, h, _ = gate.txt("POST", "/gate/in/manual", {"csrf": gate.csrf(), **b3, "act": "create"}); pid3 = int(re.search(r"/pass/(\d+)", h["Location"]).group(1))
s, _, _ = gate.txt("POST", f"/pass/{pid3}/cancel", {"csrf": gate.csrf(), "reason": "xe không vào nữa"}); r = D.connect().execute("SELECT status FROM gate_passes WHERE id=?", (pid3,)).fetchone(); check("huỷ phiếu chờ vào", r["status"] == "rejected")
s, _, t = gate.txt("POST", "/gate/in/manual", {"csrf": gate.csrf(), **b3, "act": "create"}); check("sau khi huỷ có thể tạo phiếu mới cho container đó", s == 303)
# ---------------- chế độ TỰ ĐỘNG với mô hình giả
FAKE = {"code": "CSQU3054383"}
def fake_runner(job, model, imgsz, conf):
    out = Path(job["dir"]) / "out"; (out / "frames_processed").mkdir(parents=True, exist_ok=True); (out / "crops").mkdir(exist_ok=True)
    (out / "frames_processed" / "f1.jpg").write_bytes(b"\xff\xd8\xff\xe0FAKEJPEG"); (out / "crops" / "container-number_00_t0.00_c0.90.jpg").write_bytes(b"\xff\xd8\xff\xe0CROP")
    rec = {"file": "f1.jpg", "t": 0, "boxes": 1, "text": FAKE["code"], "status": "HỢP LỆ", "cat": "A", "tid": None}
    (out / "results.json").write_text(json.dumps({"final": [{"group": "cả video", "code": FAKE["code"], "votes": 1, "note": "1/1 khung hợp lệ"}], "frames": [rec], "cut": True}), encoding="utf-8"); job["log"].append("giả lập xong"); return out
G.RUNNER = fake_runner
s, _, t = gate.txt("POST", "/gate/in/auto", {"csrf": gate.csrf()}, files={"media": ("x.txt", b"abc")}); check("tải file sai loại bị từ chối", "Chọn ảnh hoặc video thùng container" in t)
s, h, _ = gate.txt("POST", "/gate/in/auto", {"csrf": gate.csrf()}, files={"media": ("cont.jpg", b"\xff\xd8\xff" + b"0" * 5000)}); jid = h["Location"].split("/")[-1]; check("tải ảnh lên -> sang trang kết quả job", s == 303)
for _ in range(50):
    s, _, t = gate.txt("GET", f"/job/{jid}")
    if "Kết quả đọc" in t: break
    time.sleep(0.1)
check("job xong: hiện mã mô hình đọc + form nhập biển số", "Kết quả quét bằng mô hình" in t and "CSQU3054383" in t and "hợp lệ ISO 6346" in t)
s, _, b = gate.req("GET", f"/job/{jid}/img?f=proc"); check("ảnh job tải được (người tạo job)", s == 200 and b.startswith(b"\xff\xd8"))
s, _, _ = disp.req("GET", f"/job/{jid}/img?f=proc"); check("người khác (không phải chủ job/admin) KHÔNG xem được ảnh job", s == 404)
s, _, _ = boss.req("GET", f"/job/{jid}/img?f=proc"); check("Admin boss không thao tác cổng nên không xem ảnh job (403)", s == 403)
s, _, _ = gate.req("GET", f"/job/{jid}/img?f=../../etc/passwd"); check("tham số f lạ không đọc được file tuỳ ý", s == 404)
# CSRF phiếu đã có container CSQU3054383 đã ra bãi (pid2) nên tạo mới được
s, h, _ = gate.txt("POST", f"/job/{jid}/create_in", {"csrf": gate.csrf(), "container_no": "CSQU3054383", "size": "20", "truck_plate": "29H-456.78", "fee_party": "hang_tau", "act": "create_confirm"})
pid4 = int(re.search(r"/pass/(\d+)", h["Location"]).group(1)); r = D.connect().execute("SELECT * FROM gate_passes WHERE id=?", (pid4,)).fetchone()
check("phiếu tự động: mode=auto, vào bãi, có ảnh bằng chứng", r["mode"] == "auto" and r["status"] == "inside" and r["in_image"] and (G.EVID / r["in_image"]).exists())
s, _, b = gate.req("GET", f"/evidence/{pid4}/in"); check("ảnh bằng chứng phục vụ cho nhân viên", s == 200 and b.startswith(b"\xff\xd8"))
s, _, _ = c1.req("GET", f"/evidence/{pid4}/in"); check("khách hàng KHÔNG xem ảnh bằng chứng", s == 404)
ev = D.connect().execute("SELECT * FROM gate_events WHERE pass_id=? ORDER BY id", (pid4,)).fetchone(); check("sự kiện lưu mã đọc, số khung, mô hình", ev["container_read"] == "CSQU3054383" and ev["votes"] == 1 and ev["run_id"] == jid and ev["manual_override"] == 0)
# tự động lúc ra
s, h, _ = gate.txt("POST", f"/pass/{pid4}/out/auto", {"csrf": gate.csrf(), "m": "qr"}, files={"media": ("out.jpg", b"\xff\xd8\xff" + b"1" * 3000)}); jid2 = h["Location"].split("/")[-1]
for _ in range(50):
    s, _, t = gate.txt("GET", f"/job/{jid2}")
    if "Kết quả đọc" in t: break
    time.sleep(0.1)
check("job lúc ra: form nhập biển số + đối chiếu", f"/pass/{pid4}/out/check" in t)
s, _, t = gate.txt("POST", f"/pass/{pid4}/out/check", {"csrf": gate.csrf(), "container_read": "CSQU3054383", "plate_read": "29H-456.78", "m": "qr", "job_id": jid2}); check("đối chiếu có ảnh lúc ra", "KHỚP CẢ HAI DÒNG" in t and f"/job/{jid2}/img" in t)
s, _, _ = gate.txt("POST", f"/pass/{pid4}/out/confirm", {"csrf": gate.csrf(), "container_read": "CSQU3054383", "plate_read": "29H-456.78", "m": "qr", "job_id": jid2}); r = D.connect().execute("SELECT * FROM gate_passes WHERE id=?", (pid4,)).fetchone()
check("ra bãi tự động: closed + ảnh lúc ra", r["status"] == "closed" and r["out_image"] and (G.EVID / r["out_image"]).exists())
# job lỗi
def bad_runner(job, *a): raise RuntimeError("giả lập thiếu ultralytics")
G.RUNNER = bad_runner
s, h, _ = gate.txt("POST", "/gate/in/auto", {"csrf": gate.csrf()}, files={"media": ("c.jpg", b"\xff\xd8\xff" + b"0" * 100)}); j3 = h["Location"].split("/")[-1]
for _ in range(50):
    s, _, t = gate.txt("GET", f"/job/{j3}")
    if "Mô hình chạy lỗi" in t: break
    time.sleep(0.1)
check("mô hình lỗi: báo rõ + cho làm thủ công", "giả lập thiếu ultralytics" in t and "thủ công" in t)

# ================================================================ BƯỚC 3: quét biển số + giấy tờ, lọc/nhóm, thời gian, chữ ký, phiếu thanh toán
mk = lambda p10: p10 + str(G.check_digit(p10))
def new_pass(cl, cont, plate, cust="", size="40", confirm=True):
    s, h, _ = cl.txt("POST", "/gate/in/manual", {"csrf": cl.csrf(), "container_no": cont, "size": size, "truck_plate": plate, "customer_id": str(cust), "fee_party": "chu_xe", "owner_name": "Tài xế " + plate, "act": "create_confirm" if confirm else "create"})
    assert s == 303, (s, cont); return int(re.search(r"/pass/(\d+)", h["Location"]).group(1))
def close_pass(cl, pid, cont, plate, days_ago=None):
    if days_ago is not None:
        x = D.connect(); x.execute("UPDATE gate_passes SET in_at=? WHERE id=?", (time.time() - days_ago * 86400, pid)); x.commit(); x.close()
    x = D.connect(); fee, terms, cd, prepay = G.exit_quote(x, x.execute("SELECT * FROM gate_passes WHERE id=?", (pid,)).fetchone()); x.close()
    form = {"csrf": cl.csrf(), "container_read": cont, "plate_read": plate, "m": "qr"}
    if prepay: form.update({"pay_method": "cash", "pay_ref": "TEST", "pay_received": "1", "pay_confirmed": "1", "fee_expected": str(fee["total"])})
    s, _, _ = cl.txt("POST", f"/pass/{pid}/out/confirm", form); assert s == 303, s
row = lambda pid: D.connect().execute("SELECT * FROM gate_passes WHERE id=?", (pid,)).fetchone()

# ---- A. tự động: biển số + giấy tờ + đủ trường như thủ công
CA = mk("TGHU027862")
FAKE["code"] = CA
G.PLATE_OCR = lambda p: {"plate": "29H-456.78", "how": "một dòng", "source": "CCT", "raw": ["29H-456.78"], "note": ""}
G.PAPER_OCR = lambda p: {"name": "Nguyễn Văn An", "phone": "0909123456", "raw": ["Tài xế: Nguyễn Văn An", "SĐT 0909123456"]}
G.RUNNER = fake_runner
s, _, t = gate.txt("GET", "/gate/in"); check("form tự động có ô ảnh biển số + ảnh giấy tờ + cam kết xoá ảnh giấy tờ", 'name="plate"' in t and 'name="paper"' in t and "không lưu ảnh giấy tờ" in t)
s, _, t = gate.txt("POST", "/gate/in/auto", {"csrf": gate.csrf()}, files={"media": ("c.jpg", b"\xff\xd8\xff" + b"0" * 100), "plate": ("p.txt", b"hello")}); check("ảnh biển số không phải ảnh bị từ chối", "Ảnh biển số phải là ảnh" in t)
s, h, _ = gate.txt("POST", "/gate/in/auto", {"csrf": gate.csrf()}, files={"media": ("c.jpg", b"\xff\xd8\xff" + b"0" * 300), "plate": ("p.jpg", b"\xff\xd8\xff" + b"1" * 300), "paper": ("g.jpg", b"\xff\xd8\xff" + b"2" * 300)}); jA = h["Location"].split("/")[-1]
for _ in range(60):
    s, _, t = gate.txt("GET", f"/job/{jA}")
    if "Kết quả quét" in t: break
    time.sleep(0.1)
check("kết quả tự động điền sẵn biển số, tên tài xế, SĐT", 'value="29H-456.78"' in t and 'value="Nguyễn Văn An"' in t and 'value="0909123456"' in t, t[:100])
check("kết quả tự động có đủ ô như thủ công: gắn khách hàng, ghi chú, bên trả phí", 'name="customer_id"' in t and 'name="note"' in t and 'name="fee_party"' in t and 'name="owner_phone"' in t)
check("hiển thị chữ đọc được của biển số/giấy tờ để đối chiếu", "Chữ đọc được" in t and "29H-456.78" in t and "đã được xoá sau khi đọc" in t)
check("ảnh giấy tờ bị XOÁ khỏi đĩa sau khi đọc, ảnh biển số còn", not list(Path(G.JOBS[jA]["dir"]).glob("paper.*")) and list(Path(G.JOBS[jA]["dir"]).glob("plate.*")))
s, h, _ = gate.txt("POST", f"/job/{jA}/create_in", {"csrf": gate.csrf(), "container_no": CA, "size": "40", "truck_plate": "29H-456.78", "owner_name": "Nguyễn Văn An", "owner_phone": "0909123456", "customer_id": str(cust1), "fee_party": "chu_hang", "note": "đủ giấy tờ", "act": "create_confirm"})
pidA = int(re.search(r"/pass/(\d+)", h["Location"]).group(1)); rA = row(pidA)
check("phiếu tự động có đủ: khách hàng gắn, bên trả phí, ghi chú, chủ xe, SĐT, ảnh biển số", rA["customer_id"] == cust1 and rA["fee_party"] == "chu_hang" and rA["note"] == "đủ giấy tờ" and rA["owner_name"] == "Nguyễn Văn An" and rA["owner_phone"] == "0909123456" and rA["plate_image"] and (G.EVID / rA["plate_image"]).exists())
s, _, b = gate.req("GET", f"/evidence/{pidA}/plate"); check("ảnh biển số làm bằng chứng phục vụ cho nhân viên", s == 200 and b.startswith(b"\xff\xd8")); s, _, _ = c1.req("GET", f"/evidence/{pidA}/plate"); check("khách hàng không xem ảnh biển số", s == 404)
s, _, t = c1.txt("GET", f"/pass/{pidA}"); check("khách được gắn thấy phiếu tự động của mình", s == 200 and CA in t)
G.PLATE_OCR = lambda p: (_ for _ in ()).throw(RuntimeError("thiếu RapidOCR")); 
s, h, _ = gate.txt("POST", "/gate/in/auto", {"csrf": gate.csrf()}, files={"media": ("c.jpg", b"\xff\xd8\xff" + b"0" * 300), "plate": ("p.jpg", b"\xff\xd8\xff" + b"1" * 300)}); jB = h["Location"].split("/")[-1]
for _ in range(60):
    s, _, t = gate.txt("GET", f"/job/{jB}")
    if "Kết quả quét" in t: break
    time.sleep(0.1)
check("đọc biển số lỗi: vẫn ra kết quả container + báo rõ để nhập tay", "Kết quả quét bằng mô hình" in t and "Không đọc được biển số" in t and "Chưa đọc ra biển số" in t)

# ---- B. phiếu: sắp xếp, lọc, nhóm theo container
CB1, CB2 = mk("ABCU123456"), mk("ZZZU654321")
pB1 = new_pass(gate, CB1, "11A-111.11", size="20"); pB2 = new_pass(gate, CB2, "99Z-999.99", size="45")
pos = lambda t, x: t.index(x)
s, _, t = gate.txt("GET", "/passes?sort=container&dir=asc"); check("sắp xếp container tăng dần", pos(t, CB1) < pos(t, CB2))
s, _, t = gate.txt("GET", "/passes?sort=container&dir=desc"); check("sắp xếp container giảm dần", pos(t, CB2) < pos(t, CB1))
s, _, t = gate.txt("GET", "/passes?sort=plate&dir=asc"); check("sắp xếp theo biển số", pos(t, "11A-111.11") < pos(t, "99Z-999.99"))
s, _, t = gate.txt("GET", "/passes?sort=hack;DROP+TABLE&dir=sideways"); check("tham số sắp xếp lạ không gây lỗi (rơi về mặc định)", s == 200)
s, _, t = gate.txt("GET", "/passes?sort=container&dir=asc"); check("tiêu đề cột là liên kết sắp xếp có mũi tên", "sort=container" in t and "▲" in t)
s, _, t = gate.txt("GET", "/passes?size=20"); check("lọc cỡ 20 feet", CB1 in t and CB2 not in t)
s, _, t = gate.txt("GET", "/passes?size=45"); check("lọc cỡ 45 feet", CB2 in t and CB1 not in t)
s, _, t = gate.txt("GET", "/passes?mode=auto"); check("lọc cách tạo = tự động", CA in t and CB1 not in t)
s, _, t = gate.txt("GET", "/passes?mode=manual"); check("lọc cách tạo = thủ công", CB1 in t and CA not in t)
s, _, t = gate.txt("GET", "/passes?status=inside&q=" + CB1); check("lọc trạng thái + tìm kiếm cùng lúc", CB1 in t and CB2 not in t)
s, _, t = gate.txt("GET", "/passes?view=group"); check("nhóm theo container: container 2 lượt gộp 1 nhóm", "CSQU3054383</b> · 2 lượt" in t, re.findall(r"CSQU3054383</b>[^<]{0,20}", t))
s, _, t = gate.txt("GET", "/passes?view=group&multi=1"); check("nhóm 'từ 2 lượt trở lên' chỉ còn container lặp lại", "CSQU3054383" in t and CB1 not in t and CB2 not in t)
s, _, t = c1.txt("GET", "/passes?view=group"); check("khách chỉ thấy nhóm container của mình", "EITU1841398" in t and CA in t and CB1 not in t)

# ---- C. dòng thời gian theo tháng
s, _, t = gate.txt("GET", "/timeline"); check("dòng thời gian: có SVG, trục Container, đường nối phiếu", s == 200 and "<svg" in t and "Container (trục dọc)" in t and f'href="/pass/{pid}"' in t)
check("có chấm vào + chấm ra + giờ cụ thể + hôm nay", "Vào: " in t and "Ra: " in t and "vào " in t and "bây giờ" in t and re.search(r"\d\d/\d\d \d\d:\d\d", t))
check("container đang trong bãi hiển thị riêng", "đang trong bãi" in t and CB1 in t)
s, _, t = c1.txt("GET", "/timeline"); check("khách chỉ thấy container của mình trên dòng thời gian", "EITU1841398" in t and CB1 not in t)
s, _, t = c2.txt("GET", "/timeline"); check("khách không có container -> thông báo rỗng", "Không có container nào ở bãi" in t)
s, _, t = gate.txt("GET", "/timeline?month=2020-01"); check("tháng không có dữ liệu -> thông báo rỗng", "Không có container nào ở bãi" in t)
s, _, t = gate.txt("GET", "/timeline?month=abc<script>"); check("tham số tháng sai/độc hại -> rơi về tháng này, không lỗi", s == 200 and "<script>alert" not in t)
s, _, t = gate.txt("GET", "/timeline?q=" + CB2); check("lọc theo số container", CB2 in t and CB1 not in t)
xx = D.connect(); last = time.localtime(time.time() - 40 * 86400); xx.execute("UPDATE gate_passes SET in_at=?, out_at=? WHERE id=?", (time.time() - 40 * 86400, time.time() - 38 * 86400, pB1)); xx.commit(); xx.close()
s, _, t = gate.txt("GET", f"/timeline?month={last.tm_year}-{last.tm_mon:02d}"); check("phiếu của tháng trước hiện đúng ở tháng đó", CB1 in t)
xx = D.connect(); xx.execute("UPDATE gate_passes SET in_at=?, out_at=NULL WHERE id=?", (time.time() - 40 * 86400, pB1)); xx.commit(); xx.close()
s, _, t = gate.txt("GET", "/timeline"); check("vào từ tháng trước, vẫn trong bãi: hiện mũi tên '◂ vào'", "◂ vào" in t and CB1 in t)
xx = D.connect(); xx.execute("UPDATE gate_passes SET in_at=? WHERE id=?", (time.time() - 60, pB1)); xx.commit(); xx.close()

# ---- D. đồng hồ bên phải + script có nonce
s, hd, t = gate.txt("GET", "/gate"); nonce = re.search(r"script-src 'nonce-([^']+)'", hd["Content-Security-Policy"]).group(1)
check("đồng hồ bên phải cho nhân viên + script đúng nonce", 'id="ck-time"' in t and 'id="ck-date"' in t and f'<script nonce="{nonce}">' in t and "Đang trong bãi:" in t)
s, hd2, _ = gate.txt("GET", "/gate"); check("nonce đổi theo từng lượt tải", re.search(r"nonce-([^']+)'", hd2["Content-Security-Policy"]).group(1) != nonce)
s, _, t = c1.txt("GET", "/passes"); check("khách hàng không có đồng hồ điều hành", 'id="ck-time"' not in t)
s, _, t = gate.txt("GET", f"/pass/{pB2}"); check("phiếu trong bãi có đồng hồ chạy từng giây (data-since)", "data-since=" in t)
s, hd, t = gate.txt("GET", "/login"); check("trang đăng nhập không có script", "<script" not in t)

# ---- E. chữ ký
from PIL import Image, ImageDraw
import io
def sigimg(fmt="PNG", bg=(255, 255, 255), size=(420, 160)):
    im = Image.new("RGB", size, bg); d = ImageDraw.Draw(im)
    for i in range(8): d.line([(20 + i * 45, 120), (50 + i * 45, 30), (70 + i * 45, 110)], fill=(15, 15, 40), width=5)
    b = io.BytesIO(); im.save(b, fmt); return b.getvalue()
def put(cl, data, name="s.png"): return cl.txt("POST", "/profile/signature", {"csrf": cl.csrf()}, files={"sig": (name, data)})
s, _, t = c1.txt("GET", "/profile/signature"); check("khách có trang Chữ ký, ghi rõ nếu không có thì đóng dấu đỏ", s == 200 and "Chưa có chữ ký" in t and "ĐÃ XÁC NHẬN" in t)
s, _, t = put(c1, b"hello not an image"); check("tệp không phải ảnh bị từ chối", "Chỉ nhận ảnh PNG hoặc JPG" in t)
_wb = io.BytesIO(); Image.new("RGB", (300, 100), (255, 255, 255)).save(_wb, "PNG")
s, _, t = put(c1, _wb.getvalue()); check("ảnh toàn trắng (không có nét ký) bị từ chối", "Không thấy nét ký" in t)
s, _, t = put(c1, b"\x89PNG\r\n\x1a\n" + b"0" * 1_600_000); check("ảnh quá lớn bị từ chối", "quá lớn" in t)
s, _, t = put(c1, sigimg("JPEG")); check("tải ảnh chữ ký JPG hợp lệ -> lưu", s == 303 or "Đã lưu chữ ký" in t, t[:80])
s, _, b = c1.req("GET", "/signature/me"); im = Image.open(io.BytesIO(b)).convert("RGBA")
check("chữ ký lưu dạng PNG nền trong suốt, đã cắt sát, <=360x140", b.startswith(b"\x89PNG") and im.getpixel((0, 0))[3] == 0 and im.width <= 360 and im.height <= 140, im.size)
s, _, _ = c2.req("GET", "/signature/me"); check("khách khác chưa có chữ ký -> 404 (không đọc chéo)", s == 404)
sig1 = b
put(gate, sigimg("PNG"))

# ---- F. phiếu thanh toán
s, _, t = gate.txt("GET", f"/voucher/{pB2}"); check("phiếu chưa ra bãi chưa có phiếu thanh toán", s == 409 and "chưa ra bãi" in t)
s, _, t = gate.txt("GET", f"/voucher/{pid}"); r0 = row(pid)
check("phiếu thanh toán: tiêu đề, số PT, giờ vào/ra, tiền, người lập phiếu", s == 200 and "PHIẾU THANH TOÁN LƯU BÃI" in t and G.voucher_no(r0) in t and "Thời gian vào bãi" in t and "Thời gian ra bãi" in t and "140.000 đ" in t and "Người lập phiếu" in t)
check("người lập phiếu chưa có ảnh chữ ký -> chỉ in họ tên, không có ảnh", "/sig/staff" not in t and "GATE1" in t)
check("khách chưa xác nhận: ô chữ ký trống '(chưa xác nhận)'", "(chưa xác nhận)" in t and 'class="stamp"' not in t)
s, _, t = c1.txt("GET", f"/voucher/{pid}"); check("khách của phiếu xem được + có nút xác nhận + biết chữ ký sẽ được in", s == 200 and "Tôi xác nhận đã thanh toán" in t and "Chữ ký bạn đã tải sẽ được in vào phiếu" in t)
s, _, _ = c2.txt("GET", f"/voucher/{pid}"); check("khách khác KHÔNG xem được phiếu thanh toán (404)", s == 404)
s, _, t = c2.txt("POST", f"/voucher/{pid}/confirm", {"csrf": c2.csrf()}); check("khách khác không xác nhận được phiếu của người khác", s == 404)
s, _, t = gate.txt("POST", f"/voucher/{pid}/confirm", {"csrf": gate.csrf()}); check("nhân viên không tự xác nhận thay khách bằng đường khách (409)", s == 409 and "Chỉ khách hàng" in t)
s, _, t = c1.txt("POST", f"/voucher/{pid}/confirm", {"csrf": "sai"}); check("xác nhận không có csrf đúng bị từ chối", s == 403)
s, _, t = c1.txt("POST", f"/voucher/{pid}/receive", {"csrf": c1.csrf(), "method": "cash"}); check("khách KHÔNG được tự ghi 'bãi đã nhận tiền'", s == 403)
s, h, _ = c1.txt("POST", f"/voucher/{pid}/confirm", {"csrf": c1.csrf()}); check("khách xác nhận đã thanh toán", s == 303 and "m=conf" in h["Location"])
s, _, t = c1.txt("GET", f"/voucher/{pid}"); r1 = row(pid)
check("có chữ ký: ảnh chữ ký khách in vào phiếu, không đóng dấu", f"/voucher/{pid}/sig/cust" in t and 'class="stamp"' not in t and r1["cust_sig"] and r1["cust_mode"] == "self")
s, _, b = c1.req("GET", f"/voucher/{pid}/sig/cust"); check("ảnh chữ ký trên phiếu tải được", s == 200 and b.startswith(b"\x89PNG")); s, _, _ = c2.req("GET", f"/voucher/{pid}/sig/cust"); check("khách khác không tải được chữ ký trên phiếu", s == 404)
s, _, t = c1.txt("POST", f"/voucher/{pid}/confirm", {"csrf": c1.csrf()}); check("xác nhận lần 2 bị từ chối", s == 409)
r1 = row(pid); check("tiền đã chốt + trạng thái khách đã xác nhận trong CSDL", r1["fee_total"] == 140000 and r1["cust_confirmed_at"])
check("bãi đã nhận từ trước (BL-001) -> đã thanh toán đầy đủ", G.voucher_state(r1)[1] == "done" and "Đã thanh toán đầy đủ" in gate.txt("GET", f"/voucher/{pid}")[2] and "BL-001" in gate.txt("GET", f"/voucher/{pid}")[2])
s, _, t = gate.txt("POST", f"/voucher/{pid}/receive", {"csrf": gate.csrf(), "method": "cash"}); check("ghi nhận nhận tiền 2 lần bị từ chối", s == 409)
# phiếu mới có chữ ký của người lập phiếu (bảo vệ) + chữ ký khách; đổi chữ ký sau không làm đổi phiếu cũ
C5 = mk("MSCU712345"); p5 = new_pass(gate, C5, "50F-555.55", cust=cust1); close_pass(gate, p5, C5, "50F-555.55", days_ago=6)
r5 = row(p5); check("đóng phiếu: chụp chữ ký người lập phiếu (bảo vệ) vào phiếu", r5["staff_sig"] and (G.SIG_DIR / r5["staff_sig"]).exists() and r5["fee_total"] > 0)
s, _, t = gate.txt("GET", f"/voucher/{p5}"); check("phiếu có ảnh chữ ký người lập phiếu", f"/voucher/{p5}/sig/staff" in t and "Chờ thanh toán" in t)
c1.txt("POST", f"/voucher/{p5}/confirm", {"csrf": c1.csrf()}); s, _, before = c1.req("GET", f"/voucher/{p5}/sig/cust")
c1.txt("POST", "/profile/signature/delete", {"csrf": c1.csrf()}); put(c1, sigimg("PNG", size=(600, 300))); s, _, after = c1.req("GET", f"/voucher/{p5}/sig/cust")
check("đổi/xoá chữ ký sau đó KHÔNG làm đổi chữ ký trên phiếu đã xác nhận", s == 200 and before == after and len(before) > 100)
c1.txt("POST", "/profile/signature/delete", {"csrf": c1.csrf()}); s, _, _ = c1.req("GET", "/signature/me"); check("xoá chữ ký -> không còn chữ ký hiện tại", s == 404)
# khách không có chữ ký -> đóng dấu đỏ
C6 = mk("CMAU654321"); p6 = new_pass(gate, C6, "60B-666.66", cust=cust1); close_pass(gate, p6, C6, "60B-666.66", days_ago=5)
s, _, t = c1.txt("GET", f"/voucher/{p6}"); check("khách chưa có chữ ký: cảnh báo sẽ đóng dấu đỏ", "đóng dấu đỏ ĐÃ XÁC NHẬN" in t)
c1.txt("POST", f"/voucher/{p6}/confirm", {"csrf": c1.csrf()}); s, _, t = c1.txt("GET", f"/voucher/{p6}")
check("khách không có chữ ký: chữ ĐÃ XÁC NHẬN đóng dấu đỏ ở chỗ ký tên", 'class="stamp">ĐÃ XÁC NHẬN</div>' in t and f"/voucher/{p6}/sig/cust" not in t and ".stamp{" in t and "#c0392b" in t)
# khách không có tài khoản: nhân viên ghi nhận tại quầy
C7 = mk("HLCU123456"); p7 = new_pass(gate, C7, "70C-777.77", cust=cust1); close_pass(gate, p7, C7, "70C-777.77", days_ago=5)
xd = D.connect(); xd.execute("UPDATE gate_passes SET customer_id=NULL WHERE id=?", (p7,)); xd.commit(); xd.close()   # nợ cũ của khách không có tài khoản
s, _, t = gate.txt("GET", f"/voucher/{p7}"); check("nhân viên thấy nút 'Khách xác nhận tại quầy' + 'Bãi đã nhận tiền'", "Khách xác nhận tại quầy" in t and "Bãi đã nhận tiền" in t)
s, h, _ = gate.txt("POST", f"/voucher/{p7}/counter", {"csrf": gate.csrf()}); s, _, t = gate.txt("GET", f"/voucher/{p7}"); r7 = row(p7)
check("xác nhận tại quầy: đóng dấu đỏ + ghi rõ ghi nhận tại quầy bởi nhân viên", 'class="stamp">ĐÃ XÁC NHẬN</div>' in t and "ghi nhận tại quầy bởi" in t and r7["cust_mode"] == "counter" and r7["cust_sig"] == "")
s, _, t = c1.txt("POST", f"/voucher/{p7}/counter", {"csrf": c1.csrf()}); check("khách KHÔNG dùng được đường 'tại quầy'", s in (403, 404))
gate.txt("POST", f"/voucher/{p7}/receive", {"csrf": gate.csrf(), "method": "transfer", "ref": "CK778899"}); s, _, t = gate.txt("GET", f"/voucher/{p7}"); check("chuyển khoản + mã tham chiếu hiện trên phiếu, đủ 2 bên -> hoàn tất", "Chuyển khoản" in t and "CK778899" in t and "Đã thanh toán đầy đủ" in t)
# phiếu miễn phí
r2 = row(pid2); s, _, t = gate.txt("GET", f"/voucher/{pid2}"); check("phiếu ở bãi ≤3 ngày: miễn phí, tự ghi đã thu", r2["fee_total"] == 0 and r2["fee_paid"] == 1 and r2["pay_method"] == "free" and "Miễn phí lưu bãi" in t and "không cần xác nhận" in t and "người nhận" not in t)
s, _, t = gate.txt("POST", f"/voucher/{pid2}/receive", {"csrf": gate.csrf(), "method": "cash"}); check("phiếu miễn phí không cần thu tiền (409)", s == 409)
# danh sách phiếu thanh toán
s, _, t = gate.txt("GET", "/vouchers"); check("danh sách phiếu thanh toán cho nhân viên, có tổng còn phải thu", s == 200 and G.voucher_no(row(p5)) in t and G.voucher_no(row(p6)) in t and "còn phải thu" in t)
s, _, t = gate.txt("GET", "/vouchers?st=done"); check("lọc 'đã thanh toán đầy đủ'", G.voucher_no(row(pid)) in t and G.voucher_no(row(p6)) not in t)
s, _, t = gate.txt("GET", "/vouchers?st=cust"); check("lọc 'khách đã xác nhận, chờ bãi'", G.voucher_no(row(p6)) in t and G.voucher_no(row(p5)) in t and G.voucher_no(row(pid)) not in t)
s, _, t = c1.txt("GET", "/vouchers"); check("khách chỉ thấy phiếu thanh toán của mình", G.voucher_no(row(pid)) in t and G.voucher_no(row(p7)) not in t)
s, _, t = c2.txt("GET", "/vouchers"); check("khách khác: danh sách rỗng", "Chưa có phiếu thanh toán" in t)
s, _, t = gate.txt("GET", "/passes?paid=unpaid"); check("lọc phiếu đã ra nhưng chưa thu", G.voucher_no(row(p5)).replace("PT-", "PASS-") in t and G.voucher_no(row(pid)).replace("PT-", "PASS-") not in t)
s, _, t = c1.txt("GET", f"/pass/{pid}"); check("khách thấy link tới phiếu thanh toán ngay trên phiếu ra/vào", f"/voucher/{pid}" in t)


# ---- G. chống chèn mã độc (XSS) ở trang mới
EVIL = '<img src=x onerror=alert(1)>'
CX = mk("EVLU123456"); sx, hx, _ = gate.txt("POST", "/gate/in/manual", {"csrf": gate.csrf(), "container_no": CX, "size": "40", "truck_plate": "88A-888.88", "owner_name": EVIL, "note": EVIL, "act": "create_confirm"}); px = int(re.search(r"/pass/(\d+)", hx["Location"]).group(1))
close_pass(gate, px, CX, "88A-888.88", days_ago=5)
allp = "".join(gate.txt("GET", u)[2] for u in (f"/pass/{px}", f"/voucher/{px}", "/passes?q=EVLU", "/passes?view=group", "/vouchers", "/timeline", "/timeline?q=EVLU"))
check("tên/ghi chú chứa thẻ HTML được escape ở phiếu, phiếu thanh toán, danh sách, nhóm, dòng thời gian", EVIL not in allp and "&lt;img src=x onerror=alert(1)&gt;" in allp)
s, _, t = gate.txt("GET", "/passes?q=" + "%22%3E%3Cscript%3Ealert(1)%3C/script%3E&from=%22onfocus%3D"); check("tham số tìm kiếm độc hại không chạy được (form được escape)", "<script>alert(1)" not in t and s == 200)


# ---- H. đơn giá GIỜ cho phần dư (thay cho làm tròn ngày)
dbh = D.connect()
ex = lambda sec, size="40": G.fee_calc(dbh, size, 0, sec)
ex5 = ex(5 * 86400 + 7 * 3600 + 60)
check("5 ngày 7 giờ 1 phút (phiếu của bạn): 2 ngày × 70.000 + 8 giờ × 2.917 = 163.333", ex5["total"] == 163333 and ex5["days"] == 5 and ex5["rem_seconds"] == 7 * 3600 + 60, ex5["total"])
check("dòng tiền tách riêng: bậc ngày + dòng 'Phần dư' đơn vị giờ", [x["unit"] for x in ex5["lines"]] == ["ngày", "ngày", "giờ"] and "Phần dư 7 giờ 01 phút" in ex5["lines"][-1]["label"])
check("dư đúng 0 giây: không có dòng phần dư", all(x["unit"] == "ngày" for x in ex(5 * 86400)["lines"]) and ex(5 * 86400)["total"] == 140000)
check("phần dư rơi vào ngày miễn phí: 0 đ", ex(2 * 86400 + 5 * 3600)["total"] == 0)
dbh.execute("UPDATE tariff_tiers SET hour_rate=3000 WHERE size='40' AND day_from=4"); dbh.commit()
check("đơn giá giờ đặt tay 3.000: 8 giờ = 24.000, tổng 164.000", ex(5 * 86400 + 7 * 3600 + 60)["total"] == 164000)
dbh.execute("UPDATE tariff_tiers SET hour_rate=4000 WHERE size='40' AND day_from=4"); dbh.commit(); capd = ex(4 * 86400 + 20 * 3600)
check("phần dư không vượt đơn giá 1 ngày: 20 giờ × 4.000 = 80.000 bị chặn còn 70.000", capd["total"] == 140000 and "tối đa bằng 1 ngày" in capd["lines"][-1]["label"])
dbh.execute("UPDATE tariff_tiers SET hour_rate=NULL WHERE size='40'")
D.set_setting(dbh, "hour_round", "down"); check("làm tròn 'chỉ giờ trọn': 7g01p = 7 giờ = 20.417", ex(5 * 86400 + 7 * 3600 + 60)["total"] == 160417)
D.set_setting(dbh, "hour_round", "exact"); check("làm tròn 'theo phút': 7,02 giờ ≈ 20.465", ex(5 * 86400 + 7 * 3600 + 60)["total"] == 160465)
D.set_setting(dbh, "hour_round", "up"); dbh.close()
# phiếu thật: ra sau 5 ngày 7 giờ -> phiếu thanh toán có dòng phần dư
CH = mk("TCLU183552"); pH = new_pass(gate, CH, "51C-777.00", cust=cust1)
xh = D.connect(); xh.execute("UPDATE gate_passes SET in_at=? WHERE id=?", (time.time() - 5 * 86400 - 7 * 3600 - 60, pH)); xh.commit(); xh.close()
gate.txt("POST", f"/pass/{pH}/out/confirm", {"csrf": gate.csrf(), "container_read": CH, "plate_read": "51C-777.00", "m": "qr"})
fh = json.loads(row(pH)["fee_detail"]); s, _, t = gate.txt("GET", f"/voucher/{pH}")
check("phiếu thanh toán hiện dòng 'Phần dư' tính theo giờ + ghi chú ngày trọn", s == 200 and "Phần dư 7 giờ 0" in t and "8 giờ" in t and "5 ngày trọn + phần dư" in t and "/giờ" in t and abs(row(pH)["fee_total"] - 163333) <= 5, row(pH)["fee_total"])
s, _, t = gate.txt("GET", f"/pass/{pH}"); check("trang phiếu ra/vào cũng hiện dòng tiền theo giờ", "Phần dư" in t and "Số lượng" in t)
# phiếu cũ (định dạng trước khi có đơn giá giờ) vẫn hiển thị được
old_fee = {"days": 6, "elapsed": 1, "lines": [{"label": "Ngày 4–6", "days": 3, "rate": 70000, "amount": 210000}], "storage": 210000, "lift": 0, "total": 210000, "warn": ""}
xo = D.connect(); xo.execute("UPDATE gate_passes SET fee_detail=?, fee_total=210000 WHERE id=?", (json.dumps(old_fee), pH)); xo.commit(); xo.close()
s, _, t = gate.txt("GET", f"/voucher/{pH}"); check("phiếu lưu theo định dạng cũ (days/ngày) vẫn hiển thị đúng", s == 200 and "3 ngày" in t and "210.000 đ" in t and "6 ngày tính phí" in t)
# trang bảng giá
s, _, t = boss.txt("GET", "/admin/tariff"); check("trang bảng giá có cột 'Đơn giá giờ' + chọn cách làm tròn", "Đơn giá giờ (cho phần dư)" in t and 'name="hour_round"' in t and "tự động: ngày ÷ 24" in t)
s, _, t = boss.txt("POST", "/admin/tariff/settings", {"csrf": boss.csrf(), "yard_name": "B", "model_path": "x.pt", "imgsz": "960", "conf": "0.3", "hour_round": "weird", "lift_fee_20": "0", "lift_fee_40": "0", "lift_fee_45": "0"}); check("cách làm tròn lạ bị từ chối (400)", s == 400)
s, _, t = boss.txt("POST", "/admin/tariff/add", {"csrf": boss.csrf(), "size": "all", "day_from": "1", "day_to": "5", "rate": "10000", "hour_rate": "abc"}); check("đơn giá giờ không phải số bị từ chối (400)", s == 400)
xdel = D.connect(); xdel.execute("DELETE FROM tariff_tiers WHERE size='45'"); xdel.commit(); xdel.close()
s, _, t = boss.txt("POST", "/admin/tariff/add", {"csrf": boss.csrf(), "size": "45", "day_from": "1", "day_to": "5", "rate": "10.000", "hour_rate": "600"}); s, _, t = boss.txt("GET", "/admin/tariff"); check("thêm bậc có đơn giá giờ riêng 600đ/giờ (gõ giá kiểu 10.000)", "600 đ/giờ" in t and "10.000 đ/ngày" in t)
s, _, t = boss.txt("GET", "/admin/tariff?sz=20&days=1"); 
# CSDL cũ (bước 3, chưa có cột hour_rate) tự nâng cấp
import sqlite3
od = os.path.join(tmp, "old3.db"); c3 = sqlite3.connect(od); c3.executescript("CREATE TABLE tariff_tiers(id INTEGER PRIMARY KEY AUTOINCREMENT, size TEXT NOT NULL, day_from INTEGER NOT NULL, day_to INTEGER, rate INTEGER NOT NULL);INSERT INTO tariff_tiers(size,day_from,day_to,rate) VALUES('40',1,3,0),('40',4,NULL,48000);"); c3.close()
keep = os.environ["SMARTPORT_DB"]; os.environ["SMARTPORT_DB"] = od; D.init_db(); c3 = D.connect()
check("CSDL cũ chưa có hour_rate tự thêm cột và vẫn tính đúng (4 ngày 6 giờ: 48.000 + 6 giờ × 2.000)", G.fee_calc(c3, "40", 0, 4 * 86400 + 6 * 3600)["total"] == 48000 + 12000 and "hour_rate" in [r[1] for r in c3.execute("PRAGMA table_info(tariff_tiers)")]); c3.close(); os.environ["SMARTPORT_DB"] = keep


# ================================================================ GIAI ĐOẠN A1: vai trò, trả trước khi ra, công nợ gộp, gia hạn, cục đỏ
import sqlite3
# ---- I1. vai trò và điều khoản thanh toán của khách
s, _, t = boss.txt("GET", "/admin/users"); check("boss thấy cột liên hệ + loại thanh toán + số ngày công nợ cho khách", 'name="pay_terms"' in t and 'name="credit_days"' in t and "Công nợ (trả sau)" in t)
check("vai trò chỉ còn 3: Admin boss / Quản trị cổng / Khách hàng", "Quản trị cổng" in t and "Admin boss" in t and "Điều độ" not in t and "Bảo vệ cổng" not in t)
try: D.create_user(D.connect(), "x_disp", "X", "", "", "Matkhau123", role="dispatcher", status="active"); okd = False
except ValueError: okd = True
check("không tạo được vai trò 'điều độ' nữa", okd)
c2id = D.connect().execute("SELECT id FROM users WHERE username='cust2'").fetchone()[0]
upd = lambda **kw: boss.txt("POST", "/admin/users/update", {"csrf": boss.csrf(), "uid": c2id, "role": "customer", "status": "active", **kw})
s, _, _ = upd(pay_terms="credit", credit_days="0"); check("số ngày công nợ = 0 bị từ chối (400)", s == 400)
s, _, _ = upd(pay_terms="weird", credit_days="30"); check("loại thanh toán lạ bị từ chối (400)", s == 400)
s, _, _ = gate.txt("POST", "/admin/users/update", {"csrf": gate.csrf(), "uid": c2id, "role": "customer", "status": "active", "pay_terms": "credit", "credit_days": "30"}); check("quản trị cổng KHÔNG được cấp công nợ cho khách (403)", s == 403)
check("mặc định khách mới là trả trước", D.connect().execute("SELECT pay_terms FROM users WHERE username='cust2'").fetchone()[0] == "prepaid")
s, _, _ = upd(pay_terms="credit", credit_days="45"); r2u = D.connect().execute("SELECT pay_terms, credit_days FROM users WHERE id=?", (c2id,)).fetchone(); check("boss cấp công nợ 45 ngày cho khách", s == 303 and tuple(r2u) == ("credit", 45))
# CSDL cũ có vai trò 'dispatcher' và khách đang 'pending'
od2 = os.path.join(tmp, "old_roles.db"); c4 = sqlite3.connect(od2)
c4.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, full_name TEXT, email TEXT, company TEXT, pw_hash TEXT, role TEXT, status TEXT, fails INTEGER DEFAULT 0, locked_until REAL DEFAULT 0, created_at REAL, last_login REAL);"
                 "INSERT INTO users(username,role,status) VALUES('dd','dispatcher','active'),('kh','customer','pending'),('nv','gate','pending');"); c4.close()
keep = os.environ["SMARTPORT_DB"]; os.environ["SMARTPORT_DB"] = od2; D.init_db(); c4 = D.connect()
m = {r["username"]: (r["role"], r["status"], r["pay_terms"], r["credit_days"]) for r in c4.execute("SELECT * FROM users")}; c4.close(); os.environ["SMARTPORT_DB"] = keep
check("CSDL cũ: điều độ -> quản trị cổng, khách đang chờ duyệt -> vào được, nhân viên vẫn chờ, có cột trả trước/công nợ", m["dd"][0] == "gate" and m["kh"][:2] == ("customer", "active") and m["nv"][:2] == ("gate", "pending") and m["kh"][2:] == ("prepaid", 30), m)

# ---- I2. thanh toán trước khi ra (khách vãng lai / trả trước) và công nợ (khách công nợ)
def chk(cl, pid, cont, plate): return cl.txt("POST", f"/pass/{pid}/out/check", {"csrf": cl.csrf(), "container_read": cont, "plate_read": plate, "m": "qr"})
def conf(cl, pid, cont, plate, **kw): return cl.txt("POST", f"/pass/{pid}/out/confirm", {"csrf": cl.csrf(), "container_read": cont, "plate_read": plate, "m": "qr", **kw})
quote = lambda pid: G.exit_quote(D.connect(), row(pid))[0]["total"]
CW = mk("PREU123456"); pW = new_pass(gate, CW, "41A-410.41"); xw = D.connect(); xw.execute("UPDATE gate_passes SET in_at=? WHERE id=?", (time.time() - 5 * 86400, pW)); xw.commit(); xw.close()
s, _, t = chk(gate, pW, CW, "41A-410.41")
check("khách vãng lai: trang đối chiếu hiện tiền bãi + bắt buộc thanh toán trước + 2 ô xác nhận", "Phải thanh toán trước khi ra" in t and 'name="pay_received"' in t and 'name="pay_confirmed"' in t and 'name="fee_expected"' in t and "Tiền bãi tới giờ" in t)
s, _, t = conf(gate, pW, CW, "41A-410.41"); check("ra mà chưa chọn hình thức thanh toán -> bị chặn", s == 409 and "chọn hình thức" in t)
s, _, t = conf(gate, pW, CW, "41A-410.41", pay_method="cash", pay_received="1", fee_expected=str(quote(pW))); check("chỉ tích 1 trong 2 xác nhận -> bị chặn", s == 409 and "đủ 2 xác nhận" in t)
s, _, t = conf(gate, pW, CW, "41A-410.41", pay_method="cash", pay_received="1", pay_confirmed="1", fee_expected="1"); check("số tiền trên màn hình khác số tiền thật -> bị chặn", s == 409 and "Tiền bãi đã đổi" in t)
check("các lần bị chặn không làm phiếu ra bãi", row(pW)["status"] == "inside")
s, _, t = conf(gate, pW, CW, "41A-410.41", pay_method="transfer", pay_ref="CK-0001", pay_received="1", pay_confirmed="1", fee_expected=str(quote(pW)))
rW = row(pW); check("đủ 2 xác nhận + số tiền khớp -> ra bãi, đã thu, khách xác nhận tại quầy", s == 303 and rW["status"] == "closed" and rW["fee_paid"] == 1 and rW["cust_mode"] == "counter" and rW["pay_method"] == "transfer" and rW["pay_ref"] == "CK-0001" and rW["due_at"] is None and rW["fee_total"] > 0)
s, _, t = boss.txt("GET", f"/voucher/{pW}"); check("phiếu đã thanh toán trước: 'Đã thanh toán đầy đủ' + dấu đỏ + mã CK", "Đã thanh toán đầy đủ" in t and 'class="stamp">ĐÃ XÁC NHẬN</div>' in t and "CK-0001" in t and "Hạn thanh toán" not in t)
check("nhật ký phiếu ghi 'thanh toán trước tại cổng'", "thanh toán trước tại cổng" in D.connect().execute("SELECT note FROM gate_events WHERE pass_id=? AND direction='out'", (pW,)).fetchone()[0])
# khách trả trước có tài khoản cũng phải trả trước khi ra
c2id_ = c2id; upd(pay_terms="prepaid", credit_days="30")
CP = mk("PRPU123456"); pP = new_pass(gate, CP, "43C-430.43", cust=c2id); xp = D.connect(); xp.execute("UPDATE gate_passes SET in_at=? WHERE id=?", (time.time() - 5 * 86400, pP)); xp.commit(); xp.close()
s, _, t = conf(gate, pP, CP, "43C-430.43"); check("khách có tài khoản nhưng trả trước: vẫn phải thanh toán mới ra", s == 409 and row(pP)["status"] == "inside")
conf(gate, pP, CP, "43C-430.43", pay_method="cash", pay_received="1", pay_confirmed="1", fee_expected=str(quote(pP))); check("trả trước xong -> ra bãi", row(pP)["status"] == "closed" and row(pP)["fee_paid"] == 1)
CF = mk("FRUU123456"); pF = new_pass(gate, CF, "44D-440.44", cust=c2id); s, _, _ = conf(gate, pF, CF, "44D-440.44"); check("ở bãi trong số ngày miễn phí: ra không cần thanh toán", s == 303 and row(pF)["fee_total"] == 0 and row(pF)["fee_paid"] == 1)
# khách công nợ ra rồi thanh toán sau trong hạn
upd(pay_terms="credit", credit_days="45")
CK = mk("CRDU123456"); pK = new_pass(gate, CK, "45E-450.45", cust=c2id); xk = D.connect(); xk.execute("UPDATE gate_passes SET in_at=? WHERE id=?", (time.time() - 5 * 86400, pK)); xk.commit(); xk.close()
s, _, t = chk(gate, pK, CK, "45E-450.45"); check("khách công nợ: trang ra bãi ghi rõ được ra ngay, hạn thanh toán 45 ngày", "Khách công nợ: được ra bãi ngay" in t and "(45 ngày)" in t and 'name="pay_received"' not in t)
s, _, _ = conf(gate, pK, CK, "45E-450.45"); rK = row(pK); check("khách công nợ ra bãi KHÔNG cần trả tiền; hạn = ra + 45 ngày", s == 303 and rK["fee_paid"] == 0 and abs(rK["due_at"] - (rK["out_at"] + 45 * 86400)) < 5)
s, _, t = c2.txt("GET", f"/voucher/{pK}"); check("phiếu công nợ hiện hạn thanh toán + đồng hồ đếm ngược", "Hạn thanh toán" in t and "data-until=" in t and "Chờ thanh toán" in t)
upd(pay_terms="prepaid", credit_days="30")
# ngoại lệ: quản trị cổng cho ra dù lệch (có lý do) -> chủ thấy ở trang Ngoại lệ
CO = mk("OVRU123456"); pO = new_pass(gate, CO, "42B-420.42")
s, _, t = conf(gate, pO, CO, "42B-420.99"); check("quản trị cổng cho ra khi lệch mà không ghi lý do -> bị chặn", s == 409 and "lý do" in t)
s, _, _ = conf(gate, pO, CO, "42B-420.99", reason="Xe thay biển tạm, chủ xe đã xác nhận qua điện thoại"); check("quản trị cổng cho ra dù lệch khi có lý do", s == 303 and row(pO)["status"] == "closed")
s, _, t = boss.txt("GET", "/admin/exceptions"); check("Admin boss thấy ngoại lệ: phiếu, lý do, người thao tác", row(pO)["pass_no"] in t and "Xe thay biển tạm" in t and "GATE1" in t)
s, _, _ = gate.txt("GET", "/admin/exceptions"); check("quản trị cổng KHÔNG xem được trang ngoại lệ (403)", s == 403)

# ---- I3. trang Công nợ + thanh toán gộp
CD1, CD2, CD3, CD4, CD5, CD6 = (mk(p) for p in ("DBTU123451", "DBTU123452", "DBTU123453", "DBTU123454", "DBTU123455", "DBTU123456"))
dp = {}
for k, cont in enumerate((CD1, CD2, CD3, CD4, CD5, CD6), 1):
    dp[k] = new_pass(gate, cont, f"5{k}F-{k}00.0{k}", cust=cust1); close_pass(gate, dp[k], cont, f"5{k}F-{k}00.0{k}", days_ago=5 + k)
CWD = mk("WLKU123456"); pWD = new_pass(gate, CWD, "46G-460.46", cust=cust1); close_pass(gate, pWD, CWD, "46G-460.46", days_ago=6)
xq = D.connect(); xq.execute("UPDATE gate_passes SET customer_id=NULL WHERE id=?", (pWD,)); xq.commit(); xq.close()   # nợ của khách vãng lai
s, _, t = c1.txt("GET", "/debts"); check("khách xem công nợ của mình, có hạn + đồng hồ + tổng", s == 200 and all(G.voucher_no(row(dp[k])) in t for k in dp) and "Công nợ:" in t and "data-until=" in t and "Tôi xác nhận đã thanh toán" in t)
check("khách không thấy công nợ vãng lai của người khác", G.voucher_no(row(pWD)) not in t)
s, _, t = gate.txt("GET", "/debts"); check("quản trị cổng thấy công nợ mọi khách + nợ cũ khách vãng lai", G.voucher_no(row(pWD)) in t and G.voucher_no(row(dp[1])) in t and "Khách vãng lai" in t and "Bãi đã nhận tiền" in t)
s, _, t = gate.txt("GET", "/debts?c=walkin"); check("lọc khách vãng lai", G.voucher_no(row(pWD)) in t and G.voucher_no(row(dp[1])) not in t)
s, _, t = gate.txt("GET", f"/debts?c={cust1}"); check("lọc theo khách có tài khoản", G.voucher_no(row(dp[1])) in t and G.voucher_no(row(pWD)) not in t)
s, _, t = c2.txt("GET", "/debts"); check("khách chỉ thấy nợ của chính mình (cust2 có phiếu công nợ 45 ngày), không thấy nợ của cust1", G.voucher_no(row(pK)) in t and G.voucher_no(row(dp[1])) not in t)
D.create_user(D.connect(), "cust3", "CUST3", "", "", "Matkhau123", role="customer", status="active"); c3 = login("cust3"); s, _, t = c3.txt("GET", "/debts"); check("khách chưa có nợ: thông báo rỗng", "Không có phiếu nào cần thanh toán" in t)
s, _, t = c1.txt("POST", "/debts/confirm", {"ids": [dp[1], dp[2]]}); check("thanh toán gộp không có csrf bị từ chối", s == 403)
s, _, t = c1.txt("POST", "/debts/confirm", {"csrf": c1.csrf(), "ids": [dp[1], dp[2], pWD, "abc", "99999"]})
check("khách xác nhận gộp 2 phiếu của mình; phiếu người khác/rác bị bỏ và báo lỗi", s == 200 and "cho 2 phiếu" in t and row(dp[1])["cust_confirmed_at"] and row(dp[2])["cust_confirmed_at"] and row(dp[1])["cust_mode"] == "self", t[:200])
s, _, t = c1.txt("POST", "/debts/confirm", {"csrf": c1.csrf(), "ids": [pWD]}); check("khách không xác nhận được phiếu của khách vãng lai (409)", s == 409)
s, _, t = c1.txt("POST", "/debts/receive", {"csrf": c1.csrf(), "ids": [dp[1]], "method": "cash"}); check("khách KHÔNG được ghi 'bãi đã nhận tiền' (403)", s == 403)
s, _, t = gate.txt("POST", "/debts/confirm", {"csrf": gate.csrf(), "ids": [dp[3]]}); check("nhân viên không xác nhận thay khách bằng đường khách (409)", s == 409 and row(dp[3])["cust_confirmed_at"] is None)
check("sau khi khách xác nhận, phiếu vẫn nằm trong công nợ (chờ bãi nhận tiền)", G.voucher_no(row(dp[1])) in c1.txt("GET", "/debts")[2] and "chờ bãi nhận tiền" in c1.txt("GET", "/debts")[2])
s, _, t = gate.txt("POST", "/debts/receive", {"csrf": gate.csrf(), "ids": [dp[1], dp[2]], "method": "transfer", "ref": "UNC-77"}); check("bãi ghi nhận đã nhận tiền gộp 2 phiếu", s == 200 and row(dp[1])["fee_paid"] == 1 and row(dp[2])["fee_paid"] == 1 and row(dp[1])["pay_ref"] == "UNC-77")
s, _, t = c1.txt("GET", "/debts"); check("đủ 2 xác nhận -> phiếu biến khỏi công nợ", G.voucher_no(row(dp[1])) not in t and G.voucher_no(row(dp[2])) not in t and G.voucher_no(row(dp[3])) in t)
check("phiếu đủ 2 xác nhận ghi 'Đã thanh toán đầy đủ'", "Đã thanh toán đầy đủ" in c1.txt("GET", f"/voucher/{dp[1]}")[2])
s, _, _ = gate.txt("POST", "/debts/receive", {"csrf": gate.csrf(), "ids": [dp[1]], "method": "cash"}); check("nhận tiền lần 2 cho phiếu đã thu bị từ chối", s == 409)
s, _, t = gate.txt("POST", "/debts/counter", {"csrf": gate.csrf(), "ids": [dp[3]]}); check("nhân viên ghi nhận khách xác nhận tại quầy (gộp)", s == 200 and row(dp[3])["cust_mode"] == "counter" and row(dp[3])["cust_sig"] == "")
# gia hạn
d4before = G.due_of(row(dp[4]))
s, _, t = gate.txt("POST", "/debts/extend", {"csrf": gate.csrf(), "ids": [dp[4]], "days": "15", "reason": "khách đi công tác"}); check("quản trị cổng KHÔNG được gia hạn (403)", s == 403)
s, _, t = boss.txt("POST", "/debts/extend", {"csrf": boss.csrf(), "ids": [dp[4]], "days": "15", "reason": "xin"}); check("gia hạn thiếu lý do (dưới 5 ký tự) bị từ chối", s == 409)
s, _, t = boss.txt("POST", "/debts/extend", {"csrf": boss.csrf(), "ids": [dp[4]], "days": "999", "reason": "khách đi công tác dài ngày"}); check("gia hạn quá 365 ngày bị từ chối", s == 409)
s, _, t = boss.txt("POST", "/debts/extend", {"csrf": boss.csrf(), "ids": [dp[4], dp[1]], "days": "15", "reason": "khách đi công tác, đã hẹn thanh toán"}); r4 = row(dp[4])
check("Admin boss gia hạn +15 ngày, lưu lý do; phiếu đã đủ 2 xác nhận không bị đổi", s == 303 and abs(G.due_of(r4) - d4before - 15 * 86400) < 2 and "đi công tác" in r4["due_ext_reason"] and row(dp[1])["due_at"] == row(dp[1])["due_at"])
s, _, t = boss.txt("GET", f"/voucher/{dp[4]}"); check("phiếu hiện 'đã gia hạn' + boss có form gia hạn", "đã gia hạn" in t and 'action="/debts/extend"' in t)
s, _, t = gate.txt("GET", f"/voucher/{dp[4]}"); check("quản trị cổng không có form gia hạn", 'action="/debts/extend"' not in t)
s, _, t = boss.txt("POST", "/debts/extend", {"csrf": boss.csrf(), "ids": [dp[1]], "days": "5", "reason": "thử phiếu đã xong"}); check("gia hạn phiếu đã thanh toán đầy đủ bị từ chối", s == 409)

# ---- I4. cục đỏ cảnh báo + bong bóng (còn <= 15 ngày tới hạn, khách chưa xác nhận)
now_ = time.time(); xu = D.connect()
xu.execute("UPDATE gate_passes SET due_at=? WHERE id=?", (now_ + 10 * 86400, dp[4])); xu.execute("UPDATE gate_passes SET due_at=? WHERE id=?", (now_ + 25 * 86400, dp[5])); xu.execute("UPDATE gate_passes SET due_at=? WHERE id=?", (now_ - 2 * 86400, dp[6])); xu.commit(); xu.close()
cnt, soon = G.urgent(D.connect()); check("G.urgent đếm phiếu khách chưa xác nhận còn ≤15 ngày/quá hạn", cnt >= 2 and soon is not None and soon <= now_ - 2 * 86400 + 5)
s, _, t = gate.txt("GET", "/gate"); check("nhân viên thấy cục đỏ dưới đồng hồ + số phiếu + đếm ngược + bong bóng", 'class="redalert"' in t and "Cần xác nhận phiếu thanh toán" in t and "data-until=" in t and 'id="bubble"' in t and "setInterval(show,5000)" in t)
s, _, t = c1.txt("GET", "/passes"); check("khách hàng KHÔNG thấy cục đỏ của nhân viên", 'class="redalert"' not in t and 'id="bubble"' not in t)
s, _, t = gate.txt("GET", "/debts?urgent=1"); check("lọc 'sắp/đã quá hạn': có phiếu hạn 10 ngày + phiếu quá hạn, KHÔNG có phiếu hạn 25 ngày", G.voucher_no(row(dp[4])) in t and G.voucher_no(row(dp[6])) in t and G.voucher_no(row(dp[5])) not in t)
s, _, t = gate.txt("GET", "/debts"); check("phiếu quá hạn tô đỏ, phiếu sắp hạn tô cam", re.search(r'<tr class="od">.{0,400}' + re.escape(G.voucher_no(row(dp[6]))), t, re.S) and re.search(r'<tr class="warnrow">.{0,400}' + re.escape(G.voucher_no(row(dp[4]))), t, re.S))
Dbs = D.connect(); D.set_setting(Dbs, "bubble_seconds", "0"); s, _, t = gate.txt("GET", "/gate"); check("bubble_seconds=0: chỉ hiện 1 lần khi tải trang, không lặp", "setInterval(show" not in t and "setTimeout(show,1500)" in t)
D.set_setting(Dbs, "bubble_seconds", "5"); D.set_setting(Dbs, "warn_days", "3"); cnt3, _ = G.urgent(D.connect()); s, _, t = gate.txt("GET", "/debts?urgent=1")
check("đổi số ngày cảnh báo = 3: phiếu hạn 10 ngày không còn bị coi là sắp hạn", G.voucher_no(row(dp[4])) not in t and G.voucher_no(row(dp[6])) in t); D.set_setting(Dbs, "warn_days", "15"); Dbs.close()
c1.txt("POST", "/debts/confirm", {"csrf": c1.csrf(), "ids": [dp[4]]}); cnt_after, _ = G.urgent(D.connect()); check("khách xác nhận xong thì phiếu thôi tính vào cục đỏ", cnt_after == cnt - 1 or cnt_after < cnt, (cnt, cnt_after))
xz = D.connect(); xz.execute("UPDATE gate_passes SET cust_confirmed_at=? WHERE status='closed' AND cust_confirmed_at IS NULL", (time.time(),)); xz.commit(); xz.close()
s, _, t = gate.txt("GET", "/gate"); check("không còn phiếu nào cần xác nhận: cục đỏ + bong bóng biến mất", G.urgent(D.connect())[0] == 0 and 'class="redalert"' not in t and 'id="bubble"' not in t)

# ---------------- bảng giá
s, _, t = gate.txt("GET", "/admin/tariff"); check("bảo vệ KHÔNG vào được trang bảng giá", s == 403)
s, _, t = boss.txt("GET", "/admin/tariff?sz=40&days=12"); check("admin xem bảng giá + tính thử 12 ngày = 770.000", s == 200 and "770.000 đ" in t)
s, _, t = boss.txt("POST", "/admin/tariff/add", {"csrf": boss.csrf(), "size": "40", "day_from": "5", "day_to": "8", "rate": "1"}); check("thêm bậc trùng khoảng bị từ chối, nói rõ trùng bậc nào", s == 400 and "trùng với bậc đã có" in t)
for i in D.connect().execute("SELECT id FROM tariff_tiers WHERE size='40'").fetchall(): boss.txt("POST", "/admin/tariff/del", {"csrf": boss.csrf(), "id": i[0]})
for a, b_, c_ in ((1, 2, 0), (3, 6, 100000), (7, "", 200000)): boss.txt("POST", "/admin/tariff/add", {"csrf": boss.csrf(), "size": "40", "day_from": a, "day_to": b_, "rate": c_})
s, _, t = boss.txt("GET", "/admin/tariff?sz=40&days=10"); check("đổi bảng giá: 10 ngày = 4×100.000 + 4×200.000 = 1.200.000", "1.200.000 đ" in t, re.findall(r"[\d.]+ đ", t)[:3])
dbq = D.connect(); check("đổi bảng giá không làm thay đổi tiền phiếu đã chốt", dbq.execute("SELECT fee_total FROM gate_passes WHERE id=?", (pid,)).fetchone()[0] == 140000); dbq.close()
s, _, t = boss.txt("POST", "/admin/tariff/settings", {"csrf": boss.csrf(), "yard_name": "Bãi A", "model_path": "x.pt", "imgsz": "960", "conf": "0.3", "lift_fee_20": "0", "lift_fee_40": "100000", "lift_fee_45": "0"}); s, _, t = boss.txt("GET", "/admin/tariff?sz=40&days=3")
check("phí nâng hạ cố định được cộng vào (3 ngày: 100.000 bậc + 100.000 nâng hạ = 200.000)", "Phí nâng hạ: 100.000 đ" in t and "200.000 đ" in t)
s, _, _ = boss.txt("POST", "/admin/tariff/settings", {"csrf": boss.csrf(), "imgsz": "abc", "conf": "0.3", "lift_fee_20": "0", "lift_fee_40": "0", "lift_fee_45": "0"}); check("cài đặt sai kiểu -> 400", s == 400)

# ================================================================ J. Admin boss chỉ giám sát + bảng giá dễ dùng
bossu = D.connect().execute("SELECT * FROM users WHERE username='boss'").fetchone(); dj = D.connect()
pJ = new_pass(gate, mk("BOSU123456"), "47H-470.47"); pJp = new_pass(gate, mk("BOSU123457"), "47H-470.48", confirm=False)
CJC = mk("BOSU123460"); pJc = new_pass(gate, CJC, "47H-470.51", cust=cust1); close_pass(gate, pJc, CJC, "47H-470.51", days_ago=5)   # công nợ chưa thu, chưa xác nhận
for path in ("/gate", "/gate/in", "/gate/out", f"/pass/{pJ}/out"):
    s, _, _ = boss.txt("GET", path); check(f"Admin boss KHÔNG vào màn hình thao tác {path} (403)", s == 403)
bp = lambda path, **kw: boss.txt("POST", path, {"csrf": boss.csrf(), **kw})
check("Admin boss không tạo được phiếu vào bãi (403)", bp("/gate/in/manual", container_no=mk("BOSU123458"), size="40", truck_plate="47H-470.49", fee_party="chu_xe", act="create")[0] == 403)
check("Admin boss không xác nhận vào bãi (403)", bp(f"/pass/{pJp}/in/confirm")[0] == 403 and row(pJp)["status"] == "pending")
check("Admin boss không đối chiếu/cho xe ra (403)", bp(f"/pass/{pJ}/out/check", container_read="x", plate_read="y")[0] == 403 and bp(f"/pass/{pJ}/out/confirm", container_read=row(pJ)["container_no"], plate_read=row(pJ)["truck_plate"])[0] == 403 and row(pJ)["status"] == "inside")
check("Admin boss không huỷ phiếu (403)", bp(f"/pass/{pJp}/cancel", reason="thử huỷ")[0] == 403 and row(pJp)["status"] == "pending")
check("Admin boss không ghi nhận nhận tiền / xác nhận tại quầy / tải ảnh quét (403)", bp(f"/voucher/{pJc}/receive", method="cash")[0] == 403 and bp(f"/voucher/{pJc}/counter")[0] == 403
      and bp("/debts/receive", ids=[pJc], method="cash")[0] == 403 and bp("/debts/counter", ids=[pJc])[0] == 403 and row(pJc)["fee_paid"] == 0 and row(pJc)["cust_confirmed_at"] is None)
for path in ("/passes", f"/pass/{pJ}", "/timeline", "/vouchers", f"/voucher/{dp[5]}", "/debts", "/admin/exceptions", "/admin/users", "/admin/tariff"):
    s, _, _ = boss.txt("GET", path); check(f"Admin boss VẪN xem/quản lý được {path}", s == 200, s)
s, _, t = boss.txt("GET", "/"); check("menu Admin boss: có Dòng thời gian, Công nợ, Người dùng, Bảng giá, Ngoại lệ; KHÔNG có Cổng vào/ra và Chữ ký", 'href="/timeline"' in t and 'href="/debts"' in t and 'href="/admin/users"' in t and 'href="/admin/tariff"' in t and 'href="/admin/exceptions"' in t and 'href="/gate"' not in t and 'href="/profile/signature"' not in t)
check("Admin boss vẫn có đồng hồ bên phải, không có nút mở màn hình cổng", 'id="ck-time"' in t and "Mở màn hình cổng vào/ra" not in t)
s, _, t = gate.txt("GET", "/"); check("menu Quản trị cổng: có Cổng vào/ra + Chữ ký + nút mở màn hình cổng; KHÔNG có Người dùng/Bảng giá", 'href="/gate"' in t and 'href="/profile/signature"' in t and "Mở màn hình cổng vào/ra" in t and 'href="/admin/users"' not in t and 'href="/admin/tariff"' not in t)
s, _, t = boss.txt("GET", f"/pass/{pJp}"); check("phiếu chờ vào: Admin boss không có nút xác nhận/huỷ", "Xác nhận VÀO bãi" not in t and "Huỷ phiếu" not in t)
s, _, t = boss.txt("GET", f"/pass/{pJ}"); check("phiếu trong bãi: Admin boss không có nút cho ra", "Xác minh và cho RA bãi" not in t)
s, _, t = gate.txt("GET", f"/pass/{pJ}"); check("phiếu trong bãi: Quản trị cổng có nút cho ra", "Xác minh và cho RA bãi" in t)
s, _, t = boss.txt("GET", f"/pass/{dp[5]}"); check("phiếu đã ra: Admin boss có link xem phiếu thanh toán", f'/voucher/{dp[5]}' in t)
s, _, t = boss.txt("GET", f"/voucher/{pJc}"); check("phiếu thanh toán: Admin boss chỉ có Gia hạn, không có nhận tiền / tại quầy", 'action="/debts/extend"' in t and f'/voucher/{pJc}/receive' not in t and f'/voucher/{pJc}/counter' not in t)
s, _, t = gate.txt("GET", f"/voucher/{pJc}"); check("phiếu thanh toán: Quản trị cổng có nhận tiền / tại quầy, không có Gia hạn", f'/voucher/{pJc}/receive' in t and f'/voucher/{pJc}/counter' in t and 'action="/debts/extend"' not in t)
s, _, t = boss.txt("GET", "/debts"); check("công nợ: Admin boss chỉ thấy gia hạn, không có nút nhận tiền", "chỉ xem và gia hạn" in t and "/debts/receive" not in t and "/debts/extend" in t)
s, _, t = gate.txt("GET", "/debts"); check("công nợ: Quản trị cổng có nhận tiền, không có gia hạn", "/debts/receive" in t and "/debts/extend" not in t)
# kiểm tra ngay trong lớp logic (phòng khi ai gọi thẳng, không qua giao diện)
res = [G.create_pass(dj, bossu, {"container_no": mk("BOSU123459"), "size": "40", "truck_plate": "47H-470.50"})[1], G.confirm_in(dj, bossu, pJp), G.confirm_out(dj, bossu, pJ, row(pJ)["container_no"], row(pJ)["truck_plate"], "qr"),
       G.cancel_pass(dj, bossu, pJp, "thử"), G.receive_payment(dj, bossu, pJc, "cash"), G.cust_confirm(dj, bossu, pJc, counter=True)]
check("lớp logic từ chối Admin boss ở cả 6 thao tác (tạo/vào/ra/huỷ/nhận tiền/tại quầy)", all(r == [G.NOT_OPS] for r in res), res)

# ---- bảng giá: gõ kiểu Việt Nam, thêm cho cả 3 cỡ, cảnh báo khoảng trống đúng cỡ
tadd = lambda **kw: boss.txt("POST", "/admin/tariff/add", {"csrf": boss.csrf(), "size": "all3", "day_from": "1", "day_to": "3", "rate": "0", "hour_rate": "", **kw})
tcount = lambda: dj.execute("SELECT COUNT(*) FROM tariff_tiers").fetchone()[0]
s, _, t = boss.txt("POST", "/admin/tariff/reset", {"csrf": boss.csrf()}); check("khôi phục mặc định mà chưa tích xác nhận -> bị từ chối", s == 400 and "Tích ô xác nhận" in t)
s, _, _ = boss.txt("POST", "/admin/tariff/reset", {"csrf": boss.csrf(), "confirm": "1"}); dj.commit(); check("khôi phục bảng giá mặc định: 9 bậc (3 cỡ × 3)", s == 303 and tcount() == 9)
s, _, t = gate.txt("POST", "/admin/tariff/reset", {"csrf": gate.csrf(), "confirm": "1"}); check("quản trị cổng không khôi phục được bảng giá (403)", s == 403)
s, _, t = boss.txt("GET", "/admin/tariff"); check("trang bảng giá chia từng cỡ, không cảnh báo khi đã phủ kín", all(f"Cỡ {x} feet" in t for x in ("20", "40", "45")) and "chưa có giá cho" not in t)
# tái hiện đúng tình huống: chỉ thêm 1–2 cho cỡ 20 trong khi cỡ 40 không có bậc ngày 1–3
dj.execute("DELETE FROM tariff_tiers WHERE day_from=1"); dj.commit(); tadd(size="20", day_from="1", day_to="2", rate="10.000")
s, _, t = boss.txt("GET", "/admin/tariff"); check("cảnh báo từng cỡ: cỡ 20 chỉ thiếu ngày 3, cỡ 40 và 45 thiếu ngày 1–3", "Cỡ 20 feet <b>chưa có giá cho: ngày 3</b>" in t and "Cỡ 40 feet <b>chưa có giá cho: ngày 1–3</b>" in t and "Cỡ 45 feet <b>chưa có giá cho: ngày 1–3</b>" in t, re.findall(r"chưa có giá cho: [^<]+", t))
f40 = G.fee_calc(dj, "40", 0, 1 * 86400 + 11 * 3600); f20 = G.fee_calc(dj, "20", 0, 1 * 86400 + 11 * 3600)
check("phiếu cỡ 40: báo rõ 'cỡ 40 feet chưa có bậc cho ngày 1' + 'tính riêng từng cỡ' (bậc của cỡ 20 không áp dụng)", f40["storage"] == 0 and "cỡ 40 feet" in f40["warn"] and "ngày 1" in f40["warn"] and "riêng từng cỡ" in f40["warn"], f40["warn"])
check("cùng thời gian ở bãi, cỡ 20 đã có giá nên tính tiền được và không cảnh báo", f20["storage"] > 0 and f20["warn"] == "", (f20["storage"], f20["warn"]))
n0 = tcount(); s, _, t = tadd(day_from="1", day_to="3"); check("thêm 'Cả 3 cỡ' mà cỡ 20 trùng -> từ chối cả lô, không thêm dở dang", s == 400 and "Cỡ 20" in t and tcount() == n0, tcount())
dj.execute("DELETE FROM tariff_tiers WHERE size='20' AND day_from=1"); dj.commit(); s, _, _ = tadd(); dj.commit(); check("thêm 1 bậc cho cả 3 cỡ cùng lúc: đủ 9 bậc (3 cỡ × 3)", s == 303 and tcount() == 9, tcount())
check("sau đó cả 3 cỡ phủ kín, không còn khoảng trống", all(G.tariff_gaps(dj, z) == [] for z in ("20", "40", "45")))
for label, kw, text in (("giá kiểu 10.000", {"rate": "10.000"}, 10000), ("giá kiểu 10,000", {"rate": "10,000"}, 10000), ("giá 1.250.000", {"rate": "1.250.000"}, 1250000), ("giá có khoảng trắng", {"rate": " 70 000 "}, 70000)):
    dj.execute("DELETE FROM tariff_tiers WHERE size='45'"); dj.commit(); s, _, _ = tadd(size="45", day_from="20", day_to="25", **{k: v for k, v in kw.items()})
    r = dj.execute("SELECT rate FROM tariff_tiers WHERE size='45' AND day_from=20").fetchone(); dj.commit(); check(f"đọc được {label} -> {text}", s == 303 and r and r["rate"] == text, (s, r and r["rate"]))
for label, kw, msg in (("giá lẻ 10.5", {"rate": "10.5"}, "số tiền nguyên"), ("giá 10.00 (không phải nhóm 3 số)", {"rate": "10.00"}, "số tiền nguyên"), ("giá chữ", {"rate": "abc"}, "số tiền nguyên"), ("giá trống", {"rate": ""}, "số tiền nguyên"),
                       ("đơn giá giờ sai", {"hour_rate": "x1"}, "Đơn giá giờ"), ("từ ngày 0", {"day_from": "0"}, "Từ ngày thứ"), ("đến < từ", {"day_from": "9", "day_to": "5"}, "phải lớn hơn hoặc bằng"), ("cỡ lạ", {"size": "99"}, "Chọn cỡ")):
    s, _, t = tadd(size=kw.pop("size", "45"), **{**{"day_from": "40", "day_to": "45", "rate": "1000"}, **kw}); check(f"{label}: báo lỗi RÕ ({msg}), không trang 'yêu cầu không hợp lệ' chung chung", s == 400 and msg in t and "Yêu cầu không hợp lệ" not in t, t[:80])
s, _, t = tadd(size="45", day_from="40", day_to="45", rate="10.5"); check("khi lỗi, giữ lại những gì đã gõ trong form", 'value="10.5"' in t and 'value="40"' in t and 'value="45"' in t)
s, _, _ = boss.txt("POST", "/admin/tariff/add", {"size": "45", "day_from": "40", "rate": "1000"}); check("thêm bậc giá không có csrf bị từ chối", s == 403)
s, _, _ = gate.txt("POST", "/admin/tariff/add", {"csrf": gate.csrf(), "size": "45", "day_from": "40", "rate": "1000"}); check("quản trị cổng không thêm bậc giá (403)", s == 403)
sset = lambda **kw: boss.txt("POST", "/admin/tariff/settings", {"csrf": boss.csrf(), "yard_name": "Bãi A", "model_path": "x.pt", "imgsz": "960", "conf": "0.25", "hour_round": "up", "lift_fee_20": "0", "lift_fee_40": "0", "lift_fee_45": "0", **kw})
s, _, _ = sset(lift_fee_40="150.000", conf="0,3"); check("cài đặt: phí nâng hạ gõ 150.000 và ngưỡng 0,3 đều được", s == 303 and D.get_setting(dj, "lift_fee_40") == "150000" and D.get_setting(dj, "conf") == "0.3")
for label, kw, msg in (("phí nâng hạ chữ", {"lift_fee_20": "abc"}, "Phí nâng hạ 20 feet"), ("ngưỡng 2", {"conf": "2"}, "Ngưỡng tin cậy"), ("cỡ ảnh chữ", {"imgsz": "abc"}, "Cỡ ảnh")):
    s, _, t = sset(**kw); check(f"cài đặt sai ({label}): báo lỗi rõ", s == 400 and msg in t, t[:80])
sset(); boss.txt("POST", "/admin/tariff/reset", {"csrf": boss.csrf(), "confirm": "1"}); dj.commit()   # trả bảng giá về mặc định
check("kết thúc: bảng giá mặc định phủ kín ngày 1–10, từ ngày 11 trở đi đã có giá", tcount() == 9 and all(G.tariff_gaps(dj, z) == [] for z in ("20", "40", "45")))

# ---------------- nâng cấp CSDL cũ (bước 1) không mất dữ liệu
import sqlite3
old = os.path.join(tmp, "old.db"); c = sqlite3.connect(old); c.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT);INSERT INTO users VALUES(1,'giu_lai');"); c.close()
os.environ["SMARTPORT_DB"] = old; D.init_db(); c = sqlite3.connect(old); check("init_db nâng cấp CSDL cũ, giữ dữ liệu cũ", c.execute("SELECT username FROM users").fetchone()[0] == "giu_lai" and c.execute("SELECT COUNT(*) FROM tariff_tiers").fetchone()[0] == 9); c.close()
print(f"\nKẾT QUẢ: {ok} đạt, {bad} lỗi"); sys.exit(1 if bad else 0)
