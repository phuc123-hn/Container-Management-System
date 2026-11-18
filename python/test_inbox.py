"""
Tự kiểm tra Hộp thư (A2): thư hệ thống (5 ngày), thư thanh toán (chưa xong thì ở lại, xong thì còn 30 ngày), thư nhắc nhở (không tự xoá),
và QUAN TRỌNG NHẤT: thư chưa thanh toán chỉ chuyển thành đã thanh toán khi phiếu đủ 2 xác nhận.
Chạy:  python python/test_inbox.py     (CSDL tạm)
"""
import http.client, os, re, sys, tempfile, threading, time
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
tmp = tempfile.mkdtemp(); os.environ["SMARTPORT_DB"] = os.path.join(tmp, "i.db"); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portal_db as D, portal_gate as G, portal_inbox as I, portal_app as A
G.EVID = Path(tmp) / "ev"; G.JOBS_DIR = Path(tmp) / "jobs"; G.SIG_DIR = Path(tmp) / "sig"
D.init_db(); srv = ThreadingHTTPServer(("127.0.0.1", 0), A.H); PORT = srv.server_address[1]; threading.Thread(target=srv.serve_forever, daemon=True).start()

class C:
    def __init__(s): s.ck = {}
    def req(s, m, p, f=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30); hd = {"Cookie": "; ".join(f"{k}={v}" for k, v in s.ck.items())}; body = None
        if f is not None: body = urlencode(f, doseq=True); hd["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(m, p, body, hd); r = c.getresponse(); b = r.read().decode("utf-8", "replace")
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                for n, mo in SimpleCookie(v).items():
                    if mo.value: s.ck[n] = mo.value
        return r.status, dict(r.getheaders()), b
    def get(s, p): st, hd, b = s.req("GET", p); return st, b
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print(f"  ĐẠT  {name}")
    else: bad += 1; print(f"  LỖI  {name} {extra}")

PW = "Matkhau123"; db0 = D.connect()
for u, r, kw in (("gate1", "gate", {}), ("boss", "admin", {}), ("cust1", "customer", {"pay_terms": "credit", "credit_days": 30}), ("cust2", "customer", {"pay_terms": "prepaid"}), ("cust3", "customer", {"pay_terms": "credit", "credit_days": 30})):
    D.create_user(db0, u, u.upper(), "", "Cty " + u, PW, role=r, status="active", **kw)
db0.close()
def login(u): c = C(); s, _, _ = c.req("POST", "/login", {"username": u, "password": PW}); assert s == 303; return c
gate, boss, c1, c2, c3 = login("gate1"), login("boss"), login("cust1"), login("cust2"), login("cust3")
U = lambda n: D.connect().execute("SELECT * FROM users WHERE username=?", (n,)).fetchone()
row = lambda pid: D.connect().execute("SELECT * FROM gate_passes WHERE id=?", (pid,)).fetchone()
mk = lambda p10: p10 + str(G.check_digit(p10)); SEQ = [0]
def mkpass(cust, plate, days_ago=5, close=True, size="40"):
    SEQ[0] += 1; db = D.connect(); cu = U(cust) if cust else None
    pid, errs = G.create_pass(db, U("gate1"), {"container_no": mk("INBU%06d" % SEQ[0]), "size": size, "truck_plate": plate, "customer_id": str(cu["id"]) if cu else "", "fee_party": "chu_xe"}, confirm_now=True); assert pid, errs
    db.execute("UPDATE gate_passes SET in_at=? WHERE id=?", (time.time() - days_ago * 86400, pid)); db.commit()
    if close:
        p = row(pid); fee, terms, cd, prepay = G.exit_quote(db, p)
        pay = {"method": "cash", "ref": "T", "received": True, "confirmed": True, "expected": fee["total"]} if prepay else None
        e = G.confirm_out(db, U("gate1"), pid, p["container_no"], p["truck_plate"], "qr", pay=pay); assert not e, e
    return pid
def setrow(pid, **kw):
    db = D.connect(); db.execute("UPDATE gate_passes SET " + ",".join(f"{k}=?" for k in kw) + " WHERE id=?", (*kw.values(), pid)); db.commit(); db.close()
pay_l = lambda name, now=None: I.payment_letters(D.connect(), U(name), now)
rem_l = lambda name, now=None: I.reminders(D.connect(), U(name), now)
unp = lambda name: [x for x in pay_l(name) if x["state"] == "unpaid"]

# ================= 1. THƯ HỆ THỐNG
print("-- thư hệ thống")
p1 = mkpass("cust1", "51A-100.01", days_ago=1, close=False); m = D.connect().execute("SELECT * FROM system_msgs WHERE user_id=?", (U("cust1")["id"],)).fetchall()
check("xe của khách vào bãi -> 1 thư hệ thống 'đã vào bãi' cho ĐÚNG khách đó", len(m) == 1 and m[0]["kind"] == "in" and "51A-100.01" in m[0]["body"] and row(p1)["pass_no"] in m[0]["body"])
check("khách khác không nhận thư của người ta", D.connect().execute("SELECT COUNT(*) FROM system_msgs WHERE user_id IN (?,?)", (U("cust2")["id"], U("cust3")["id"])).fetchone()[0] == 0)
n_before = D.connect().execute("SELECT COUNT(*) FROM system_msgs").fetchone()[0]; mkpass(None, "52A-200.02", close=False); check("khách vãng lai (không tài khoản) không có hộp thư: không tạo thư", D.connect().execute("SELECT COUNT(*) FROM system_msgs").fetchone()[0] == n_before)
e = G.confirm_out(D.connect(), U("gate1"), p1, row(p1)["container_no"], row(p1)["truck_plate"], "qr"); mo = D.connect().execute("SELECT * FROM system_msgs WHERE user_id=? AND kind='out'", (U("cust1")["id"],)).fetchone()
check("xe ra bãi (miễn phí) -> thư 'đã ra bãi' ghi rõ miễn phí", not e and mo and "Miễn phí lưu bãi" in mo["body"] and "đã ra bãi" in mo["body"])
p2 = mkpass("cust1", "51A-100.03", days_ago=5); mo2 = D.connect().execute("SELECT * FROM system_msgs WHERE pass_id=? AND kind='out'", (p2,)).fetchone()
check("xe công nợ ra bãi -> thư ghi số tiền + hạn thanh toán", mo2 and "Tiền bãi" in mo2["body"] and "hạn thanh toán" in mo2["body"] and G.money(row(p2)["fee_total"]) in mo2["body"])
p3 = mkpass("cust2", "51A-100.04", days_ago=5); mo3 = D.connect().execute("SELECT * FROM system_msgs WHERE pass_id=? AND kind='out'", (p3,)).fetchone(); check("khách trả trước ra bãi -> thư ghi 'đã thanh toán tại cổng'", mo3 and "đã thanh toán tại cổng" in mo3["body"])
s, t = c1.get("/inbox?tab=sys"); check("khách mở tab Hệ thống: thấy thư, nhóm 'Hôm nay', có chấm chưa đọc", s == 200 and "Hôm nay" in t and "51A-100.01" in t and 'class="new"' in t and "Xe đã vào bãi" in t and "Xe đã ra bãi" in t)
s, t = c1.get("/inbox?tab=sys"); check("mở lần 2: thư đã đọc, hết chấm chưa đọc", 'class="new"' not in t)
s, t = c2.get("/inbox?tab=sys"); check("khách khác không thấy thư hệ thống của cust1", "51A-100.01" not in t and "51A-100.04" in t)
# thời hạn 5 ngày
db = D.connect(); ids = [r["id"] for r in db.execute("SELECT id FROM system_msgs WHERE user_id=? ORDER BY id", (U("cust1")["id"],))]; now = time.time()
db.execute("UPDATE system_msgs SET created_at=? WHERE id=?", (now - 6 * 86400, ids[0])); db.execute("UPDATE system_msgs SET created_at=? WHERE id=?", (now - 4 * 86400, ids[1])); db.commit()
sl = I.system_letters(db, U("cust1")); check("thư 6 ngày tuổi không hiện; thư 4 ngày vẫn hiện", ids[0] not in [m["id"] for m in sl] and ids[1] in [m["id"] for m in sl])
I.purge(db); gone = db.execute("SELECT COUNT(*) FROM system_msgs WHERE id=?", (ids[0],)).fetchone()[0]; kept = db.execute("SELECT COUNT(*) FROM system_msgs WHERE id=?", (ids[1],)).fetchone()[0]; check("dọn dẹp xoá thật thư quá 5 ngày, giữ thư còn hạn của mọi khách", gone == 0 and kept == 1 and db.execute("SELECT COUNT(*) FROM system_msgs WHERE user_id=?", (U("cust2")["id"],)).fetchone()[0] >= 1)
D.set_setting(db, "sysmsg_days", "2"); check("đổi thời hạn giữ = 2 ngày: thư 4 ngày tuổi biến mất", ids[1] not in [m["id"] for m in I.system_letters(db, U("cust1"))]); D.set_setting(db, "sysmsg_days", "5")
s, t = gate.get("/inbox?tab=sys"); check("nhân viên không có tab Hệ thống (tự chuyển sang Nhắc nhở)", s == 200 and "tab=sys" not in t and "tab=pay" not in t and "Nhắc nhở xác nhận" in t)

# ================= 2. THƯ THANH TOÁN: chưa thanh toán chỉ thành đã thanh toán khi ĐỦ 2 XÁC NHẬN
print("-- thư thanh toán")
pp = mkpass("cust1", "53A-300.01", days_ago=5); base_unpaid = len(unp("cust1"))
for fp, cf, want_paid, miss_has in ((0, 0, False, ("Bạn chưa xác nhận", "Bãi chưa ghi nhận")), (1, 0, False, ("Bạn chưa xác nhận",)), (0, 1, False, ("Bãi chưa ghi nhận",)), (1, 1, True, ())):
    setrow(pp, fee_paid=fp, paid_at=time.time() if fp else None, cust_confirmed_at=time.time() if cf else None)
    L = [x for x in pay_l("cust1") if x["p"]["id"] == pp][0]; txt = " ".join(L["missing"])
    check(f"bảng chân trị (bãi nhận={fp}, khách xác nhận={cf}) -> {'ĐÃ thanh toán' if want_paid else 'CHƯA thanh toán'}", (L["state"] == "paid") == want_paid == G.is_done(row(pp)) and all(k in txt for k in miss_has) and (want_paid or len(L["missing"]) == len(miss_has)), L["state"])
setrow(pp, fee_paid=0, paid_at=None, cust_confirmed_at=None)
s, t = c1.get("/inbox?tab=pay"); check("thư chưa thanh toán: hiện đủ phiếu, số tiền, hạn, đồng hồ đếm ngược, ✘ ✘", s == 200 and G.voucher_no(row(pp)) in t and "Chưa thanh toán" in t and "data-until=" in t and "Khách xác nhận: ✘ · Bãi nhận tiền: ✘" in t)
b0 = I.badge(D.connect(), U("cust1")); e1 = G.receive_payment(D.connect(), U("gate1"), pp, "transfer", "CK1")
check("bãi nhận tiền xong nhưng khách CHƯA xác nhận -> VẪN là thư chưa thanh toán", not e1 and any(x["p"]["id"] == pp and x["state"] == "unpaid" for x in pay_l("cust1")) and "Khách xác nhận: ✘ · Bãi nhận tiền: ✔" in c1.get("/inbox?tab=pay")[1])
check("con số đỏ chưa giảm khi mới có 1 xác nhận", I.badge(D.connect(), U("cust1")) == b0)
e2 = G.cust_confirm(D.connect(), U("cust1"), pp)
L = [x for x in pay_l("cust1") if x["p"]["id"] == pp][0]; s, t = c1.get("/inbox?tab=pay")
check("khách xác nhận nốt -> TỰ chuyển thành 'Đã thanh toán' + ghi ngày tự xoá", not e2 and L["state"] == "paid" and "Đã thanh toán" in t and "Thư này tự xoá sau" in t)
check("thư đã thanh toán không còn tính vào con số đỏ", I.badge(D.connect(), U("cust1")) == b0 - 1)
# 30 ngày
setrow(pp, paid_at=time.time() - 29 * 86400, cust_confirmed_at=time.time() - 30 * 86400); check("đã thanh toán 29 ngày (xong lúc mới nhất) -> còn hiện", any(x["p"]["id"] == pp for x in pay_l("cust1")))
setrow(pp, paid_at=time.time() - 31 * 86400, cust_confirmed_at=time.time() - 32 * 86400); check("đã thanh toán 31 ngày -> thư biến mất", not any(x["p"]["id"] == pp for x in pay_l("cust1")))
D.set_setting(D.connect(), "paid_letter_days", "10"); setrow(pp, paid_at=time.time() - 9 * 86400, cust_confirmed_at=time.time() - 9 * 86400); a1 = any(x["p"]["id"] == pp for x in pay_l("cust1")); setrow(pp, paid_at=time.time() - 11 * 86400, cust_confirmed_at=time.time() - 11 * 86400)
check("đổi thời hạn giữ thư đã thanh toán = 10 ngày: 9 ngày còn, 11 ngày mất", a1 and not any(x["p"]["id"] == pp for x in pay_l("cust1"))); D.set_setting(D.connect(), "paid_letter_days", "30")
# chưa thanh toán thì không bao giờ tự mất
pq = mkpass("cust1", "53A-300.02", days_ago=5); setrow(pq, out_at=time.time() - 1000 * 86400, due_at=time.time() - 970 * 86400)
check("thư chưa thanh toán quá hạn 970 ngày VẪN nằm đó (không tự xoá)", any(x["p"]["id"] == pq and x["state"] == "unpaid" for x in pay_l("cust1")))
# phạm vi
pf = mkpass("cust1", "53A-300.03", days_ago=1); check("phiếu miễn phí (0 đ) không tạo thư thanh toán", not any(x["p"]["id"] == pf for x in pay_l("cust1")))
pw = mkpass(None, "53A-300.04", days_ago=5); check("khách vãng lai không có thư thanh toán; nhân viên cũng không có thư loại này", not any(x["p"]["id"] == pw for x in pay_l("cust1")) and pay_l("gate1") == [] and pay_l("boss") == [])
check("khách khác không thấy thư thanh toán của cust1", all(x["p"]["customer_id"] == U("cust2")["id"] for x in pay_l("cust2")) and not any(x["p"]["id"] == pq for x in pay_l("cust2")))
dl = G.debts(D.connect(), U("cust1")); check("thư chưa thanh toán khớp ĐÚNG với danh sách Công nợ (cùng một định nghĩa)", sorted(p["id"] for p in dl) == sorted(x["p"]["id"] for x in unp("cust1")))
check("thanh toán trả trước tại cổng (đủ 2 xác nhận lúc ra) -> thư 'Đã thanh toán' ngay", any(x["p"]["id"] == p3 and x["state"] == "paid" for x in pay_l("cust2")))

# ================= 3. THƯ NHẮC NHỞ
print("-- thư nhắc nhở")
now = time.time(); r10, r25, rlate = mkpass("cust3", "54A-400.01", days_ago=5), mkpass("cust3", "54A-400.02", days_ago=5), mkpass("cust3", "54A-400.03", days_ago=5)
for pid_, dd in ((r10, 10), (r25, 25), (rlate, -3)): setrow(pid_, due_at=now + dd * 86400)
ids3 = lambda name: [p["id"] for p in rem_l(name)]
check("khách nhắc: phiếu hạn 10 ngày và phiếu quá hạn 3 ngày CÓ, phiếu hạn 25 ngày KHÔNG", r10 in ids3("cust3") and rlate in ids3("cust3") and r25 not in ids3("cust3"))
check("sắp xếp: quá hạn lên đầu", ids3("cust3")[0] == rlate)
setrow(rlate, due_at=now - 1000 * 86400); check("nhắc nhở KHÔNG tự xoá theo thời gian (quá hạn 1000 ngày vẫn còn)", rlate in ids3("cust3"))
D.set_setting(D.connect(), "warn_days", "3"); check("đổi số ngày cảnh báo = 3: phiếu hạn 10 ngày không còn bị nhắc, phiếu quá hạn vẫn nhắc", r10 not in ids3("cust3") and rlate in ids3("cust3")); D.set_setting(D.connect(), "warn_days", "15")
s, t = c3.get("/inbox?tab=remind"); check("tab Nhắc nhở của khách: 'Đến hạn xác nhận và thanh toán', quá hạn tô riêng, đồng hồ", s == 200 and "Đến hạn xác nhận và thanh toán" in t and "letter remind overdue" in t and "data-until=" in t and G.voucher_no(row(r10)) in t and G.voucher_no(row(r25)) not in t and "không tự xoá theo thời gian" in t)
G.receive_payment(D.connect(), U("gate1"), rlate, "cash"); check("mới 1 xác nhận (bãi nhận tiền): thư nhắc nhở VẪN còn", rlate in ids3("cust3"))
G.cust_confirm(D.connect(), U("cust3"), rlate); check("đủ 2 xác nhận -> thư nhắc nhở TỰ biến mất (ràng buộc với trạng thái phiếu, không có cờ riêng)", rlate not in ids3("cust3"))
check("nhân viên: nhắc nhở chỉ gồm phiếu khách CHƯA XÁC NHẬN còn ≤15 ngày/quá hạn", all(p["cust_confirmed_at"] is None for p in rem_l("gate1")) and r10 in ids3("gate1") and r25 not in ids3("gate1"))
G.cust_confirm(D.connect(), U("cust3"), r10); check("khách xác nhận xong -> nhân viên thôi bị nhắc phiếu đó, nhưng khách vẫn bị nhắc vì bãi chưa nhận tiền", r10 not in ids3("gate1") and r10 in ids3("cust3"))
check("nhân viên và Admin boss thấy cùng danh sách nhắc nhở", ids3("gate1") == ids3("boss"))
check("số thư nhắc nhở của nhân viên khớp cục đỏ (G.urgent)", len(rem_l("gate1")) == G.urgent(D.connect())[0])
pwk = mkpass("cust1", "54A-400.04", days_ago=5); setrow(pwk, customer_id=None, due_at=now + 5 * 86400); s, t = gate.get("/inbox?tab=remind")
check("nhân viên thấy cả nợ khách vãng lai + tên khách ở thư nhắc", pwk in ids3("gate1") and "Khách vãng lai" in t and "Cần xác nhận phiếu thanh toán" in t and "khách CHƯA XÁC NHẬN" in t)
s, t = boss.get("/inbox"); check("Admin boss mở hộp thư: thấy tab nhắc nhở", s == 200 and "Nhắc nhở xác nhận" in t)

# ================= 4. TRANG, CON SỐ ĐỎ, QUYỀN
print("-- trang và quyền")
st, hd, _ = C().req("GET", "/inbox"); check("chưa đăng nhập vào /inbox bị chuyển về đăng nhập", st == 303 and hd["Location"] == "/login")
s, t = c1.get("/inbox?tab=viol"); check("tab Vi phạm: trống (bước A3 sẽ điền)", s == 200 and "Chưa có thư vi phạm nào" in t)
s, t = c1.get("/inbox?tab=<script>alert(1)</script>"); check("tham số tab độc hại: rơi về tab mặc định, không bị phản chiếu", s == 200 and "<script>alert(1)" not in t)
s, hd, t = c1.req("GET", "/inbox"); check("trang tự làm mới 30 giây (thư hệ thống gần thời gian thực)", 'http-equiv="refresh" content="30"' in t)
s, t = c1.get("/passes"); nb = I.badge(D.connect(), U("cust1")); check("menu khách có 'Hộp thư' kèm con số đỏ đúng", ('Hộp thư <span class="badge">%d</span>' % nb) in t if nb else "Hộp thư" in t, nb)
s, t = gate.get("/passes"); nbg = I.badge(D.connect(), U("gate1")); check("menu nhân viên có 'Hộp thư' kèm số phiếu cần nhắc", ('Hộp thư <span class="badge">%d</span>' % nbg) in t if nbg else "Hộp thư" in t, nbg)
s, t = C().get("/login"); check("trang đăng nhập không có hộp thư", "Hộp thư" not in t)
s, t = c2.get("/inbox?tab=remind"); check("khách khác không thấy nhắc nhở của cust3", G.voucher_no(row(r10)) not in t)
c4 = login("cust3")
db = D.connect(); db.execute("DELETE FROM system_msgs"); db.commit(); s, t = c4.get("/inbox?tab=sys"); check("không có thư hệ thống: thông báo rỗng đúng số ngày", "Chưa có thư hệ thống trong 5 ngày gần đây" in t)
# CSDL cũ chưa có bảng system_msgs
import sqlite3
od = os.path.join(tmp, "old.db"); cc = sqlite3.connect(od); cc.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, role TEXT, status TEXT);"); cc.close()
keep = os.environ["SMARTPORT_DB"]; os.environ["SMARTPORT_DB"] = od; D.init_db(); cc = D.connect(); has = cc.execute("SELECT name FROM sqlite_master WHERE name='system_msgs'").fetchone(); st_ = D.get_setting(cc, "sysmsg_days"), D.get_setting(cc, "paid_letter_days"); cc.close(); os.environ["SMARTPORT_DB"] = keep
check("CSDL cũ tự có bảng thư hệ thống + cài đặt 5 ngày / 30 ngày", has and st_ == ("5", "30"), st_)
print(f"\nKẾT QUẢ: {ok} đạt, {bad} lỗi"); sys.exit(1 if bad else 0)
