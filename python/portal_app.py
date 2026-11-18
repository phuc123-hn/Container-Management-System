"""
Cổng SmartPort (bước 1): đăng ký, đăng nhập, phân quyền, quản lý người dùng, khung giao diện.
Giữ nguyên công cụ "Kiểm tra mô hình trên video" cũ (python/app_video_test.py), chỉ quản trị viên mở được từ đây.

Chạy:
  python python/portal_app.py --create-admin        # lần đầu: tạo tài khoản quản trị (hỏi mật khẩu, không hiện khi gõ)
  python python/portal_app.py                       # chạy cổng tại http://127.0.0.1:8800
  python python/portal_app.py --reset-password tên  # quên mật khẩu: đặt lại ngay trên máy chủ
Mặc định chỉ nghe ở 127.0.0.1. Muốn cho máy khác truy cập phải có HTTPS (xem ghi chú cuối README_PORTAL).
"""
import argparse, getpass, html, json, sys, threading, time, traceback, webbrowser, hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import secrets
import portal_db as D
import portal_gate as G
import portal_inbox
import re

PORT, COOKIE = 8800, "sp_session"
MSG = {"registered": "Đã đăng ký tài khoản nhân viên. Chờ Admin boss duyệt rồi mới đăng nhập được.", "saved": "Đã lưu thay đổi.", "bye": "Bạn đã đăng xuất.", "registered_ok": "Đã đăng ký xong. Bạn đăng nhập được ngay."}
esc = lambda s: html.escape("" if s is None else str(s), quote=True)
fmt_ts = lambda t: time.strftime("%d/%m/%Y %H:%M", time.localtime(t)) if t else "—"

CSS = """:root{--steel:#2e4a5a;--wash:#e8edf0;--ink:#16232c;--mute:#5d6e7a;--blue:#2457a6;--line:#cdd6dc;--bad:#c0392b;--ok:#1e7a3c}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:15px/1.5 Bahnschrift,"Segoe UI",system-ui,sans-serif}
header{background:repeating-linear-gradient(90deg,#2e4a5a 0 7px,#37576a 7px 14px);color:#fff;padding:12px 28px;display:flex;align-items:center;gap:22px;flex-wrap:wrap}
header h1{margin:0;font-size:20px;font-weight:600}header nav{display:flex;gap:6px;flex:1;flex-wrap:wrap}
header nav a{color:#dbe6ec;text-decoration:none;padding:6px 12px;border-radius:4px}header nav a:hover,header nav a.on{background:rgba(255,255,255,.16);color:#fff}
header .me{font-size:14px;display:flex;align-items:center;gap:10px}header .me form{margin:0}
main{max-width:1100px;margin:22px auto;padding:0 20px}.box{background:#fff;border:1px solid var(--line);border-radius:6px;padding:20px;margin-bottom:18px}
.auth{max-width:420px;margin:50px auto}h2{margin:0 0 12px;font-size:19px}label{display:block;margin:12px 0 3px;font-weight:600;font-size:14px}
input,select{width:100%;padding:9px;border:1px solid var(--line);border-radius:4px;font:inherit;background:#fff}
button,.btn{display:inline-block;padding:10px 16px;border:0;border-radius:5px;background:var(--blue);color:#fff;font:600 15px inherit;cursor:pointer;text-decoration:none}
button.full{width:100%;margin-top:16px}button.ghost{background:transparent;border:1px solid rgba(255,255,255,.5);padding:5px 12px;font-size:13px}button.sm{padding:6px 12px;font-size:13px}
:focus-visible{outline:3px solid #f0b429;outline-offset:2px}.err{background:#f8d7d3;border:1px solid #e3a59d;padding:10px 12px;border-radius:5px;margin-bottom:10px}
.err ul{margin:0;padding-left:18px}.okm{background:#d8f0dd;border:1px solid #8ccaa0;padding:10px 12px;border-radius:5px;margin-bottom:12px}
.info{background:#eef3fb;border:1px solid #b9cdea;padding:10px 12px;border-radius:5px}small,.mute{color:var(--mute)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:18px}.card{background:#fff;border:1px solid var(--line);border-radius:6px;padding:14px 16px}
.card b{display:block;font:700 30px Consolas,monospace}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:middle}
th{font-size:13px;color:var(--mute)}td form{margin:0;display:flex;gap:6px;align-items:center}td select{padding:5px}.tag{display:inline-block;padding:1px 9px;border-radius:10px;font-size:12px;background:#e6eaed}
.tag.pending{background:#fff3cd}.tag.active,.tag.inside{background:#d8f0dd}.tag.disabled,.tag.rejected{background:#f8d7d3}.wrap{overflow-x:auto}"""

