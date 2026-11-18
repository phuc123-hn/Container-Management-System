"""
Tự kiểm tra cổng SmartPort: chạy máy chủ thật trên cổng ngẫu nhiên với CSDL tạm, thử đăng ký/đăng nhập/phân quyền/khoá tài khoản/CSRF/XSS.
Chạy:  python python/test_portal.py        (không đụng tới data/smartport.db của bạn)
"""
import http.client, os, re, sys, tempfile, threading
from http.cookies import SimpleCookie
from urllib.parse import urlencode

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
tmp = tempfile.mkdtemp(); os.environ["SMARTPORT_DB"] = os.path.join(tmp, "test.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portal_db as D, portal_app as A
from http.server import ThreadingHTTPServer

D.init_db(); srv = ThreadingHTTPServer(("127.0.0.1", 0), A.H); PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

class Client:
    def __init__(self): self.ck = {}
    def req(self, method, path, form=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20); body = urlencode(form) if form is not None else None
        hd = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.ck.items())}
        if body is not None: hd["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body, hd); r = c.getresponse(); txt = r.read().decode("utf-8", "replace")
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                sc = SimpleCookie(v)
                for name, m in sc.items():
                    if m.value: self.ck[name] = m.value
                    else: self.ck.pop(name, None)
        return r.status, dict(r.getheaders()), txt
    def csrf(self, path="/"): return re.search(r'name="csrf" value="([^"]+)"', self.req("GET", path)[2]).group(1)

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print(f"  ĐẠT  {name}")
    else: bad += 1; print(f"  LỖI  {name} {extra}")

PW = "Matkhau123"
# --- mật khẩu
h = D.hash_password(PW); check("băm mật khẩu: đúng/sai", D.verify_password(PW, h) and not D.verify_password("sai", h) and PW not in h)
check("hai lần băm cùng mật khẩu cho kết quả khác (có salt)", D.hash_password(PW) != D.hash_password(PW))
# --- chưa đăng nhập
a = Client(); s, hd, _ = a.req("GET", "/"); check("chưa đăng nhập vào / bị chuyển về /login", s == 303 and hd["Location"] == "/login")
s, _, _ = a.req("GET", "/admin/users"); check("chưa đăng nhập vào /admin/users bị chuyển", s == 303)
s, hd, _ = a.req("GET", "/login"); check("trang đăng nhập có header bảo mật", s == 200 and hd.get("X-Frame-Options") == "DENY" and "Content-Security-Policy" in hd)
# --- đăng ký
reg = lambda c, **kw: c.req("POST", "/register", {"full_name": "An Nguyễn", "company": "", "email": "", "phone": "0909123456", "account_type": "customer", "username": "alice", "password": PW, "password2": PW, **kw})
s, _, t = reg(a, password="123", password2="123"); check("mật khẩu yếu bị từ chối", s == 200 and "ít nhất 8" in t)
s, _, t = reg(a, password2="khac"); check("hai mật khẩu không khớp bị từ chối", "không giống nhau" in t)
s, _, t = reg(a, username="a b"); check("tên đăng nhập sai định dạng bị từ chối", "Tên đăng nhập" in t)
s, hd, _ = reg(a); check("đăng ký hợp lệ -> chuyển /login", s == 303 and "registered_ok" in hd["Location"])
s, _, t = reg(a, username="ALICE"); check("trùng tên (không phân biệt hoa thường) bị từ chối", "đã có người" in t)
s, hd, _ = reg(a, username="nhanvien1", account_type="staff"); check("nhân viên bãi đăng ký -> chờ duyệt", s == 303 and hd["Location"].endswith("m=registered"))
s, _, t = a.req("POST", "/login", {"username": "nhanvien1", "password": PW}); check("tài khoản nhân viên chờ duyệt chưa đăng nhập được", s == 200 and "chờ Admin boss" in t)
s, _, t = reg(a, username="khongsdt", phone=""); check("đăng ký thiếu số điện thoại bị từ chối", "số điện thoại" in t.lower())
s, _, t = reg(a, username="sdtsai", phone="123"); check("số điện thoại sai định dạng bị từ chối", "Số điện thoại không đúng" in t)
s, hd, _ = reg(a, username="khach_moi"); s, hd2, _ = a.req("POST", "/login", {"username": "khach_moi", "password": PW}); check("khách hàng đăng ký xong đăng nhập NGAY, không cần duyệt", s == 303)
b = Client(); b.req("POST", "/login", {"username": "khach_moi", "password": PW}); s, _, tt = b.req("GET", "/admin/users"); check("khách hàng không vào được trang người dùng (403)", s == 403)
s, _, t = a.req("POST", "/login", {"username": "alice", "password": "sai"}); s2, _, t2 = a.req("POST", "/login", {"username": "khongco", "password": "sai"})
check("sai mật khẩu và tài khoản không tồn tại cho thông báo giống nhau", "Sai tên đăng nhập" in t and "Sai tên đăng nhập" in t2)
# --- XSS
s, _, _ = reg(a, username="mallory", full_name='<script>alert(1)</script>'); db = D.connect(); db.execute("UPDATE users SET status='active'"); db.commit(); db.close()
# --- admin
db = D.connect(); D.create_user(db, "boss", "Quản trị", "", "", PW, role="admin", status="active"); db.close()
ad = Client(); s, hd, _ = ad.req("POST", "/login", {"username": "boss", "password": PW}); check("admin đăng nhập -> cookie phiên", s == 303 and "sp_session" in ad.ck)
check("cookie có HttpOnly + SameSite", "HttpOnly" in hd["Set-Cookie"] and "SameSite=Lax" in hd["Set-Cookie"])
check("token phiên không lưu nguyên văn trong DB", all(ad.ck["sp_session"] not in r[0] for r in D.connect().execute("SELECT token_hash FROM sessions")))
s, _, t = ad.req("GET", "/"); check("admin xem được tổng quan", s == 200 and "Xin chào" in t and "Công cụ mô hình" in t)
s, _, t = ad.req("GET", "/admin/users"); check("admin xem danh sách người dùng", s == 200 and "alice" in t)
check("tên có thẻ <script> được escape", "<script>alert(1)</script>" not in t and "&lt;script&gt;" in t)
# --- phân quyền + CSRF
cs = ad.csrf("/admin/users"); uid = D.connect().execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
s, _, _ = ad.req("POST", "/admin/users/update", {"uid": uid, "role": "gate", "status": "active"}); check("admin đổi vai trò KHÔNG có csrf bị từ chối", s == 403)
s, _, _ = ad.req("POST", "/admin/users/update", {"csrf": cs, "uid": uid, "role": "gate", "status": "active"}); check("admin duyệt alice thành bảo vệ cổng", s == 303)
s, _, _ = ad.req("POST", "/admin/users/update", {"csrf": cs, "uid": uid, "role": "superuser", "status": "active"}); check("vai trò lạ bị từ chối", s == 400)
boss = D.connect().execute("SELECT id FROM users WHERE username='boss'").fetchone()[0]
s, hd, _ = ad.req("POST", "/admin/users/update", {"csrf": cs, "uid": boss, "role": "customer", "status": "active"}); check("admin không tự hạ quyền mình", "e=self" in hd.get("Location", ""))
al = Client(); s, _, _ = al.req("POST", "/login", {"username": "alice", "password": PW}); check("alice đăng nhập được sau khi duyệt", s == 303)
s, _, _ = al.req("GET", "/admin/users"); check("bảo vệ cổng KHÔNG vào được trang quản trị (403)", s == 403)
s, _, _ = al.req("POST", "/admin/tool", {"csrf": al.csrf()}); check("bảo vệ cổng KHÔNG mở được công cụ mô hình", s == 403)
s, _, _ = al.req("POST", "/admin/users/update", {"csrf": al.csrf(), "uid": uid, "role": "admin", "status": "active"}); check("không tự nâng quyền thành admin", s == 403)
s, _, t = al.req("GET", "/"); check("bảo vệ cổng thấy tổng quan, không có nút công cụ mô hình", s == 200 and "Công cụ mô hình" not in t)
# --- khoá/đăng xuất ngay
s, _, _ = ad.req("POST", "/admin/users/update", {"csrf": cs, "uid": uid, "role": "gate", "status": "disabled"})
s, hd, _ = al.req("GET", "/"); check("khoá tài khoản -> phiên đang mở mất hiệu lực ngay", s == 303)
# --- khoá do sai nhiều lần
bo = Client()
for i in range(D.MAX_FAILS): bo.req("POST", "/login", {"username": "boss", "password": "sai"})
s, _, t = bo.req("POST", "/login", {"username": "boss", "password": PW}); check(f"sai {D.MAX_FAILS} lần -> khoá tạm, đúng mật khẩu cũng chưa vào được", s == 200 and "tạm khoá" in t)
# --- đăng xuất
cs2 = ad.csrf(); s, _, _ = ad.req("POST", "/logout", {}); check("đăng xuất không có csrf bị từ chối", s == 403)
s, _, _ = ad.req("POST", "/logout", {"csrf": cs2}); s2, _, _ = ad.req("GET", "/"); check("đăng xuất xong vào / bị chuyển về đăng nhập", s == 303 and s2 == 303)
s, _, _ = a.req("POST", "/login", {"username": "x", "password": "y" * 70000}); check("body quá lớn bị từ chối (400)", s == 400)
s, _, _ = a.req("GET", "/khong-co"); check("đường dẫn lạ -> 404", s == 404)
n = D.connect().execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]; check("có nhật ký kiểm toán (audit_log)", n >= 5, f"n={n}")
print(f"\nKẾT QUẢ: {ok} đạt, {bad} lỗi"); sys.exit(1 if bad else 0)