def page(title, body, h=None, nav="", refresh=0):
    u = h.user if h else None
    meta = '<meta http-equiv="refresh" content="%d">' % int(refresh) if refresh else ""
    links = ""
    if u:
        nb = portal_inbox.badge(h.db, u); inbox_badge = (' <span class="badge">%d</span>' % nb) if nb else ""
        items = [("/", "Tổng quan")] + ([("/gate", "Cổng vào/ra")] if u["role"] in G.OPS else []) + [("/passes", "Phiếu điện tử"), ("/timeline", "Dòng thời gian"), ("/vouchers", "Phiếu thanh toán"), ("/debts", "Công nợ"), ("/inbox", "Hộp thư" + inbox_badge)] + ([("/profile/signature", "Chữ ký")] if u["role"] != "admin" else []) + ([("/admin/users", "Người dùng"), ("/admin/tariff", "Bảng giá & mô hình"), ("/admin/exceptions", "Ngoại lệ cổng")] if u["role"] == "admin" else [])
        links = "".join(f'<a href="{p}" class="{"on" if p == nav else ""}">{t}</a>' for p, t in items)
        tool = (f'<form method="post" action="/admin/tool" style="margin:0"><input type="hidden" name="csrf" value="{esc(u["csrf"])}"><button class="ghost" title="Mở công cụ kiểm tra YOLO trên video">Công cụ mô hình</button></form>' if u["role"] == "admin" else "")
        me = (f'<div class="me">{tool}<span>{esc(u["full_name"])} · {esc(D.ROLES[u["role"]])}</span>'
              f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{esc(u["csrf"])}"><button class="ghost">Đăng xuất</button></form></div>')
    else: me = ""
    clock = ""; script = ""
    nonce = getattr(h, "nonce", "") if h else ""
    if u and nonce:
        bsec = 0; bub = ""
        if u["role"] in G.STAFF:
            n = lambda st: h.db.execute("SELECT COUNT(*) FROM gate_passes WHERE status=?", (st,)).fetchone()[0]
            cnt, soon = G.urgent(h.db); alert = ""
            if cnt:
                bsec = max(0, int(D.get_setting(h.db, "bubble_seconds", "5") or 0))
                alert = (f'<a class="redalert" href="/debts?urgent=1" title="Phiếu khách chưa xác nhận thanh toán, còn dưới số ngày cảnh báo hoặc đã quá hạn"><span class="dot">{cnt}</span>'
                         f'<span class="rt">Cần xác nhận phiếu thanh toán<br><b data-until="{int(soon)}">…</b></span></a>')
                bub = (f'<div class="bubble" id="bubble" role="status"><a href="/debts?urgent=1">Cần xác nhận phiếu thanh toán ({cnt} phiếu)</a>'
                       '<button type="button" id="bubble-off" title="Ẩn thông báo này 1 giờ">Ẩn 1 giờ</button></div>')
            clock = (f'<aside class="clock noprint" aria-label="Đồng hồ điều hành"><div><div class="cd" id="ck-date">…</div><div class="ct" id="ck-time">--:--:--</div></div>'
                     f'<div class="cs">Đang trong bãi: <b>{n("inside")}</b><br>Chờ vào bãi: <b>{n("pending")}</b></div>{alert}</aside>{bub}')
        js = ("(function(){var off=__MS__-Date.now(),tz=__TZ__*1000,W=['Chủ nhật','Thứ Hai','Thứ Ba','Thứ Tư','Thứ Năm','Thứ Sáu','Thứ Bảy'];function p(n){return n<10?'0'+n:''+n}"
              "function dur(a){var dd=Math.floor(a/86400),r=a%86400;return (dd?dd+' ngày ':'')+p(Math.floor(r/3600))+':'+p(Math.floor(r%3600/60))+':'+p(r%60)}"
              "function tick(){var now=Date.now()+off,d=new Date(now+tz),a=document.getElementById('ck-date'),t=document.getElementById('ck-time');"
              "if(a)a.textContent=W[d.getUTCDay()]+', '+p(d.getUTCDate())+'/'+p(d.getUTCMonth()+1)+'/'+d.getUTCFullYear();"
              "if(t)t.textContent=p(d.getUTCHours())+':'+p(d.getUTCMinutes())+':'+p(d.getUTCSeconds());"
              "document.querySelectorAll('[data-since]').forEach(function(e){e.textContent=dur(Math.max(0,Math.floor(now/1000-parseFloat(e.getAttribute('data-since')))))});"
              "document.querySelectorAll('[data-until]').forEach(function(e){var s=Math.floor(parseFloat(e.getAttribute('data-until'))-now/1000);e.textContent=(s<0?'QUÁ HẠN ':'còn ')+dur(Math.abs(s))})}"
              "tick();setInterval(tick,1000);"
              "document.querySelectorAll('[data-checkall]').forEach(function(c){c.addEventListener('change',function(){document.querySelectorAll('input[name=\"'+c.getAttribute('data-checkall')+'\"]').forEach(function(x){x.checked=c.checked})})});"
              "__BUBBLE__})();")
        bj = ""
        if bub:
            bj = ("var bb=document.getElementById('bubble'),bo=document.getElementById('bubble-off');"
                  "function hidden(){try{return parseInt(localStorage.getItem('sp_bub_off')||'0',10)>Date.now()}catch(e){return false}}"
                  "function show(){if(hidden())return;bb.className='bubble show';setTimeout(function(){bb.className='bubble'},4000)}"
                  "if(bo)bo.addEventListener('click',function(){try{localStorage.setItem('sp_bub_off',String(Date.now()+3600000))}catch(e){}bb.className='bubble'});"
                  "setTimeout(show,1500);" + (f"setInterval(show,{bsec * 1000});" if bsec > 0 else ""))
        script = f'<script nonce="{nonce}">' + js.replace("__MS__", str(int(time.time() * 1000))).replace("__TZ__", str(int(time.localtime().tm_gmtoff))).replace("__BUBBLE__", bj) + "</script>"
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'{meta}<title>{esc(title)} · SmartPort</title><style>{CSS}</style></head><body><header><h1>SmartPort</h1><nav>{links}</nav>{me}</header>{clock}<main>{body}</main>{script}</body></html>')

def errbox(errs): return ('<div class="err" role="alert"><ul>' + "".join(f"<li>{esc(e)}</li>" for e in errs) + "</ul></div>") if errs else ""

# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "SmartPort"
    def log_message(self, *a): pass
    user = None
    def ip(self): return self.client_address[0]
    def token(self):
        try: c = SimpleCookie(self.headers.get("Cookie", "")); return c[COOKIE].value if COOKIE in c else None
        except Exception: return None
    def send(self, code, body, extra=(), ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8"); self.send_response(code)
        for k, v in (("Content-Type", ctype), ("Content-Length", str(len(b))), ("X-Frame-Options", "DENY"), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin"), ("Cache-Control", "no-store"),
                     ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-" + getattr(self, "nonce", "x") + "'; img-src 'self' data:; form-action 'self' http://127.0.0.1:8765; base-uri 'none'; frame-ancestors 'none'"), *extra):
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def redirect(self, to, extra=()):
        self.send_response(303); self.send_header("Location", to); self.send_header("Content-Length", "0")
        for k, v in extra: self.send_header(k, v)
        self.end_headers()
    def form(self):
        try: n = int(self.headers.get("Content-Length") or 0)
        except ValueError: n = -1
        if n < 0 or n > 65536: raise ValueError("body")
        self._lists = parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True)      # _lists giữ được ô nhiều giá trị (nhiều ô tích)
        return {k: v[0] for k, v in self._lists.items()}
    def send_bytes(self, code, data, ctype):
        self.send_response(code)
        for k, v in (("Content-Type", ctype), ("Content-Length", str(len(data))), ("X-Content-Type-Options", "nosniff"), ("Cache-Control", "private, max-age=60")): self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)
    def multipart(self, cap=150 * 1024 * 1024):
        """Đọc form có file (multipart/form-data). Trả (các trường chữ, {tên: (tên file, bytes)})."""
        from email import policy
        from email.parser import BytesParser
        ctype = self.headers.get("Content-Type", "")
        try: n = int(self.headers.get("Content-Length") or 0)
        except ValueError: n = 0
        if not ctype.startswith("multipart/form-data") or n <= 0 or n > cap: raise ValueError("multipart")
        msg = BytesParser(policy=policy.HTTP).parsebytes(b"Content-Type: " + ctype.encode("latin-1", "replace") + b"\r\nMIME-Version: 1.0\r\n\r\n" + self.rfile.read(n))
        fields, files = {}, {}
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition"); fn = part.get_filename(); data = part.get_payload(decode=True) or b""
            if name is None: continue
            if fn is not None: files[name] = (fn, data)
            else: fields[name] = data.decode("utf-8", "replace")
        return fields, files
    def dispatch(self, method):
        path = urlparse(self.path).path; self.q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        self.db = D.connect(); self.nonce = secrets.token_urlsafe(12)
        try:
            self.user = D.get_session(self.db, self.token())
            fn = ROUTES.get((method, path)); args = ()
            if fn is None:
                for m, rx, f2 in ROUTES_RE:
                    mt = rx.fullmatch(path)
                    if m == method and mt: fn, args = f2, mt.groups(); break
            if fn is None: return self.send(404, page("Không tìm thấy", '<div class="box"><h2>Không có trang này</h2><a href="/">Về trang chủ</a></div>', self))
            fn(self, *args)
        except ValueError:
            self.send(400, page("Yêu cầu không hợp lệ", '<div class="box"><h2>Yêu cầu không hợp lệ</h2></div>', self))
        except Exception:
            traceback.print_exc(); self.send(500, page("Lỗi", '<div class="box"><h2>Có lỗi trong máy chủ</h2><p>Xem cửa sổ dòng lệnh để biết chi tiết.</p></div>', self))
        finally: self.db.close()
    def do_GET(self): self.dispatch("GET")
    def do_POST(self): self.dispatch("POST")

def need_login(h):
    if h.user is None: h.redirect("/login"); return False
    return True
def need_role(h, *roles):
    if not need_login(h): return False
    if h.user["role"] not in roles: h.send(403, page("Không có quyền", '<div class="box"><h2>Bạn không có quyền vào trang này</h2></div>', h)); return False
    return True
def csrf_ok(h, f):
    if h.user is None or not hmac.compare_digest(f.get("csrf", ""), h.user["csrf"]):
        h.send(403, page("Từ chối", '<div class="box"><h2>Phiên làm việc không hợp lệ</h2><p>Tải lại trang rồi thử lại.</p></div>', h)); return False
    return True

# ---------------------------------------------------------------- trang đăng nhập / đăng ký
def login_page(h, errs=(), username=""):
    ok = MSG.get(h.q.get("m", "")) and f'<div class="okm">{esc(MSG[h.q["m"]])}</div>' or ""
    h.send(200, page("Đăng nhập", f'<div class="box auth"><h2>Đăng nhập</h2>{ok}{errbox(errs)}<form method="post" action="/login">'
        f'<label for="u">Tên đăng nhập</label><input id="u" name="username" value="{esc(username)}" autocomplete="username" required autofocus>'
        f'<label for="p">Mật khẩu</label><input id="p" name="password" type="password" autocomplete="current-password" required>'
        f'<button class="full">Đăng nhập</button></form><p class="mute">Chưa có tài khoản? <a href="/register">Đăng ký</a></p></div>', h))

def r_login_get(h):
    if h.user: return h.redirect("/")
    login_page(h)

def r_login_post(h):
    f = h.form(); u, err = D.authenticate(h.db, f.get("username", "").strip(), f.get("password", ""))
    if u is None:
        D.audit(h.db, None, "login_fail", f.get("username", "")[:40], h.ip()); return login_page(h, [err], f.get("username", ""))
    tok = D.new_session(h.db, u["id"]); D.audit(h.db, u["id"], "login", "", h.ip())
    h.redirect("/", [("Set-Cookie", f"{COOKIE}={tok}; HttpOnly; SameSite=Lax; Path=/; Max-Age={D.SESSION_SECONDS}")])

def r_logout(h):
    f = h.form()
    if h.user and csrf_ok(h, f):
        D.drop_session(h.db, h.token()); D.audit(h.db, h.user["id"], "logout", "", h.ip())
        h.redirect("/login?m=bye", [("Set-Cookie", f"{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")])
    elif h.user is None: h.redirect("/login")

def register_page(h, errs=(), v=None):
    v = v or {}; fld = lambda k: esc(v.get(k, ""))
    h.send(200, page("Đăng ký", f'<div class="box auth"><h2>Đăng ký tài khoản</h2>{errbox(errs)}<form method="post" action="/register">'
        f'<label for="n">Họ tên</label><input id="n" name="full_name" value="{fld("full_name")}" required maxlength="100">'
        f'<label for="c">Công ty / đơn vị (nếu có)</label><input id="c" name="company" value="{fld("company")}" maxlength="100">'
        f'<label for="ph">Số điện thoại</label><input id="ph" name="phone" value="{fld("phone")}" required maxlength="20" placeholder="0909123456" autocomplete="tel">'
        f'<label for="e">Email (nếu có)</label><input id="e" name="email" type="email" value="{fld("email")}" maxlength="200">'
        f'<label for="u">Tên đăng nhập</label><input id="u" name="username" value="{fld("username")}" required autocomplete="username"><small>3-32 ký tự: chữ không dấu, số, . _ -</small>'
        f'<label for="p">Mật khẩu</label><input id="p" name="password" type="password" required autocomplete="new-password"><small>Ít nhất 8 ký tự, gồm cả chữ và số.</small>'
        f'<label for="p2">Nhập lại mật khẩu</label><input id="p2" name="password2" type="password" required autocomplete="new-password">'
        f'<label>Loại tài khoản</label><label style="font-weight:400"><input type="radio" name="account_type" value="customer"{" checked" if v.get("account_type", "customer") != "staff" else ""}> Khách hàng (chủ xe, chủ hàng): vào dùng ngay</label>'
        f'<label style="font-weight:400"><input type="radio" name="account_type" value="staff"{" checked" if v.get("account_type") == "staff" else ""}> Nhân viên bãi: chờ Admin boss duyệt</label>'
        f'<button class="full">Đăng ký</button></form><p class="mute">Đã có tài khoản? <a href="/login">Đăng nhập</a></p></div>', h))

def r_register_get(h):
    if h.user: return h.redirect("/")
    register_page(h)

def r_register_post(h):
    f = {k: v.strip() if k not in ("password", "password2") else v for k, v in h.form().items()}
    staff_acc = f.get("account_type") == "staff"
    errs = D.validate_new_user(f.get("username"), f.get("full_name"), f.get("email"), f.get("password"), f.get("password2"), f.get("phone"))
    if not f.get("phone"): errs.append("Nhập số điện thoại (để liên hệ và đối chiếu khi cần).")
    if not errs:
        try:
            role, status = ("gate", "pending") if staff_acc else ("customer", "active")      # khách vào ngay; chỉ nhân viên bãi cần chủ duyệt
            uid = D.create_user(h.db, f["username"], f["full_name"], f.get("email"), f.get("company"), f["password"], role=role, status=status, phone=f.get("phone"))
            D.audit(h.db, uid, "register", f"{f['username']} ({role})", h.ip()); return h.redirect("/login?m=" + ("registered" if staff_acc else "registered_ok"))
        except ValueError as e: errs = [str(e)]
    register_page(h, errs, f)

# ---------------------------------------------------------------- trang trong hệ thống
def scope(u):
    """Điều kiện lọc phiếu theo vai trò: khách hàng chỉ thấy phiếu của mình."""
    return ("", ()) if u["role"] != "customer" else (" AND customer_id=?", (u["id"],))

def r_home(h):
    if not need_login(h): return
    u = h.user; w, p = scope(u); db = h.db
    n = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    day0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    cards = [("Đang trong bãi", n("SELECT COUNT(*) FROM gate_passes WHERE status='inside'" + w, *p)),
             ("Chờ xác nhận", n("SELECT COUNT(*) FROM gate_passes WHERE status='pending'" + w, *p)),
             ("Phiếu tạo hôm nay", n("SELECT COUNT(*) FROM gate_passes WHERE created_at>=?" + w, day0, *p)),
             ("Đã ra hôm nay", n("SELECT COUNT(*) FROM gate_passes WHERE status='closed' AND out_at>=?" + w, day0, *p))]
    extra = ""
    if u["role"] == "admin":
        k = n("SELECT COUNT(*) FROM users WHERE status='pending'")
        if k: extra = f'<div class="info" style="margin-bottom:18px">Có <b>{k}</b> tài khoản đang chờ duyệt. <a href="/admin/users">Xem ngay</a></div>'
    todo = {"gate": "Vào mục Cổng vào/ra để cho xe vào, quét QR cho xe ra. Mục Công nợ để thu và xác nhận thanh toán.",
            "customer": "Bạn sẽ xem được phiếu và chứng từ của riêng mình tại mục Phiếu điện tử.",
            "admin": "Admin boss chỉ giám sát: xem phiếu, dòng thời gian, công nợ (và gia hạn). Duyệt nhân viên, cấp công nợ cho khách ở mục Người dùng. Xem ngoại lệ ở mục Ngoại lệ cổng. Việc cho xe ra vào và thu tiền do Quản trị cổng làm."}[u["role"]]
    if u["role"] in G.OPS: extra += '<div class="btnrow" style="margin:0 0 18px"><a class="btn" href="/gate">Mở màn hình cổng vào/ra</a></div>'
    h.send(200, page("Tổng quan", f'<h2>Xin chào, {esc(u["full_name"])}</h2>{extra}<div class="cards">' + "".join(f'<div class="card">{esc(t)}<b>{v}</b></div>' for t, v in cards)
        + f'</div><div class="box"><b>Trạng thái hệ thống:</b> đã có đăng nhập, phân quyền và cơ sở dữ liệu. <p class="mute" style="margin-bottom:0">{esc(todo)}</p></div>', h, "/"))

PASS_ST = {"pending": "Chờ xác nhận", "inside": "Trong bãi", "closed": "Đã ra", "rejected": "Từ chối"}
def r_passes(h):
    if not need_login(h): return
    w, p = scope(h.user)
    rows = h.db.execute("SELECT * FROM gate_passes WHERE 1=1" + w + " ORDER BY id DESC LIMIT 200", p).fetchall()
    tb = "".join(f'<tr><td><b>{esc(r["pass_no"])}</b></td><td>{esc(r["container_no"])}</td><td>{esc(r["truck_plate"])}</td><td><span class="tag {esc(r["status"])}">{esc(PASS_ST[r["status"]])}</span></td><td>{fmt_ts(r["in_at"])}</td><td>{fmt_ts(r["out_at"])}</td></tr>' for r in rows)
    h.send(200, page("Phiếu điện tử", '<div class="box"><h2>Phiếu điện tử</h2><div class="wrap"><table><tr><th>Số phiếu</th><th>Container</th><th>Biển số xe</th><th>Trạng thái</th><th>Giờ vào</th><th>Giờ ra</th></tr>'
        + (tb or '<tr><td colspan="6" class="mute">Chưa có phiếu nào. Phiếu sẽ được tạo ở cổng vào (bước 2).</td></tr>') + '</table></div></div>', h, "/passes"))

def r_users(h):
    if not need_role(h, "admin"): return
    rows = h.db.execute("SELECT * FROM users ORDER BY (status='pending') DESC, id").fetchall(); csrf = esc(h.user["csrf"])
    ok = MSG.get(h.q.get("m", "")) and f'<div class="okm">{esc(MSG[h.q["m"]])}</div>' or ""
    bad = h.q.get("e") == "self" and errbox(["Không thể tự hạ quyền hoặc tự khoá chính mình."]) or ""
    opt = lambda d, cur: "".join(f'<option value="{k}"{" selected" if k == cur else ""}>{esc(v)}</option>' for k, v in d.items())
    pend = sum(1 for r in rows if r["status"] == "pending")
    tb = "".join(f'<tr><td><b>{esc(r["username"])}</b><br><small>{esc(r["full_name"])}{" · " + esc(r["company"]) if r["company"] else ""}</small></td><td><small>{esc(r["phone"])}<br>{esc(r["email"])}</small></td>'
                 f'<td><form method="post" action="/admin/users/update"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="uid" value="{r["id"]}">'
                 f'<select name="role" aria-label="Vai trò">{opt(D.ROLES, r["role"])}</select><select name="status" aria-label="Trạng thái">{opt(D.STATUSES, r["status"])}</select>'
                 + (f'<select name="pay_terms" aria-label="Loại thanh toán">{opt(D.PAY_TERMS, r["pay_terms"])}</select><input name="credit_days" type="number" min="1" max="365" value="{r["credit_days"]}" style="width:78px" aria-label="Số ngày công nợ" title="Số ngày được nợ">' if r["role"] == "customer" else "")
                 + f'<button class="sm">Lưu</button></form></td><td><small>{fmt_ts(r["last_login"])}</small></td></tr>' for r in rows)
    h.send(200, page("Người dùng", f'<div class="box"><h2>Người dùng</h2>{ok}{bad}' + (f'<div class="banner warn">{pend} tài khoản đang chờ duyệt.</div>' if pend else "")
        + f'<div class="wrap"><table><tr><th>Tài khoản</th><th>Liên hệ</th><th>Vai trò / trạng thái / thanh toán</th><th>Đăng nhập gần nhất</th></tr>{tb}</table></div>'
        '<p class="mute"><b>Khách hàng</b> tự đăng ký và vào ngay, mặc định <b>trả trước tại cổng</b>. Chỉ khi bạn chọn <b>Công nợ</b> (và số ngày được nợ) thì khách mới được ra cổng rồi trả sau. <b>Nhân viên bãi</b> đăng ký xong ở trạng thái chờ duyệt: chọn vai trò Quản trị cổng và Đang hoạt động.</p></div>', h, "/admin/users"))

def r_users_update(h):
    f = h.form()
    if not need_role(h, "admin") or not csrf_ok(h, f): return
    uid = int(f.get("uid", ""))                      # sai định dạng -> ValueError -> trả 400
    role, st = f.get("role"), f.get("status")
    if role not in D.ROLES or st not in D.STATUSES: raise ValueError("giá trị")
    if uid == h.user["id"] and (role != "admin" or st != "active"): return h.redirect("/admin/users?e=self")
    t = h.db.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    if t is None: raise ValueError("uid")
    h.db.execute("UPDATE users SET role=?, status=? WHERE id=?", (role, st, uid))
    if role == "customer" and f.get("pay_terms"):
        terms = f.get("pay_terms"); days = int(f.get("credit_days", "30"))
        if terms not in D.PAY_TERMS or not 1 <= days <= 365: raise ValueError("thanh toán")
        h.db.execute("UPDATE users SET pay_terms=?, credit_days=? WHERE id=?", (terms, days, uid))
    if st != "active": h.db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))      # khoá/chờ duyệt thì đăng xuất ngay
    h.db.commit(); D.audit(h.db, h.user["id"], "user_update", f"{t['username']} -> {role}/{st}/{f.get('pay_terms', '')}", h.ip()); h.redirect("/admin/users?m=saved")

_TOOL = {"on": False}
def r_tool(h):
    f = h.form()
    if not need_role(h, "admin") or not csrf_ok(h, f): return
    if not _TOOL["on"]:
        try:
            import app_video_test as T
        except Exception as e:                    # thiếu file/thư viện: báo rõ trên trang thay vì lỗi 500
            return h.send(500, page("Lỗi công cụ", f'<div class="box"><h2>Không mở được công cụ mô hình</h2><div class="err">{esc(type(e).__name__)}: {esc(e)}</div>'
                '<p>Kiểm tra file <code>python\\app_video_test.py</code> có nằm cùng thư mục với <code>portal_app.py</code> không.</p></div>', h))
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", T.PORT), T.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        except OSError: pass                      # cổng đã có chương trình chạy (ví dụ bạn mở chay_giao_dien.bat) -> dùng luôn
        _TOOL["on"] = True
    D.audit(h.db, h.user["id"], "open_tool", "", h.ip()); h.redirect("http://127.0.0.1:8765/")

ROUTES = {("GET", "/login"): r_login_get, ("POST", "/login"): r_login_post, ("POST", "/logout"): r_logout, ("GET", "/register"): r_register_get, ("POST", "/register"): r_register_post,
          ("GET", "/"): r_home, ("GET", "/passes"): r_passes, ("GET", "/admin/users"): r_users, ("POST", "/admin/users/update"): r_users_update, ("POST", "/admin/tool"): r_tool}

ROUTES_RE = []
import portal_views
portal_views.install(globals())
portal_inbox.install(portal_views)

# ---------------------------------------------------------------- dòng lệnh
def cli_create_admin():
    D.init_db(); db = D.connect()
    name = input("Tên đăng nhập quản trị: ").strip(); full = input("Họ tên: ").strip()
    pw, pw2 = getpass.getpass("Mật khẩu (không hiện khi gõ): "), getpass.getpass("Nhập lại mật khẩu: ")
    errs = D.validate_new_user(name, full, "", pw, pw2)
    if errs: sys.exit("Không tạo được:\n  - " + "\n  - ".join(errs))
    try: D.create_user(db, name, full, "", "", pw, role="admin", status="active")
    except ValueError as e: sys.exit(str(e))
    print(f"Đã tạo quản trị viên '{name}'. Chạy: python python\\portal_app.py")

def cli_reset(name):
    D.init_db(); db = D.connect()
    if not db.execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone(): sys.exit(f"Không có tài khoản '{name}'.")
    pw, pw2 = getpass.getpass("Mật khẩu mới: "), getpass.getpass("Nhập lại: ")
    errs = D.validate_new_user(name, "x", "", pw, pw2)
    if errs: sys.exit("Không đổi được:\n  - " + "\n  - ".join(errs))
    db.execute("UPDATE users SET pw_hash=?, fails=0, locked_until=0 WHERE username=?", (D.hash_password(pw), name)); db.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE username=?)", (name,)); db.commit()
    print("Đã đổi mật khẩu và đăng xuất mọi phiên của tài khoản này.")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--create-admin", action="store_true"); ap.add_argument("--reset-password", metavar="TÊN")
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=PORT); ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if a.create_admin: return cli_create_admin()
    if a.reset_password: return cli_reset(a.reset_password)
    D.init_db()
    db = D.connect(); n_admin = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND status='active'").fetchone()[0]; db.close()
    if not n_admin: print("CHƯA CÓ quản trị viên. Tắt chương trình và chạy:  python python\\portal_app.py --create-admin\n")
    if a.host not in ("127.0.0.1", "localhost", "::1"): print("CẢNH BÁO: đang mở cho máy khác truy cập qua HTTP thường, mật khẩu đi trên mạng KHÔNG mã hoá. Chỉ dùng sau HTTPS (reverse proxy).\n")
    srv = ThreadingHTTPServer((a.host, a.port), H); url = f"http://{'127.0.0.1' if a.host == '0.0.0.0' else a.host}:{a.port}"
    print(f"Cổng SmartPort đang chạy tại {url}  (Ctrl+C để tắt)\nCơ sở dữ liệu: {D.db_path()}")
    if not a.no_browser: threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print("Đã tắt.")

if __name__ == "__main__":
    main()
