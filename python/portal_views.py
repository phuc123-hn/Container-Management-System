"""
Giao diện cổng vào/ra, phiếu điện tử, mã QR, tìm kiếm, bảng giá. Được portal_app.py nạp bằng install(globals()).
"""
import calendar, json, re, time
from urllib.parse import urlencode
from pathlib import Path
import portal_db as D
import portal_gate as G

try: import segno
except ImportError: segno = None

EXTRA_CSS = """input[type=hidden]{display:none!important}input[type=checkbox]{width:auto}input[type=file]{padding:6px}textarea{width:100%;padding:9px;border:1px solid var(--line);border-radius:4px;font:inherit}
.x{background:#f8d7d3;color:#b02a1c;font-weight:700;border-radius:2px;padding:0 1px}.bad td{background:#fdecea}.good td{background:#eef9f1}.mono{font-family:Consolas,monospace}
.big{font:700 26px Consolas,monospace;letter-spacing:1px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:820px){.grid2{grid-template-columns:1fr}}
.banner{padding:12px 16px;border-radius:6px;font-weight:600;margin-bottom:12px}.banner.ok{background:#d8f0dd;border:1px solid #8ccaa0}.banner.no{background:#f8d7d3;border:1px solid #e3a59d}.banner.warn{background:#fff3cd;border:1px solid #e6cf7a}
.tag.closed{background:#dbe4ff}.qr{background:#fff;padding:8px;border:1px solid var(--line);display:inline-block}.qr svg{display:block;max-width:230px;height:auto}
img.ev{max-width:100%;border:1px solid var(--line);border-radius:4px}.kv td:first-child{width:38%;color:var(--mute);font-size:14px}.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
button.green{background:#1e7a3c}button.red{background:#b3321f}button.gray{background:#5d6e7a}a.btn.big2,button.big2{padding:18px 26px;font-size:18px}.row2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.clock{position:fixed;right:14px;top:92px;width:178px;background:#16232c;color:#e8f1f6;border-radius:8px;padding:12px 14px;box-shadow:0 2px 8px rgba(0,0,0,.25);z-index:5;text-align:center}
.clock .cd{font-size:13px;color:#a9bdc9}.clock .ct{font:700 28px Consolas,monospace;margin:4px 0}.clock .cs{font-size:13px;color:#cfe0ea;border-top:1px solid #34505f;padding-top:6px;margin-top:6px}
@media(max-width:1399px){.clock{position:static;width:auto;margin:12px 20px 0;display:flex;gap:22px;justify-content:center;align-items:center}.clock .cs{border:0;padding:0;margin:0}}
.voucher{background:#fff;border:2px solid #16232c;padding:26px 30px;max-width:860px;margin:0 auto 18px}.voucher h1{text-align:center;font-size:22px;margin:0 0 2px}.voucher .sub{text-align:center;color:var(--mute);margin-bottom:14px}
.sigrow{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:22px;text-align:center}.sigbox{min-height:150px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:2px}.sigbox img{max-width:230px;max-height:95px}
.sigttl{font-weight:700;border-top:1px solid #16232c;padding-top:4px;margin-top:6px;width:80%}
.stamp{display:inline-block;color:#c0392b;border:4px double #c0392b;border-radius:8px;padding:6px 16px;font:800 24px "Segoe UI",Arial,sans-serif;letter-spacing:2px;transform:rotate(-9deg);opacity:.9;background:rgba(192,57,43,.05);-webkit-print-color-adjust:exact;print-color-adjust:exact;margin-bottom:6px}
.sigprev{background:#fff;border:1px dashed var(--line);padding:14px;text-align:center;min-height:90px}.sigprev img{max-width:100%;max-height:120px}.legend span{display:inline-block;margin-right:16px}.legend i{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:-1px;margin-right:5px}
summary{cursor:pointer;padding:8px 0}details{border-bottom:1px solid var(--line)}th a{color:inherit;text-decoration:none}th a:hover{text-decoration:underline}
.redalert{display:flex;align-items:center;gap:8px;background:#b3321f;color:#fff;border-radius:8px;padding:8px 10px;margin-top:8px;text-decoration:none;font-size:12px;text-align:left;animation:pulse 2s infinite}
.redalert .dot{background:#fff;color:#b3321f;font:800 16px Consolas,monospace;border-radius:50%;min-width:28px;height:28px;display:inline-flex;align-items:center;justify-content:center}.redalert b{font:700 12px Consolas,monospace}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(179,50,31,.55)}70%{box-shadow:0 0 0 10px rgba(179,50,31,0)}100%{box-shadow:0 0 0 0 rgba(179,50,31,0)}}
.bubble{position:fixed;right:14px;top:330px;max-width:230px;background:#fff;border:1px solid #e3a59d;border-left:5px solid #b3321f;border-radius:12px 12px 4px 12px;padding:10px 12px;box-shadow:0 4px 14px rgba(0,0,0,.25);z-index:20;opacity:0;transform:translateY(8px);pointer-events:none;transition:.25s}
.bubble.show{opacity:1;transform:none;pointer-events:auto}.bubble a{color:#b3321f;font-weight:700;text-decoration:none;display:block}.bubble button{margin-top:6px;padding:2px 8px;font-size:11px;background:#eee;color:#333}
@media(max-width:1399px){.bubble{top:auto;bottom:16px}}
.od td{background:#fdecea}.warnrow td{background:#fff8e1}
@media print{header,.noprint,.clock,.bubble{display:none!important}body{background:#fff}.box{border:0}main{margin:0;max-width:none}}"""

class _A: pass
A = _A()
FLASH = {"created": "Đã tạo phiếu. Bấm Xác nhận VÀO bãi khi xe thật sự đi qua cổng.", "in": "Đã xác nhận VÀO bãi.", "out": "Đã xác nhận RA bãi. Phiếu hoàn tất.", "paid": "Đã ghi nhận thu tiền.", "cancel": "Đã huỷ phiếu.", "saved": "Đã lưu.", "sig": "Đã lưu chữ ký.", "sigdel": "Đã xoá chữ ký.", "conf": "Đã ghi nhận xác nhận thanh toán.", "recv": "Đã ghi nhận bãi nhận tiền."}
FEE_STATUS = {0: "Chưa thu", 1: "Đã thu"}

def install(g):
    for k in ("page", "esc", "errbox", "need_role", "need_login", "csrf_ok", "fmt_ts", "ROUTES", "ROUTES_RE", "H"): setattr(A, k, g[k])
    A.g = g
    g["CSS"] = g["CSS"] + EXTRA_CSS
    R = A.ROUTES; RE = A.ROUTES_RE
    for (m, p), fn in {("GET", "/gate"): gate_home, ("GET", "/gate/in"): gate_in, ("POST", "/gate/in/manual"): in_manual, ("POST", "/gate/in/auto"): in_auto,
                       ("GET", "/gate/out"): gate_out, ("POST", "/gate/out/find"): out_find, ("GET", "/passes"): passes, ("GET", "/debts"): debts, ("POST", "/debts/confirm"): debts_confirm, ("POST", "/debts/receive"): debts_receive, ("POST", "/debts/counter"): debts_counter,
                       ("POST", "/debts/extend"): debts_extend, ("GET", "/admin/exceptions"): exceptions, ("GET", "/timeline"): timeline, ("GET", "/vouchers"): vouchers, ("GET", "/profile/signature"): sig_page, ("POST", "/profile/signature"): sig_upload,
                       ("POST", "/profile/signature/delete"): sig_delete, ("GET", "/signature/me"): sig_me, ("GET", "/admin/tariff"): tariff,
                       ("POST", "/admin/tariff/settings"): tariff_settings, ("POST", "/admin/tariff/add"): tariff_add, ("POST", "/admin/tariff/reset"): tariff_reset, ("POST", "/admin/tariff/del"): tariff_del}.items():
        R[(m, p)] = fn
    for m, pat, fn in (("GET", r"/pass/(\d+)", pass_detail), ("POST", r"/pass/(\d+)/in/confirm", pass_in), ("POST", r"/pass/(\d+)/cancel", pass_cancel), ("GET", r"/voucher/(\d+)", voucher), ("POST", r"/voucher/(\d+)/receive", voucher_receive), ("POST", r"/voucher/(\d+)/confirm", voucher_confirm), ("POST", r"/voucher/(\d+)/counter", voucher_counter), ("GET", r"/voucher/(\d+)/sig/(staff|cust)", voucher_sig),
                       ("GET", r"/pass/(\d+)/out", out_page), ("POST", r"/pass/(\d+)/out/check", out_check), ("POST", r"/pass/(\d+)/out/auto", out_auto), ("POST", r"/pass/(\d+)/out/confirm", out_confirm),
                       ("GET", r"/job/([0-9a-f]{12})", job_page), ("GET", r"/job/([0-9a-f]{12})/img", job_img), ("POST", r"/job/([0-9a-f]{12})/create_in", job_create_in),
                       ("GET", r"/evidence/(\d+)/(in|out|plate)", evidence)):
        RE.append((m, re.compile(pat), fn))

# ---------------------------------------------------------------- tiện ích
E = lambda s: A.esc(s)
def lq(x): return x.get("qty", x.get("days", 0))
def lu(x): return x.get("unit", "ngày")
def fee_note(fee):
    if fee.get("rem_seconds") is None: return f'{fee.get("days", "")} ngày tính phí'
    return f'{fee["days"]} ngày trọn' + (f' + phần dư {G.dur_text(fee["rem_seconds"])} tính theo giờ' if fee["rem_seconds"] else "")
def ops(h): return A.need_role(h, *G.OPS)            # thao tác cổng / thanh toán: chỉ Quản trị cổng
def staff(h): return A.need_role(h, *G.STAFF)          # chỉ xem: Quản trị cổng + Admin boss
def csrf_in(h): return f'<input type="hidden" name="csrf" value="{E(h.user["csrf"])}">'
def tag(st): return f'<span class="tag {E(st)}">{E(G.PASS_STATUS.get(st, st))}</span>'
def flash(h): return (f'<div class="okm">{E(FLASH[h.q["m"]])}</div>' if h.q.get("m") in FLASH else "")
def get_pass(h, pid):
    p = h.db.execute("SELECT * FROM gate_passes WHERE id=?", (int(pid),)).fetchone()
    if p is None or not G.can_view(h.user, p): h.send(404, A.page("Không tìm thấy", '<div class="box"><h2>Không có phiếu này</h2><a href="/passes">Về danh sách phiếu</a></div>', h)); return None
    return p
def qr_svg(text):
    if segno is None: return '<div class="info">Chưa cài thư viện tạo mã QR. Chạy: <code>python -m pip install segno</code> rồi khởi động lại cổng.</div>'
    return '<div class="qr">' + segno.make(text, error="m").svg_inline(scale=5, border=2, dark="#000", light="#fff") + "</div>"
def kv(rows): return '<table class="kv">' + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows if b not in (None, "")) + "</table>"
def customers(db): return db.execute("SELECT id, full_name, company, username FROM users WHERE role='customer' AND status='active' ORDER BY full_name").fetchall()
def opts(d, cur): return "".join(f'<option value="{E(k)}"{" selected" if str(k) == str(cur) else ""}>{E(v)}</option>' for k, v in d.items())
def pass_table(rows, empty="Chưa có phiếu nào.", head=None):
    def pay(r):
        if r["status"] != "closed": return "—"
        return E(G.voucher_state(r)[0])
    tb = "".join(f'<tr><td><a href="/pass/{r["id"]}"><b>{E(r["pass_no"])}</b></a></td><td class="mono">{E(r["container_no"])}</td><td>{E(r["truck_plate"])}</td><td>{tag(r["status"])}</td>'
                 f'<td>{E(A.fmt_ts(r["in_at"]))}</td><td>{E(A.fmt_ts(r["out_at"]))}</td><td>{G.money(r["fee_total"]) if r["status"] == "closed" else "—"}</td><td>{pay(r)}</td><td>{"Tự động" if r["mode"] == "auto" else "Thủ công"}</td></tr>' for r in rows)
    heads = head or ["Số phiếu", "Container", "Biển số xe", "Trạng thái", "Giờ vào", "Giờ ra", "Tiền bãi", "Thanh toán", "Cách tạo"]
    return ('<div class="wrap"><table><tr>' + "".join(f"<th>{x}</th>" for x in heads) + "</tr>" + (tb or f'<tr><td colspan="9" class="mute">{E(empty)}</td></tr>') + "</table></div>")

def read_uploads(h):
    f, files = h.multipart()
    if not A.csrf_ok(h, f): return None, None, None
    m = files.get("media", ("", b""))
    if not m[1] or Path(m[0]).suffix.lower() not in G.UPLOAD_EXT: return f, None, "Chọn ảnh hoặc video thùng container (jpg, png, mp4, avi, mov, mkv)."
    ex = {}
    for k, label in (("plate", "biển số"), ("paper", "giấy tờ")):
        fn, data = files.get(k, ("", b""))
        if data:
            if Path(fn).suffix.lower() not in G.IMG_EXT: return f, None, f"Ảnh {label} phải là ảnh (jpg, png, webp, bmp)."
            ex[k] = (fn, data)
    return f, {"media": m, "extras": ex}, ""

# ---------------------------------------------------------------- cổng
def gate_home(h):
    if not ops(h): return
    db = h.db; n = lambda sql, *a: db.execute(sql, a).fetchone()[0]; day0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    cards = [("Chờ xác nhận vào", n("SELECT COUNT(*) FROM gate_passes WHERE status='pending'")), ("Đang trong bãi", n("SELECT COUNT(*) FROM gate_passes WHERE status='inside'")),
             ("Đã ra hôm nay", n("SELECT COUNT(*) FROM gate_passes WHERE status='closed' AND out_at>=?", day0))]
    rows = db.execute("SELECT * FROM gate_passes ORDER BY id DESC LIMIT 12").fetchall()
    h.send(200, A.page("Cổng vào/ra", f'{flash(h)}<div class="cards">' + "".join(f'<div class="card">{E(t)}<b>{v}</b></div>' for t, v in cards) + '</div>'
        '<div class="box"><div class="btnrow" style="margin-top:0"><a class="btn big2 green" href="/gate/in">Cho xe VÀO bãi</a><a class="btn big2" href="/gate/out">Cho xe RA bãi (quét QR)</a></div>'
        f'<form method="post" action="/gate/out/find" style="margin-top:18px">{csrf_in(h)}<label for="sc">Quét mã QR của chủ xe (máy quét tự điền vào ô này) hoặc gõ số phiếu</label>'
        '<div class="row2"><input id="sc" name="scan" autocomplete="off" placeholder="SPASS|PASS-…  hoặc  PASS-20261029-0001" autofocus><div><button>Tìm phiếu để xác minh ra</button></div></div></form></div>'
        f'<div class="box"><h2>Phiếu gần đây</h2>{pass_table(rows)}</div>', h, "/gate"))

def manual_form(h, v=None, errs=(), show_accept=False, action="/gate/in/manual", hint=""):
    v = v or {}; f = lambda k: E(v.get(k, ""))
    cs = "".join(f'<option value="{c["id"]}"{" selected" if str(c["id"]) == str(v.get("customer_id", "")) else ""}>{E(c["full_name"])}{" · " + E(c["company"]) if c["company"] else ""} ({E(c["username"])})</option>' for c in customers(h.db))
    acc = ('<label style="font-weight:400"><input type="checkbox" name="accept_invalid" value="1"> Tôi đã nhìn thùng thật: mã đúng như trên, dù số kiểm tra không khớp</label>' if show_accept else "")
    return (f'<form method="post" action="{action}">{csrf_in(h)}{A.errbox(errs)}{hint}'
            f'<label for="c">Số container (11 ký tự)</label><input id="c" name="container_no" class="mono" maxlength="14" value="{f("container_no")}" placeholder="EITU1841398" required>'
            f'<div class="row2"><div><label for="s">Cỡ</label><select id="s" name="size">{opts({"20": "20 feet", "40": "40 feet", "45": "45 feet"}, v.get("size", "40"))}</select></div>'
            f'<div><label for="i">Mã loại (nếu có)</label><input id="i" name="iso_type" maxlength="4" value="{f("iso_type")}" placeholder="45G1"></div></div>'
            f'<label for="p">Biển số xe</label><input id="p" name="truck_plate" value="{f("truck_plate")}" placeholder="51C-123.45" required>'
            f'<div class="row2"><div><label for="on">Tên chủ xe / tài xế</label><input id="on" name="owner_name" value="{f("owner_name")}"></div><div><label for="op">Số điện thoại</label><input id="op" name="owner_phone" value="{f("owner_phone")}"></div></div>'
            f'<label for="cu">Gắn tài khoản khách hàng (để họ xem phiếu)</label><select id="cu" name="customer_id"><option value="">— không gắn —</option>{cs}</select>'
            f'<label for="fp">Bên trả phí bãi</label><select id="fp" name="fee_party">{opts(G.FEE_PARTIES, v.get("fee_party", "chu_xe"))}</select>'
            f'<label for="n">Ghi chú</label><input id="n" name="note" value="{f("note")}" maxlength="300">{acc}'
            '<div class="btnrow"><button name="act" value="create_confirm" class="green">Tạo phiếu và xác nhận VÀO bãi</button><button name="act" value="create" class="gray">Chỉ tạo phiếu (xác nhận sau)</button></div></form>')

def gate_in(h, v=None, errs=(), show_accept=False, code=200):
    if not ops(h): return
    h.send(code, A.page("Cho xe vào", '<h2>Cho xe VÀO bãi</h2><p class="mute">Dùng một trong hai cách. Cả hai đều ra cùng một phiếu điện tử.</p><div class="grid2">'
        f'<div class="box"><h2>1. Thủ công</h2>{manual_form(h, v, errs, show_accept)}</div>'
        f'<div class="box"><h2>2. Tự động (quét từ ảnh/video)</h2><p class="mute">Tải ảnh thùng container (bắt buộc), thêm ảnh biển số xe và ảnh giấy tờ nếu có. Hệ thống điền sẵn số container, biển số, tên tài xế, số điện thoại; bạn kiểm tra, bổ sung phần còn lại rồi xác nhận.</p>'
        f'<form method="post" action="/gate/in/auto" enctype="multipart/form-data">{csrf_in(h)}<label for="m">1. Ảnh hoặc video thùng container (bắt buộc)</label><input id="m" type="file" name="media" accept="image/*,video/*" required>'
        '<label for="pl">2. Ảnh biển số xe (nếu có)</label><input id="pl" type="file" name="plate" accept="image/*">'
        '<label for="pp">3. Ảnh giấy tờ có tên tài xế và số điện thoại (nếu có)</label><input id="pp" type="file" name="paper" accept="image/*">'
        '<p class="mute">Ảnh giấy tờ chỉ dùng để đọc tên và số điện thoại rồi xoá ngay, hệ thống không lưu ảnh giấy tờ.</p>'
        '<button class="full">Quét bằng mô hình</button></form></div></div>', h, "/gate"))

def in_manual(h):
    f = h.form()
    if not ops(h) or not A.csrf_ok(h, f): return
    pid, errs = G.create_pass(h.db, h.user, f, "manual", confirm_now=(f.get("act") == "create_confirm"))
    if pid: return h.redirect(f"/pass/{pid}?m={'in' if f.get('act') == 'create_confirm' else 'created'}")
    gate_in(h, f, errs, show_accept=any("ISO 6346" in e for e in errs), code=200)

def in_auto(h):
    if not ops(h): return
    f, up, err = read_uploads(h)
    if f is None: return
    if up is None: return gate_in(h, None, [err])
    job = G.start_job(h.user["id"], "in", up["media"][0], up["media"][1], extras=up["extras"]); h.redirect(f"/job/{job['id']}")

# ---------------------------------------------------------------- job (chạy mô hình)
def get_job(h, jid):
    j = G.JOBS.get(jid)
    if j is None or (j["user_id"] != h.user["id"] and h.user["role"] != "admin"):
        h.send(404, A.page("Không tìm thấy", '<div class="box"><h2>Không thấy lượt đọc này</h2><p>Cổng có thể đã khởi động lại. Hãy tải ảnh/video lại.</p><a href="/gate">Về cổng</a></div>', h)); return None
    return j

def readbox(r, j):
    out = []
    if j.get("has_plate"):
        raw = " | ".join(r.get("plate_raw") or []) or "—"
        if r.get("plate_text"):
            weak = r.get("plate_source") != "CCT"
            out.append(f'<div class="banner warn">Biển số gợi ý: <span class="big">{E(r["plate_text"])}</span> <span class="mute">({E(r.get("plate_source", ""))}; {E(r.get("plate_how", ""))})</span><br>Chữ đọc được: <span class="mono">{E(raw)}</span><br>'
                       + ("OCR chung dễ đọc sai mà vẫn ra chuỗi trông hợp lệ. " if weak else "") + "<b>Đối chiếu với biển số thật trên xe.</b></div>")
        else: out.append(f'<div class="banner warn">Chưa đọc ra biển số từ ảnh (chữ đọc được: <span class="mono">{E(raw)}</span>). Nhập tay.</div>')
    if j.get("has_paper"):
        out.append(f'<div class="banner warn">Giấy tờ: tên <b>{E(r.get("owner_name") or "—")}</b> · số điện thoại <b>{E(r.get("owner_phone") or "—")}</b><br><span class="mute">Chữ đọc được: {E(" | ".join(r.get("paper_raw") or []) or "—")}</span><br>'
                   'Ảnh giấy tờ đã được xoá sau khi đọc. Đọc tên có dấu tiếng Việt hay sai, hãy sửa nếu cần.</div>')
    for n in r.get("ocr_notes") or []: out.append(f'<div class="info" style="margin-bottom:10px">{E(n)}</div>')
    return "".join(out)

def job_page(h, jid):
    if not ops(h): return
    j = get_job(h, jid)
    if j is None: return
    back = "/gate/in" if j["purpose"] == "in" else f"/pass/{j['pass_id']}/out"
    if j["status"] in ("queued", "running"):
        return h.send(200, A.page("Đang đọc", f'<div class="box"><h2>Đang chạy mô hình… ({int(time.time() - j["t0"])} giây)</h2><p class="mute">Lần đầu mất khoảng 10-30 giây vì nạp mô hình. Trang tự làm mới.</p>'
            f'<pre style="background:#121a22;color:#cfe3f0;padding:12px;border-radius:6px;max-height:260px;overflow:auto">{E(chr(10).join(j["log"][-12:]) or "(chưa có nhật ký)")}</pre></div>', h, "/gate", refresh=3))
    if j["status"] == "error":
        return h.send(200, A.page("Lỗi đọc", f'<div class="box"><h2>Mô hình chạy lỗi</h2><div class="err">{E(j["error"])}</div><pre style="background:#121a22;color:#cfe3f0;padding:12px;border-radius:6px;max-height:300px;overflow:auto">{E(chr(10).join(j["log"][-25:]))}</pre>'
            f'<p>Bạn vẫn có thể làm <b>thủ công</b>. <a href="{back}">Quay lại</a></p></div>', h, "/gate"))
    r = j["result"]; code = r["code"]; guess = code or G.clean(r["raw_text"]); ok = bool(code)
    imgs = "".join(f'<div><div class="mute">{t}</div><img class="ev" src="/job/{jid}/img?f={k}" alt="{t}"></div>' for k, t in (("proc", "Ảnh đã khoanh vùng"), ("crop", "Vùng số container"), ("plate", "Ảnh biển số")) if r.get(k + "_path"))
    banner = (f'<div class="banner {"ok" if ok else "warn"}">' + (f'Mô hình đọc: <span class="big">{E(code)}</span> — hợp lệ ISO 6346. {E(r["note"])}.' if ok else
              f'Mô hình CHƯA đọc ra mã hợp lệ (chữ đọc được: <span class="mono">{E(r["raw_text"] or "—")}</span>). Nhìn ảnh và nhập tay số container.') + " <b>Luôn nhìn ảnh để xác nhận.</b></div>")
    if j["purpose"] == "in":
        pre = {"container_no": guess, "truck_plate": r.get("plate_text", ""), "owner_name": r.get("owner_name", ""), "owner_phone": r.get("owner_phone", "")}
        form = manual_form(h, pre, action=f"/job/{jid}/create_in", hint='<div class="info" style="margin:10px 0">Các ô đã điền sẵn từ ảnh. Sửa nếu sai, chọn khách hàng và bên trả phí rồi xác nhận.</div>')
    else:
        form = (f'<form method="post" action="/pass/{j["pass_id"]}/out/check">{csrf_in(h)}<input type="hidden" name="job_id" value="{jid}"><input type="hidden" name="m" value="{E(j["scan"])}">'
                f'<label for="c">Số container đọc lúc ra (sửa nếu đọc sai)</label><input id="c" name="container_read" class="mono" value="{E(guess)}" required><label for="p">Biển số xe lúc ra</label><input id="p" name="plate_read" value="{E(r.get("plate_text", ""))}" required autofocus>'
                '<button class="full">Đối chiếu với phiếu</button></form>')
    h.send(200, A.page("Kết quả đọc", f'<h2>Kết quả quét bằng mô hình</h2>{banner}{readbox(r, j)}<div class="grid2"><div class="box">{imgs}</div><div class="box">{form}</div></div>', h, "/gate"))

def job_img(h, jid):
    if not ops(h): return
    j = get_job(h, jid)
    if j is None: return
    if not j.get("result"): return h.send(404, "")
    path = j["result"].get({"proc": "proc_path", "cut": "cut_path", "crop": "crop_path", "plate": "plate_path"}.get(h.q.get("f", ""), ""))
    if not path or not Path(path).exists(): return h.send(404, "")
    h.send_bytes(200, Path(path).read_bytes(), "image/jpeg")

def job_create_in(h, jid):
    f = h.form()
    if not ops(h) or not A.csrf_ok(h, f): return
    j = get_job(h, jid)
    if j is None or j["purpose"] != "in" or j["status"] != "done": return
    pid, errs = G.create_pass(h.db, h.user, f, "auto", job=j, confirm_now=(f.get("act") == "create_confirm"))
    if pid: return h.redirect(f"/pass/{pid}?m={'in' if f.get('act') == 'create_confirm' else 'created'}")
    gate_in(h, f, errs, show_accept=any("ISO 6346" in e for e in errs))

# ---------------------------------------------------------------- phiếu
def pass_detail(h, pid):
    if not A.need_login(h): return
    p = get_pass(h, pid)
    if p is None: return
    db, u, now = h.db, h.user, time.time(); is_staff = u["role"] in G.STAFF
    fee = None; elapsed = None
    if p["status"] == "inside": fee = G.fee_calc(db, p["size"], p["in_at"], now); elapsed = now - p["in_at"]
    elif p["status"] == "closed": fee = json.loads(p["fee_detail"] or "{}"); elapsed = (p["out_at"] or 0) - (p["in_at"] or 0)
    cust = db.execute("SELECT full_name, company FROM users WHERE id=?", (p["customer_id"],)).fetchone() if p["customer_id"] else None
    info = kv([("Số phiếu", f'<span class="big">{E(p["pass_no"])}</span>'), ("Trạng thái", tag(p["status"])), ("Số container", f'<span class="big">{E(p["container_no"])}</span>'),
               ("Cỡ / mã loại", E(p["size"] + " feet" + (" · " + p["iso_type"] if p["iso_type"] else ""))), ("Biển số xe", f'<span class="big">{E(p["truck_plate"])}</span>'),
               ("Chủ xe / tài xế", E(" · ".join(x for x in (p["owner_name"], p["owner_phone"]) if x))), ("Khách hàng (tài khoản)", E(cust["full_name"] + (" · " + cust["company"] if cust["company"] else "")) if cust else ""),
               ("Cách tạo", "Tự động (mô hình YOLO)" if p["mode"] == "auto" else "Thủ công"), ("Tạo lúc", E(A.fmt_ts(p["created_at"]))), ("Giờ vào bãi", E(A.fmt_ts(p["in_at"])) if p["in_at"] else ""),
               ("Giờ ra bãi", E(A.fmt_ts(p["out_at"])) if p["out_at"] else ""), ("Ghi chú", E(p["note"])), ("Lý do huỷ", E(p["cancel_reason"]))])
    live = ""
    if p["status"] == "inside": live = f'<div class="banner warn">ĐANG TRONG BÃI: <span class="big" data-since="{p["in_at"]}">{E(G.dur_text(elapsed))}</span> &nbsp; (đồng hồ chạy từng giây, tiền bãi cập nhật mỗi 20 giây)</div>'
    elif p["status"] == "closed": live = f'<div class="banner ok">Đã ra bãi. Thời gian ở bãi: <b>{E(G.dur_text(elapsed))}</b></div>'
    elif p["status"] == "pending": live = '<div class="banner warn">Phiếu đã tạo, chưa xác nhận vào bãi.</div>'
    feebox = ""
    if fee:
        ln = "".join(f'<tr><td>{E(x["label"])}</td><td>{lq(x)} {lu(x)}</td><td>{G.money(x["rate"])}/{lu(x)}</td><td>{G.money(x["amount"])}</td></tr>' for x in fee["lines"])
        lift = f'<tr><td colspan="3">Phí nâng hạ</td><td>{G.money(fee["lift"])}</td></tr>' if fee["lift"] else ""
        head = ("Tạm tính tới giờ (chốt khi ra bãi)" if p["status"] == "inside" else "Thành tiền")
        paid = (f'<p>Bên trả phí: <b>{E(G.FEE_PARTIES.get(p["fee_party"], ""))}</b> · Thanh toán: <b>{E(G.voucher_state(p)[0])}</b> · <a href="/voucher/{p["id"]}">Phiếu thanh toán</a></p>' if p["status"] == "closed" else f'<p>Bên trả phí: <b>{E(G.FEE_PARTIES.get(p["fee_party"], ""))}</b></p>')
        feebox = (f'<div class="box"><h2>Tiền bãi</h2><p>{head}: <span class="big">{G.money(fee["total"])}</span> &nbsp;<span class="mute">({E(fee_note(fee))}; mỗi 24 giờ là 1 ngày, phần dư tính theo đơn giá giờ)</span></p>'
                  f'<div class="wrap"><table><tr><th>Bậc</th><th>Số lượng</th><th>Đơn giá</th><th>Tiền</th></tr>{ln}{lift}</table></div>'
                  + (f'<div class="err">{E(fee["warn"])}</div>' if fee.get("warn") else "") + paid + '</div>')
    qr = (f'<div class="box" style="text-align:center"><h2>Mã QR của phiếu</h2>{qr_svg(G.qr_payload(p))}<p class="mute">Chủ xe giữ mã này, đưa cho cổng quét khi ra bãi.<br><span class="mono">{E(G.qr_payload(p))}</span></p></div>' if p["status"] in ("pending", "inside") else "")
    acts = ""
    if u["role"] in G.OPS:
        if p["status"] == "pending":
            acts = (f'<form method="post" action="/pass/{p["id"]}/in/confirm" style="display:inline">{csrf_in(h)}<button class="big2 green">Xác nhận VÀO bãi</button></form>'
                    f'<form method="post" action="/pass/{p["id"]}/cancel" class="noprint" style="margin-top:12px">{csrf_in(h)}<div class="row2"><input name="reason" placeholder="Lý do huỷ phiếu" required><div><button class="red">Huỷ phiếu</button></div></div></form>')
        elif p["status"] == "inside": acts = f'<a class="btn big2" href="/pass/{p["id"]}/out">Xác minh và cho RA bãi</a>'
        elif p["status"] == "closed": acts = f'<a class="btn big2" href="/voucher/{p["id"]}">Phiếu thanh toán</a>'
    if u["role"] not in G.OPS and p["status"] == "closed": acts = f'<a class="btn big2" href="/voucher/{p["id"]}">Phiếu thanh toán</a>'
    ev = "".join(f'<tr><td>{E(A.fmt_ts(e["ts"]))}</td><td>{"VÀO" if e["direction"] == "in" else "RA"}</td><td>{E(e["note"])}{" · <b>có chỉnh tay/lệch</b>" if e["manual_override"] else ""}</td><td>{E(e["who"] or "")}</td></tr>'
                 for e in db.execute("SELECT e.*, u.full_name AS who FROM gate_events e LEFT JOIN users u ON u.id=e.confirmed_by WHERE e.pass_id=? ORDER BY e.id", (p["id"],)))
    imgs = "".join(f'<div><div class="mute">{t}</div><img class="ev" src="/evidence/{p["id"]}/{k}" alt="{t}"></div>' for k, t, c in (("in", "Ảnh lúc vào", p["in_image"]), ("plate", "Ảnh biển số", p["plate_image"]), ("out", "Ảnh lúc ra", p["out_image"])) if c) if is_staff else ""
    body = (f'{flash(h)}{live}<div class="grid2"><div class="box"><h2>Phiếu điện tử ra/vào bãi</h2>{info}<div class="btnrow noprint">{acts}</div></div><div>{qr}{feebox}</div></div>'
            + (f'<div class="box"><h2>Ảnh bằng chứng</h2><div class="grid2">{imgs}</div></div>' if imgs else "")
            + f'<div class="box"><h2>Lịch sử phiếu</h2><div class="wrap"><table><tr><th>Lúc</th><th>Cổng</th><th>Nội dung</th><th>Người thao tác</th></tr>{ev}</table></div><p class="mute noprint">In phiếu: nhấn Ctrl+P.</p></div>')
    h.send(200, A.page(p["pass_no"], body, h, "/passes", refresh=20 if p["status"] == "inside" else 0))

def _act(h, pid, fn_name):
    f = h.form()
    if not ops(h) or not A.csrf_ok(h, f): return None, None
    return f, h.db.execute("SELECT * FROM gate_passes WHERE id=?", (int(pid),)).fetchone()

def pass_in(h, pid):
    f, p = _act(h, pid, "in")
    if p is None: return
    errs = G.confirm_in(h.db, h.user, p["id"])
    h.redirect(f"/pass/{p['id']}?m=in") if not errs else h.send(409, A.page("Không xác nhận được", f'<div class="box">{A.errbox(errs)}<a href="/pass/{p["id"]}">Quay lại phiếu</a></div>', h))

def pass_cancel(h, pid):
    f, p = _act(h, pid, "cancel")
    if p is None: return
    errs = G.cancel_pass(h.db, h.user, p["id"], f.get("reason", ""))
    h.redirect(f"/pass/{p['id']}?m=cancel") if not errs else h.send(409, A.page("Không huỷ được", f'<div class="box">{A.errbox(errs)}<a href="/pass/{p["id"]}">Quay lại phiếu</a></div>', h))

def pass_paid(h, pid):
    f, p = _act(h, pid, "paid")
    if p is None: return
    G.mark_paid(h.db, h.user, p["id"]); h.redirect(f"/pass/{p['id']}?m=paid")

# ---------------------------------------------------------------- cổng RA
def gate_out(h, errs=()):
    if not ops(h): return
    h.send(200, A.page("Cho xe ra", f'<div class="box" style="max-width:640px"><h2>Cho xe RA bãi</h2><p class="mute">Chủ xe đưa mã QR của phiếu. Quét bằng máy quét (máy tự gõ vào ô dưới) rồi nhấn Enter.</p>{A.errbox(errs)}'
        f'<form method="post" action="/gate/out/find">{csrf_in(h)}<label for="sc">Mã QR / số phiếu</label><input id="sc" name="scan" autocomplete="off" autofocus required placeholder="SPASS|PASS-…  hoặc  PASS-20261029-0001"><button class="full big2">Tìm phiếu</button></form></div>', h, "/gate"))

def out_find(h):
    f = h.form()
    if not ops(h) or not A.csrf_ok(h, f): return
    p, how, msg = G.find_by_scan(h.db, f.get("scan", ""))
    if p is None: return gate_out(h, [msg])
    if p["status"] != "inside": return gate_out(h, [f"Phiếu {p['pass_no']} đang ở trạng thái '{G.PASS_STATUS[p['status']]}', không cho ra được. Xem phiếu: /pass/{p['id']}"])
    h.redirect(f"/pass/{p['id']}/out?m={how}")

def _out_header(h, p, how):
    warn = ('<div class="banner warn">Phiếu được tìm bằng gõ số, KHÔNG quét QR. Chỉ dùng khi mã QR hỏng; cân nhắc hỏi thêm giấy tờ xe.</div>' if how == "tay" else "")
    return warn + f'<div class="box"><h2>Phiếu trên giấy: {E(p["pass_no"])}</h2>' + kv([("Số container", f'<span class="big">{E(p["container_no"])}</span>'), ("Biển số xe", f'<span class="big">{E(p["truck_plate"])}</span>'), ("Vào bãi lúc", E(A.fmt_ts(p["in_at"])))]) + "</div>"

def _out_open(h, pid):
    if not ops(h): return None
    p = h.db.execute("SELECT * FROM gate_passes WHERE id=?", (int(pid),)).fetchone()
    if p is None: h.send(404, A.page("Không tìm thấy", '<div class="box"><h2>Không có phiếu</h2></div>', h)); return None
    if p["status"] != "inside": h.send(409, A.page("Không cho ra được", f'<div class="box"><h2>Phiếu {E(p["pass_no"])} đang ở trạng thái: {E(G.PASS_STATUS[p["status"]])}</h2><a href="/pass/{p["id"]}">Xem phiếu</a></div>', h)); return None
    return p

def out_page(h, pid):
    p = _out_open(h, pid)
    if p is None: return
    how = h.q.get("m", "")
    h.send(200, A.page("Xác minh ra", f'<h2>Xác minh xe RA bãi</h2>{_out_header(h, p, how)}<p class="mute">Nhìn container và biển số xe thật, rồi chọn một cách nhập. Hệ thống sẽ so với phiếu và chỉ ra dòng nào lệch.</p><div class="grid2">'
        f'<div class="box"><h2>1. Thủ công</h2><form method="post" action="/pass/{p["id"]}/out/check">{csrf_in(h)}<input type="hidden" name="m" value="{E(how)}">'
        '<label for="c">Số container thật trên thùng</label><input id="c" name="container_read" class="mono" required autofocus><label for="pl">Biển số xe thật</label><input id="pl" name="plate_read" required><button class="full">Đối chiếu với phiếu</button></form></div>'
        f'<div class="box"><h2>2. Tự động (ảnh/video)</h2><form method="post" action="/pass/{p["id"]}/out/auto" enctype="multipart/form-data">{csrf_in(h)}<input type="hidden" name="m" value="{E(how)}">'
        '<label for="md">Ảnh hoặc video thùng container</label><input id="md" type="file" name="media" accept="image/*,video/*" required><label for="mp">Ảnh biển số xe (nếu có)</label><input id="mp" type="file" name="plate" accept="image/*"><button class="full">Quét bằng mô hình</button></form></div></div>', h, "/gate"))

def out_auto(h, pid):
    p = _out_open(h, pid)
    if p is None: return
    f, up, err = read_uploads(h)
    if f is None: return
    if up is None: return h.send(200, A.page("Xác minh ra", f'<div class="box">{A.errbox([err])}<a href="/pass/{p["id"]}/out">Quay lại</a></div>', h))
    ex = {k: x for k, x in up["extras"].items() if k == "plate"}
    job = G.start_job(h.user["id"], "out", up["media"][0], up["media"][1], pass_id=p["id"], scan=f.get("m", ""), extras=ex); h.redirect(f"/job/{job['id']}")

def out_check(h, pid):
    f = h.form()
    if not ops(h) or not A.csrf_ok(h, f): return
    p = _out_open(h, pid)
    if p is None: return
    cr, pr = f.get("container_read", ""), f.get("plate_read", ""); how = f.get("m", ""); j = G.JOBS.get(f.get("job_id", ""))
    if j is not None and (j["user_id"] != h.user["id"] and h.user["role"] != "admin" or j.get("pass_id") != p["id"]): j = None
    rows = G.compare_out(p, cr, pr); bad = [r["label"] for r in rows if not r["ok"]]; iso_ok = G.is_valid_container(cr)
    tb = "".join(f'<tr class="{"good" if r["ok"] else "bad"}"><td><b>{E(r["label"])}</b></td><td class="mono big">{r["he"]}</td><td class="mono big">{r["hg"]}</td><td>{"KHỚP" if r["ok"] else "<b>LỆCH — kiểm tra lại bằng mắt</b>"}</td></tr>' for r in rows)
    banner = ('<div class="banner ok">KHỚP CẢ HAI DÒNG. Có thể cho xe ra.</div>' if not bad else f'<div class="banner no">LỆCH Ở {len(bad)} DÒNG: {E(", ".join(bad))}. Nhìn lại thùng/biển số thật. Ký tự khác nhau được tô đỏ.</div>')
    iso = ("" if iso_ok or not G.clean(cr) else '<div class="banner warn">Số container vừa nhập/đọc KHÔNG qua kiểm tra ISO 6346 (nhiều khả năng đọc/gõ sai một ký tự).</div>')
    ev = (f'<div class="box"><h2>Ảnh mô hình đọc lúc ra</h2><img class="ev" src="/job/{j["id"]}/img?f=proc" alt="Ảnh lúc ra"></div>' if j and j.get("result") and j["result"].get("proc_path") else "")
    hid = f'{csrf_in(h)}<input type="hidden" name="container_read" value="{E(cr)}"><input type="hidden" name="plate_read" value="{E(pr)}"><input type="hidden" name="m" value="{E(how)}"><input type="hidden" name="job_id" value="{E(f.get("job_id", ""))}">'
    fee, terms, cdays, prepay = G.exit_quote(h.db, p)
    qrows = "".join(f'<tr><td>{E(x["label"])}</td><td>{lq(x)} {lu(x)}</td><td>{G.money(x["rate"])}/{lu(x)}</td><td style="text-align:right">{G.money(x["amount"])}</td></tr>' for x in fee["lines"])
    qrows += f'<tr><td colspan="3">Phí nâng hạ</td><td style="text-align:right">{G.money(fee["lift"])}</td></tr>' if fee["lift"] else ""
    if prepay: qnote = '<div class="banner warn"><b>Phải thanh toán trước khi ra</b> (khách vãng lai hoặc khách trả trước tại cổng). Tích đủ 2 xác nhận bên dưới.</div>'
    elif fee["total"] > 0: qnote = f'<div class="banner ok">Khách công nợ: được ra bãi ngay. Hạn thanh toán {E(time.strftime("%d/%m/%Y", time.localtime(time.time() + cdays * 86400)))} ({cdays} ngày).</div>'
    else: qnote = '<div class="banner ok">Miễn phí lưu bãi, không phát sinh tiền.</div>'
    quote = (f'<div class="box"><h2>Tiền bãi tới giờ: <span class="big">{G.money(fee["total"])}</span></h2><p class="mute">{E(fee_note(fee))}</p><div class="wrap"><table><tr><th>Bậc</th><th>Số lượng</th><th>Đơn giá</th><th style="text-align:right">Tiền</th></tr>{qrows}</table></div>{qnote}'
             + (f'<div class="err">{E(fee["warn"])}</div>' if fee.get("warn") else "") + "</div>")
    pf = ""
    if prepay:
        pf = (f'<input type="hidden" name="fee_expected" value="{fee["total"]}"><div class="row2"><div><label for="pm">Hình thức thanh toán</label><select id="pm" name="pay_method">{opts({"cash": "Tiền mặt", "transfer": "Chuyển khoản", "other": "Khác"}, "cash")}</select></div>'
              '<div><label for="pr">Mã tham chiếu (nếu có)</label><input id="pr" name="pay_ref" maxlength="60"></div></div>'
              '<label style="font-weight:400"><input type="checkbox" name="pay_received" value="1"> Xác nhận 1: bãi ĐÃ NHẬN đủ tiền</label>'
              '<label style="font-weight:400"><input type="checkbox" name="pay_confirmed" value="1"> Xác nhận 2: khách ĐÃ XÁC NHẬN thanh toán (phiếu đóng dấu đỏ ĐÃ XÁC NHẬN)</label>')
    if not bad: act = f'<form method="post" action="/pass/{p["id"]}/out/confirm">{hid}{pf}<button class="big2 green">XÁC NHẬN RA BÃI (hoàn tất phiếu)</button></form>'
    else: act = (f'<form method="post" action="/pass/{p["id"]}/out/confirm">{hid}{pf}<label for="rs">Cho ra dù lệch: ghi lý do (lưu vào phiếu, Admin boss xem ở mục Ngoại lệ cổng)</label><textarea id="rs" name="reason" rows="2" required></textarea><button class="big2 red">Cho ra dù lệch</button></form>')
    fix = (f'<div class="box"><h2>Gõ lại và đối chiếu</h2><form method="post" action="/pass/{p["id"]}/out/check">{csrf_in(h)}<input type="hidden" name="m" value="{E(how)}"><input type="hidden" name="job_id" value="{E(f.get("job_id", ""))}">'
           f'<div class="row2"><div><label for="c">Số container</label><input id="c" name="container_read" class="mono" value="{E(cr)}"></div><div><label for="p">Biển số xe</label><input id="p" name="plate_read" value="{E(pr)}"></div></div><button class="gray">Đối chiếu lại</button></form></div>')
    h.send(200, A.page("Kết quả đối chiếu", f'<h2>Đối chiếu lúc ra với phiếu</h2>{banner}{iso}<div class="box"><div class="wrap"><table><tr><th>Hạng mục</th><th>Trên phiếu (vào bãi)</th><th>Lúc ra (đọc/nhập)</th><th>Kết quả</th></tr>{tb}</table></div></div>{quote}<div class="box"><div class="btnrow" style="margin-top:0;display:block">{act}</div></div>{ev}{fix}', h, "/gate"))

def out_confirm(h, pid):
    f = h.form()
    if not ops(h) or not A.csrf_ok(h, f): return
    p = _out_open(h, pid)
    if p is None: return
    j = G.JOBS.get(f.get("job_id", ""))
    if j is not None and (j["user_id"] != h.user["id"] and h.user["role"] != "admin" or j.get("pass_id") != p["id"]): j = None
    pay = {"method": f.get("pay_method"), "ref": f.get("pay_ref"), "received": f.get("pay_received") == "1", "confirmed": f.get("pay_confirmed") == "1", "expected": f.get("fee_expected")}
    errs = G.confirm_out(h.db, h.user, p["id"], f.get("container_read", ""), f.get("plate_read", ""), f.get("m", ""), j, f.get("reason", ""), pay)
    h.redirect(f"/pass/{p['id']}?m=out") if not errs else h.send(409, A.page("Không cho ra được", f'<div class="box">{A.errbox(errs)}<a href="/pass/{p["id"]}/out">Quay lại</a></div>', h))

def evidence(h, pid, which):
    if not A.need_login(h): return
    p = get_pass(h, pid)
    if p is None: return
    rel = p[{"in": "in_image", "out": "out_image", "plate": "plate_image"}[which]]; path = (G.EVID / rel).resolve() if rel else None
    if not path or G.EVID.resolve() not in path.parents or not path.exists() or h.user["role"] not in G.STAFF: return h.send(404, "")
    h.send_bytes(200, path.read_bytes(), "image/jpeg")

# ---------------------------------------------------------------- tìm kiếm
def passes(h):
    if not A.need_login(h): return
    q = h.q; view = "group" if q.get("view") == "group" else "list"; multi = q.get("multi") == "1"
    sort = q.get("sort", "created") if q.get("sort") in G.SORTS else "created"; dr = "asc" if q.get("dir") == "asc" else "desc"
    rows = G.search(h.db, h.user, q.get("q", ""), q.get("status", ""), q.get("from", ""), q.get("to", ""), limit=1000 if view == "group" else 300,
                    size=q.get("size", ""), mode=q.get("mode", ""), paid=q.get("paid", ""), party=q.get("party", ""), sort=sort, direction=dr)
    keep = {k: q[k] for k in ("q", "status", "from", "to", "size", "mode", "paid", "party", "view", "multi") if q.get(k)}
    def sl(key, label):
        nd = "asc" if (sort == key and dr == "desc") else "desc"
        arrow = (" ▲" if dr == "asc" else " ▼") if sort == key else ""
        return f'<a href="/passes?{E(urlencode({**keep, "sort": key, "dir": nd}))}">{label}{arrow}</a>'
    head = [sl("pass", "Số phiếu"), sl("container", "Container"), sl("plate", "Biển số xe"), sl("status", "Trạng thái"), sl("in", "Giờ vào"), sl("out", "Giờ ra"), sl("fee", "Tiền bãi"), "Thanh toán", "Cách tạo"]
    st = {"": "Mọi trạng thái", **G.PASS_STATUS}
    sel = lambda name, d, cur: f'<select name="{name}">{opts(d, cur)}</select>'
    form = ('<div class="box"><h2>Tìm, lọc, sắp xếp</h2><form method="get" action="/passes">'
            f'<div class="row2" style="grid-template-columns:2fr 1fr 1fr 1fr 1fr;align-items:end"><div><label for="q">Số phiếu / container / biển số / tên / SĐT</label><input id="q" name="q" value="{E(q.get("q", ""))}" autofocus></div>'
            f'<div><label>Trạng thái</label>{sel("status", st, q.get("status", ""))}</div><div><label>Cỡ</label>{sel("size", {"": "Mọi cỡ", "20": "20 feet", "40": "40 feet", "45": "45 feet"}, q.get("size", ""))}</div>'
            f'<div><label>Cách tạo</label>{sel("mode", {"": "Tất cả", "manual": "Thủ công", "auto": "Tự động"}, q.get("mode", ""))}</div><div><label>Thanh toán</label>{sel("paid", {"": "Tất cả", "unpaid": "Đã ra, chưa thu", "paid": "Đã thu"}, q.get("paid", ""))}</div></div>'
            f'<div class="row2" style="grid-template-columns:1fr 1fr 1fr 1fr 1fr auto;align-items:end;margin-top:8px"><div><label for="f">Tạo từ ngày</label><input id="f" type="date" name="from" value="{E(q.get("from", ""))}"></div>'
            f'<div><label for="t">Đến ngày</label><input id="t" type="date" name="to" value="{E(q.get("to", ""))}"></div><div><label>Bên trả phí</label>{sel("party", {"": "Tất cả", **G.FEE_PARTIES}, q.get("party", ""))}</div>'
            f'<div><label>Sắp xếp theo</label>{sel("sort", {"created": "Ngày tạo", "pass": "Số phiếu", "container": "Container", "plate": "Biển số", "status": "Trạng thái", "in": "Giờ vào", "out": "Giờ ra", "fee": "Tiền bãi"}, sort)}</div>'
            f'<div><label>Thứ tự</label>{sel("dir", {"desc": "Mới/Lớn trước", "asc": "Cũ/Nhỏ trước"}, dr)}</div><div><button>Áp dụng</button></div></div>'
            f'<div class="row2" style="grid-template-columns:auto auto 1fr;margin-top:10px;align-items:center"><label style="margin:0;font-weight:400"><input type="radio" name="view" value="list"{" checked" if view == "list" else ""}> Danh sách</label>'
            f'<label style="margin:0;font-weight:400"><input type="radio" name="view" value="group"{" checked" if view == "group" else ""}> Nhóm theo số container</label>'
            f'<label style="margin:0;font-weight:400"><input type="checkbox" name="multi" value="1"{" checked" if multi else ""}> (khi nhóm) chỉ container vào bãi từ 2 lượt trở lên</label></div></form></div>')
    if view == "group":
        groups = {}
        for r in rows: groups.setdefault(r["container_no"], []).append(r)
        items = [(c, ps) for c, ps in groups.items() if len(ps) >= 2 or not multi]
        items.sort(key=lambda kv: (-len(kv[1]), -max(x["id"] for x in kv[1])))
        body = "".join(f'<details{" open" if len(ps) >= 2 else ""}><summary><b class="mono">{E(c)}</b> · {len(ps)} lượt · {"".join(tag(s) for s in dict.fromkeys(x["status"] for x in ps))} · tổng tiền bãi đã chốt: <b>{G.money(sum(x["fee_total"] or 0 for x in ps if x["status"] == "closed"))}</b></summary>{pass_table(ps)}</details>' for c, ps in items)
        emp = '<p class="mute">Không có phiếu phù hợp.</p>'
        res = f'<div class="box"><h2>{len(items)} container · {sum(len(ps) for _, ps in items)} phiếu</h2>{body or emp}</div>'
    else:
        res = f'<div class="box"><h2>{len(rows)} phiếu{" (hiện tối đa 300)" if len(rows) >= 300 else ""}</h2>{pass_table(rows, "Không có phiếu phù hợp.", head)}</div>'
    h.send(200, A.page("Phiếu điện tử", form + res, h, "/passes"))

# ---------------------------------------------------------------- bảng giá + mô hình (admin)
def money_in(s):
    """Đọc số tiền gõ kiểu Việt Nam: '10000', '10.000', '1.250.000', '10,000', ' 70 000 ' -> số nguyên. Sai thì None.
    Dấu . hoặc , chỉ được hiểu là ngăn cách hàng nghìn (đúng nhóm 3 chữ số); số lẻ (10.5) không hợp lệ vì tiền tính theo đồng."""
    s = re.sub(r"\s", "", str(s or ""))
    if re.fullmatch(r"\d+", s): n = int(s)
    elif re.fullmatch(r"\d{1,3}([.,]\d{3})+", s): n = int(re.sub(r"[.,]", "", s))
    else: return None
    return n if n <= 10 ** 9 else None

def tariff(h, errs=(), vals=None, code=200):
    if not A.need_role(h, "admin"): return
    db = h.db; q = h.q; v = vals or {}; fv = lambda k: E(v.get(k, ""))
    sections = ""
    for sz in ("20", "40", "45", "all"):
        tiers = db.execute("SELECT * FROM tariff_tiers WHERE size=? ORDER BY day_from", (sz,)).fetchall()
        if sz == "all" and not tiers: continue
        gaps = G.tariff_gaps(db, sz) if sz != "all" else []
        gb = (f'<div class="banner no">Cỡ {sz} feet <b>chưa có giá cho: {E(", ".join(gaps))}</b>. Các ngày này đang tính 0 đ. Thêm bậc giá ở bên dưới (bảng giá tính riêng từng cỡ).</div>' if gaps else "")
        tb = "".join(f'<tr><td>{t["day_from"]}</td><td>{t["day_to"] if t["day_to"] else "trở đi"}</td><td>{G.money(t["rate"])}/ngày</td><td>{G.money(t["hour_rate"]) + "/giờ" if t["hour_rate"] is not None else "tự động: ngày ÷ 24"}</td>'
                     f'<td><form method="post" action="/admin/tariff/del">{csrf_in(h)}<input type="hidden" name="id" value="{t["id"]}"><button class="sm red">Xoá</button></form></td></tr>' for t in tiers)
        title = f"Cỡ {sz} feet" if sz != "all" else "Bậc 'Mọi cỡ' (cũ): chỉ dùng khi một cỡ chưa có bậc riêng"
        sections += (f'<h3 style="margin:16px 0 6px">{title}</h3>{gb}<div class="wrap"><table><tr><th>Từ ngày</th><th>Đến ngày</th><th>Đơn giá ngày</th><th>Đơn giá giờ (cho phần dư)</th><th></th></tr>'
                     + (tb or '<tr><td colspan="5" class="mute">Chưa có bậc giá nào.</td></tr>') + "</table></div>")
    sim = ""
    if q.get("sz") in G.SIZES and (q.get("days") or "").isdigit() and 1 <= int(q["days"]) <= 3650:
        fe = G.fee_calc(db, q["sz"], 0, int(q["days"]) * 86400)
        sim = (f'<div class="info" style="margin-top:12px"><b>{q["days"]} ngày, cỡ {E(q["sz"])}:</b> {G.money(fe["total"])}<br>' + "<br>".join(f'{E(x["label"])}: {lq(x)} {lu(x)} × {G.money(x["rate"])} = {G.money(x["amount"])}' for x in fe["lines"]) + (f'<br>Phí nâng hạ: {G.money(fe["lift"])}' if fe["lift"] else "") + (f'<br><b>{E(fe["warn"])}</b>' if fe["warn"] else "") + "</div>")
    gs = lambda k: E(D.get_setting(db, k))
    sz_sel = opts({"all3": "Cả 3 cỡ (20, 40 và 45)", "20": "Chỉ cỡ 20", "40": "Chỉ cỡ 40", "45": "Chỉ cỡ 45"}, v.get("size", "all3"))
    reset = (f'<h2 style="margin-top:18px">Khôi phục bảng giá mặc định</h2><form method="post" action="/admin/tariff/reset">{csrf_in(h)}<label style="font-weight:400"><input type="checkbox" name="confirm" value="1"> Tôi hiểu: xoá toàn bộ bảng giá hiện tại, nạp lại bảng mặc định (số tạm). Phiếu đã chốt tiền không bị đổi.</label><button class="gray">Khôi phục mặc định</button></form>')
    h.send(code, A.page("Bảng giá & mô hình", f'{flash(h)}{A.errbox(errs)}<div class="box"><h2>Bảng giá lưu bãi (bậc theo ngày, tính riêng từng cỡ)</h2><div class="banner warn">Đây đang là <b>số tạm để chạy thử</b>. Hãy thay bằng biểu giá thật của bãi.</div>{sections}'
        f'<h2 style="margin-top:18px">Thêm bậc giá</h2><p class="mute">Gõ tiền kiểu <b>10000</b> hoặc <b>10.000</b> đều được. Chọn "Cả 3 cỡ" để thêm cùng một bậc cho 20, 40 và 45 cùng lúc. Ví dụ miễn phí 3 ngày đầu: từ ngày 1, đến ngày 3, đơn giá 0.</p>'
        f'<form method="post" action="/admin/tariff/add" class="row2" style="grid-template-columns:1.4fr 1fr 1fr 1fr 1fr auto;align-items:end">{csrf_in(h)}'
        f'<div><label for="sz">Áp dụng cho</label><select id="sz" name="size">{sz_sel}</select></div>'
        f'<div><label for="df">Từ ngày thứ</label><input id="df" name="day_from" inputmode="numeric" autocomplete="off" value="{fv("day_from")}" required></div><div><label for="dt">Đến ngày thứ (trống = trở đi)</label><input id="dt" name="day_to" inputmode="numeric" autocomplete="off" value="{fv("day_to")}"></div>'
        f'<div><label for="rt">Đơn giá ngày (đồng)</label><input id="rt" name="rate" inputmode="numeric" autocomplete="off" placeholder="70000 hoặc 70.000" value="{fv("rate")}" required></div><div><label for="hr">Đơn giá giờ (trống = ngày ÷ 24)</label><input id="hr" name="hour_rate" inputmode="numeric" autocomplete="off" value="{fv("hour_rate")}"></div><div><button>Thêm</button></div></form>'
        f'<h2 style="margin-top:18px">Tính thử</h2><form method="get" action="/admin/tariff" class="row2" style="grid-template-columns:1fr 1fr auto;align-items:end"><div><label for="sz2">Cỡ</label><select id="sz2" name="sz"><option>20</option><option selected>40</option><option>45</option></select></div>'
        f'<div><label for="dy">Số ngày ở bãi</label><input id="dy" name="days" type="number" min="1" value="{E(q.get("days", "12"))}"></div><div><button class="gray">Tính</button></div></form>{sim}{reset}</div>'
        f'<div class="box"><h2>Cài đặt</h2><form method="post" action="/admin/tariff/settings">{csrf_in(h)}<label for="yn">Tên bãi (in trên phiếu)</label><input id="yn" name="yard_name" value="{gs("yard_name")}">'
        f'<label for="mp">Đường dẫn mô hình YOLO (best.pt)</label><input id="mp" name="model_path" value="{gs("model_path")}"><div class="row2"><div><label for="is">Cỡ ảnh (bằng cỡ lúc train)</label><input id="is" name="imgsz" value="{gs("imgsz")}"></div><div><label for="cf">Ngưỡng tin cậy</label><input id="cf" name="conf" value="{gs("conf")}"></div></div>'
        f'<label for="hrd">Cách làm tròn phần dư theo giờ</label><select id="hrd" name="hour_round">{opts({"up": "Mỗi giờ bắt đầu tính trọn 1 giờ (7g01p = 8 giờ)", "down": "Chỉ tính giờ trọn (7g01p = 7 giờ)", "exact": "Theo phút, tỷ lệ chính xác"}, D.get_setting(db, "hour_round", "up"))}</select>'
        f'<label>Phí nâng hạ cố định mỗi phiếu (đồng, 0 = không thu)</label><div class="row2" style="grid-template-columns:1fr 1fr 1fr"><div><label for="l20">20 feet</label><input id="l20" name="lift_fee_20" value="{gs("lift_fee_20")}"></div><div><label for="l40">40 feet</label><input id="l40" name="lift_fee_40" value="{gs("lift_fee_40")}"></div><div><label for="l45">45 feet</label><input id="l45" name="lift_fee_45" value="{gs("lift_fee_45")}"></div></div>'
        '<button class="full">Lưu cài đặt</button></form></div>', h, "/admin/tariff"))

def _int(v, lo=0, hi=10**9):
    try: n = int(str(v).strip()); return n if lo <= n <= hi else None
    except ValueError: return None

def tariff_settings(h):
    f = h.form()
    if not A.need_role(h, "admin") or not A.csrf_ok(h, f): return
    errs, lifts = [], {}
    for k, lab in (("lift_fee_20", "20 feet"), ("lift_fee_40", "40 feet"), ("lift_fee_45", "45 feet")):
        lifts[k] = money_in(f.get(k) or "0")
        if lifts[k] is None: errs.append(f"Phí nâng hạ {lab}: nhập số tiền nguyên (vd 150000 hoặc 150.000).")
    imgsz = _int(f.get("imgsz"), 64, 4096)
    if imgsz is None: errs.append("Cỡ ảnh: nhập số nguyên từ 64 đến 4096 (bằng cỡ lúc train, ví dụ 960).")
    try: conf = float(f.get("conf", "0.25").replace(",", ".")); assert 0.01 <= conf <= 0.99
    except (ValueError, AssertionError): conf = None; errs.append("Ngưỡng tin cậy: nhập số từ 0.01 đến 0.99 (ví dụ 0.25).")
    if f.get("hour_round", "up") not in ("up", "down", "exact"): errs.append("Cách làm tròn giờ không hợp lệ.")
    if errs: return tariff(h, errs, None, 400)
    for k, n in lifts.items(): D.set_setting(h.db, k, n)
    D.set_setting(h.db, "imgsz", imgsz); D.set_setting(h.db, "conf", conf); D.set_setting(h.db, "hour_round", f.get("hour_round", "up"))
    D.set_setting(h.db, "yard_name", f.get("yard_name", "")[:80].strip() or "Bãi container SmartPort"); D.set_setting(h.db, "model_path", f.get("model_path", "").strip()[:300])
    D.audit(h.db, h.user["id"], "settings", "", h.ip()); h.redirect("/admin/tariff?m=saved")

def tariff_add(h):
    f = h.form()
    if not A.need_role(h, "admin") or not A.csrf_ok(h, f): return
    errs = []; size = f.get("size", ""); sizes = list(G.SIZES) if size == "all3" else ([size] if size in G.SIZES else [])
    if not sizes: errs.append("Chọn cỡ container (hoặc Cả 3 cỡ).")
    df = _int(f.get("day_from"), 1, 3650)
    if df is None: errs.append('"Từ ngày thứ": nhập số nguyên từ 1 đến 3650.')
    dt = None
    if f.get("day_to", "").strip():
        dt = _int(f.get("day_to"), 1, 3650)
        if dt is None: errs.append('"Đến ngày thứ": nhập số nguyên từ 1 đến 3650, hoặc để trống nếu áp dụng từ ngày đó trở đi.')
        elif df is not None and dt < df: errs.append(f'"Đến ngày" ({dt}) phải lớn hơn hoặc bằng "Từ ngày" ({df}).')
    rt = money_in(f.get("rate"))
    if rt is None: errs.append('Đơn giá ngày: nhập số tiền nguyên, ví dụ 70000 hoặc 70.000 (không dùng số lẻ).')
    hr = None
    if f.get("hour_rate", "").strip():
        hr = money_in(f.get("hour_rate"))
        if hr is None: errs.append('Đơn giá giờ: nhập số tiền nguyên (ví dụ 3000 hoặc 3.000), hoặc để trống để tự tính = đơn giá ngày ÷ 24.')
    if not errs:
        for sz in sizes:
            for t in h.db.execute("SELECT * FROM tariff_tiers WHERE size=?", (sz,)):
                if df <= (t["day_to"] or 10 ** 9) and t["day_from"] <= (dt or 10 ** 9):
                    errs.append("Cỡ %s: khoảng ngày %s–%s bị trùng với bậc đã có (%s–%s). Xoá bậc cũ trước, hoặc chọn khoảng ngày khác." % (sz, df, dt or "trở đi", t["day_from"], t["day_to"] or "trở đi"))
    if errs: return tariff(h, errs, f, 400)
    for sz in sizes: h.db.execute("INSERT INTO tariff_tiers(size,day_from,day_to,rate,hour_rate) VALUES(?,?,?,?,?)", (sz, df, dt, rt, hr))
    h.db.commit(); D.audit(h.db, h.user["id"], "tariff_add", f"{','.join(sizes)} {df}-{dt} {rt}", h.ip()); h.redirect("/admin/tariff?m=saved")

def tariff_reset(h):
    f = h.form()
    if not A.need_role(h, "admin") or not A.csrf_ok(h, f): return
    if f.get("confirm") != "1": return tariff(h, ["Tích ô xác nhận trước khi khôi phục bảng giá mặc định."], None, 400)
    D.reset_tiers(h.db); D.audit(h.db, h.user["id"], "tariff_reset", "", h.ip()); h.redirect("/admin/tariff?m=saved")

def tariff_del(h):
    f = h.form()
    if not A.need_role(h, "admin") or not A.csrf_ok(h, f): return
    i = _int(f.get("id"), 1)
    if i is None: raise ValueError("id")
    h.db.execute("DELETE FROM tariff_tiers WHERE id=?", (i,)); h.db.commit(); D.audit(h.db, h.user["id"], "tariff_del", str(i), h.ip()); h.redirect("/admin/tariff?m=saved")

# ---------------------------------------------------------------- dòng thời gian theo tháng (SVG, không cần script)
def timeline(h):
    if not A.need_login(h): return
    db, u, q = h.db, h.user, h.q; now = time.time(); lt = time.localtime()
    mm = re.fullmatch(r"(\d{4})-(\d{2})", q.get("month", "") or "")
    y, m = (int(mm.group(1)), int(mm.group(2))) if mm and 2000 <= int(mm.group(1)) <= 2100 and 1 <= int(mm.group(2)) <= 12 else (lt.tm_year, lt.tm_mon)
    nd = calendar.monthrange(y, m)[1]; start = time.mktime((y, m, 1, 0, 0, 0, 0, 0, -1)); end = start + nd * 86400
    sql = "SELECT * FROM gate_passes WHERE in_at IS NOT NULL AND in_at < ? AND COALESCE(out_at, ?) >= ?"; args = [end, now, start]
    if u["role"] == "customer": sql += " AND customer_id=?"; args.append(u["id"])
    cq = G.clean(q.get("q", ""))
    if cq: sql += " AND container_no LIKE ?"; args.append(f"%{cq}%")
    groups = {}
    for r in db.execute(sql + " ORDER BY container_no, in_at", args): groups.setdefault(r["container_no"], []).append(r)
    order = sorted(groups.items(), key=lambda kv: kv[1][0]["in_at"]); more = len(order) > 80; order = order[:80]
    LABEL, DW, TOP, RH = 178, 32, 46, 84; W = LABEL + nd * DW + 24; HT = TOP + max(1, len(order)) * RH + 26
    xs = lambda t: LABEL + (min(max(t, start), end) - start) / 86400 * DW
    lab = lambda t: time.strftime("%d/%m %H:%M", time.localtime(t))
    def anchor(x): return "start" if x < LABEL + 40 else ("end" if x > W - 72 else "middle")
    def put_label(taken, x, ym, txt, color, above):
        """Xếp nhãn giờ vào tầng chưa bị nhãn khác đè (2 tầng trên, 2 tầng dưới của đường ngang)."""
        an = anchor(x); wd = len(txt) * 5.6; x1, x2 = (x, x + wd) if an == "start" else ((x - wd, x) if an == "end" else (x - wd / 2, x + wd / 2))
        lv = ([-13, -26, 26, 39] if above else [26, 39, -13, -26]); pick = lv[0]
        for L in lv:
            if not any(abs(L - t[2]) < 11 and x1 < t[1] + 3 and x2 > t[0] - 3 for t in taken): pick = L; break
        taken.append((x1, x2, pick))
        return '<text x="%.1f" y="%.1f" font-size="10" text-anchor="%s" fill="%s">%s</text>' % (x, ym + pick + (0 if pick < 0 else 0), an, color, txt)
    P = ['<svg viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-label="Dòng thời gian container theo tháng" style="font-family:Segoe UI,Arial,sans-serif">' % (W, HT, W, HT)]
    for d in range(nd):
        x = LABEL + d * DW
        if calendar.weekday(y, m, d + 1) >= 5: P.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#f1f4f6"/>' % (x, TOP - 16, DW, HT - TOP - 6))
        P.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#e2e8ec"/><text x="%.1f" y="%d" font-size="11" text-anchor="middle" fill="#5d6e7a">%d</text>' % (x, TOP - 16, x, HT - 24, x + DW / 2, TOP - 22, d + 1))
    P.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#16232c" stroke-width="2"/><line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#16232c" stroke-width="2"/>' % (LABEL, TOP - 16, LABEL, HT - 24, LABEL, TOP - 16, W - 12, TOP - 16))
    P.append('<text x="8" y="%d" font-size="13" font-weight="700" fill="#16232c">Container (trục dọc)</text><text x="8" y="%d" font-size="11" fill="#5d6e7a">Tháng %d/%d → ngày</text>' % (TOP - 24, TOP - 8, m, y))
    if start <= now < end:
        tx = xs(now); P.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#c0392b" stroke-dasharray="4 3"/><text x="%.1f" y="%d" font-size="10" fill="#c0392b" text-anchor="middle">bây giờ</text>' % (tx, TOP - 16, tx, HT - 24, tx, HT - 10))
    for r, (cn, ps) in enumerate(order):
        ym = TOP + r * RH + RH / 2; taken = []
        P.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#cdd6dc" stroke-width="1.5"/>' % (LABEL, ym, W - 12, ym))
        P.append('<a href="/passes?q=%s"><text x="8" y="%.1f" font-size="13" font-weight="700" font-family="Consolas,monospace" fill="#2457a6">%s</text></a><text x="8" y="%.1f" font-size="11" fill="#5d6e7a">%d lượt · %s feet</text>' % (E(cn), ym - 2, E(cn), ym + 14, len(ps), E(ps[0]["size"])))
        for p in ps:
            ti, to = p["in_at"], p["out_at"]; inside = to is None; xi, xo = xs(ti), xs(to if to else min(now, end))
            dur = G.dur_text((to or now) - ti); ttl = f'{p["pass_no"]} · {cn} · vào {lab(ti)} · ' + (f'ra {lab(to)}' if to else "đang trong bãi") + f' · ở {dur}' + (f' · tiền {G.money(p["fee_total"])}' if to else "")
            P.append('<a href="/pass/%d"><rect x="%.1f" y="%.1f" width="%.1f" height="10" rx="5" fill="%s"%s><title>%s</title></rect></a>' % (p["id"], xi, ym - 5, max(3, xo - xi), "#f4c26b" if inside else "#7aa2d8", ' stroke="#d98c00" stroke-dasharray="5 3"' if inside else "", E(ttl)))
            if ti >= start: P.append('<a href="/pass/%d"><circle cx="%.1f" cy="%.1f" r="7" fill="#1e7a3c" stroke="#fff" stroke-width="2"><title>%s</title></circle></a>%s' % (p["id"], xi, ym, E("Vào: " + lab(ti)), put_label(taken, xi, ym, "vào " + lab(ti), "#1e7a3c", True)))
            else: P.append(put_label(taken, LABEL + 4, ym, "◂ vào " + lab(ti), "#1e7a3c", True))
            if to and to < end: P.append('<a href="/pass/%d"><circle cx="%.1f" cy="%.1f" r="7" fill="#c0392b" stroke="#fff" stroke-width="2"><title>%s</title></circle></a>%s' % (p["id"], xo, ym, E("Ra: " + lab(to)), put_label(taken, xo, ym, "ra " + lab(to), "#c0392b", False)))
            elif to: P.append(put_label(taken, W - 14, ym, "ra " + lab(to) + " ▸", "#c0392b", False))
            else: P.append('<circle cx="%.1f" cy="%.1f" r="7" fill="#fff" stroke="#d98c00" stroke-width="3"><title>Đang trong bãi tới giờ</title></circle>%s' % (xo, ym, put_label(taken, xo, ym, "đang trong bãi", "#b36b00", False)))
    P.append("</svg>")
    pm, nm = (f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"), (f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}")
    nav = lambda mon, t: f'<a class="btn gray sm" href="/timeline?{E(urlencode({"month": mon, "q": q.get("q", "")}))}">{t}</a>'
    form = (f'<form method="get" action="/timeline" class="row2" style="grid-template-columns:auto auto 1fr auto auto auto;align-items:end;gap:10px">{nav(pm, "◂ Tháng trước")}<div><label for="mo">Tháng</label><input id="mo" type="month" name="month" value="{y}-{m:02d}"></div>'
            f'<div><label for="qq">Lọc theo số container</label><input id="qq" name="q" value="{E(q.get("q", ""))}" placeholder="vd EITU"></div><div><button>Xem</button></div>{nav(nm, "Tháng sau ▸")}{nav(time.strftime("%Y-%m"), "Tháng này")}</form>')
    legend = '<p class="legend mute"><span><i style="background:#1e7a3c"></i>Giờ vào bãi</span><span><i style="background:#c0392b"></i>Giờ ra bãi</span><span><i style="background:#7aa2d8"></i>Thời gian ở bãi</span><span><i style="background:#f4c26b;border:1px dashed #d98c00"></i>Đang trong bãi</span>Di chuột vào chấm/thanh để xem giờ chi tiết, bấm để mở phiếu.</p>'
    body = (f'<div class="box"><h2>Dòng thời gian container trong tháng {m}/{y}</h2>{form}{legend}'
            + (f'<div class="wrap">{"".join(P)}</div>' if order else '<p class="mute">Không có container nào ở bãi trong tháng này.</p>')
            + (f'<p class="mute">Chỉ hiện 80 container đầu. Lọc theo số container để xem cụ thể.</p>' if more else "") + f'<p class="mute">{len(order)} container · {sum(len(ps) for _, ps in order)} lượt. Trang tự làm mới mỗi phút.</p></div>')
    h.send(200, A.page("Dòng thời gian", body, h, "/timeline", refresh=60))

# ---------------------------------------------------------------- phiếu thanh toán
def vouchers(h):
    if not A.need_login(h): return
    q = h.q; rows = G.search(h.db, h.user, q.get("q", ""), "closed", q.get("from", ""), q.get("to", ""), limit=500, sort="out", direction="desc")
    stf = q.get("st", "")
    if stf in ("wait", "cust", "bai", "done", "free"): rows = [r for r in rows if G.voucher_state(r)[1] == stf]
    owed = sum((r["fee_total"] or 0) for r in rows if G.voucher_state(r)[1] in ("wait", "cust"))
    tb = "".join(f'<tr><td><a href="/voucher/{r["id"]}"><b>{E(G.voucher_no(r))}</b></a></td><td class="mono">{E(r["container_no"])}</td><td>{E(r["truck_plate"])}</td><td>{E(A.fmt_ts(r["in_at"]))}</td><td>{E(A.fmt_ts(r["out_at"]))}</td>'
                 f'<td><b>{G.money(r["fee_total"])}</b></td><td>{E(G.voucher_state(r)[0])}</td><td>{"✔" if r["fee_paid"] and (r["fee_total"] or 0) else ""}</td><td>{"✔" if r["cust_confirmed_at"] else ""}</td></tr>' for r in rows)
    states = {"": "Tất cả", "wait": "Chờ thanh toán", "cust": "Khách đã xác nhận, chờ bãi nhận tiền", "bai": "Bãi đã nhận, chờ khách xác nhận", "done": "Đã thanh toán đầy đủ", "free": "Miễn phí"}
    h.send(200, A.page("Phiếu thanh toán", '<div class="box"><h2>Phiếu thanh toán</h2><form method="get" action="/vouchers" class="row2" style="grid-template-columns:2fr 2fr 1fr 1fr auto;align-items:end">'
        f'<div><label for="q">Số phiếu / container / biển số</label><input id="q" name="q" value="{E(q.get("q", ""))}"></div><div><label for="st">Tình trạng</label><select id="st" name="st">{opts(states, stf)}</select></div>'
        f'<div><label for="f">Từ ngày tạo</label><input id="f" type="date" name="from" value="{E(q.get("from", ""))}"></div><div><label for="t">Đến ngày</label><input id="t" type="date" name="to" value="{E(q.get("to", ""))}"></div><div><button>Lọc</button></div></form></div>'
        f'<div class="box"><h2>{len(rows)} phiếu thanh toán · còn phải thu: {G.money(owed)}</h2><div class="wrap"><table><tr><th>Số phiếu TT</th><th>Container</th><th>Biển số</th><th>Giờ vào</th><th>Giờ ra</th><th>Số tiền</th><th>Tình trạng</th><th>Bãi nhận</th><th>Khách xác nhận</th></tr>'
        + (tb or '<tr><td colspan="9" class="mute">Chưa có phiếu thanh toán. Phiếu xuất hiện sau khi xe ra bãi.</td></tr>') + "</table></div></div>", h, "/vouchers"))

def _uname(db, uid):
    r = db.execute("SELECT full_name FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return r["full_name"] if r else ""

def voucher(h, pid):
    if not A.need_login(h): return
    p = get_pass(h, pid)
    if p is None: return
    if p["status"] != "closed": return h.send(409, A.page("Chưa có phiếu thanh toán", f'<div class="box"><h2>Phiếu {E(p["pass_no"])} chưa ra bãi</h2><p>Phiếu thanh toán chỉ có sau khi xe ra bãi và tiền bãi được chốt.</p><a href="/pass/{p["id"]}">Xem phiếu</a></div>', h))
    db, u = h.db, h.user; fee = json.loads(p["fee_detail"] or "{}"); total = p["fee_total"] or 0; state, grp = G.voucher_state(p); is_staff = u["role"] in G.STAFF
    cust = db.execute("SELECT full_name, company FROM users WHERE id=?", (p["customer_id"],)).fetchone() if p["customer_id"] else None
    ln = "".join(f'<tr><td>{E(x["label"])}</td><td>{lq(x)} {lu(x)}</td><td>{G.money(x["rate"])}/{lu(x)}</td><td style="text-align:right">{G.money(x["amount"])}</td></tr>' for x in fee.get("lines", []))
    lift = f'<tr><td colspan="3">Phí nâng hạ</td><td style="text-align:right">{G.money(fee["lift"])}</td></tr>' if fee.get("lift") else ""
    maker = _uname(db, p["out_by"]) or "—"
    staffimg = f'<img src="/voucher/{p["id"]}/sig/staff" alt="Chữ ký người lập phiếu">' if p["staff_sig"] else '<div style="height:50px"></div>'
    if p["cust_confirmed_at"]:
        who = (_uname(db, p["cust_confirmed_by"]) if p["cust_mode"] == "self" else (p["owner_name"] or (cust["full_name"] if cust else "Khách hàng")))
        inner = f'<img src="/voucher/{p["id"]}/sig/cust" alt="Chữ ký khách hàng">' if p["cust_sig"] else '<div class="stamp">ĐÃ XÁC NHẬN</div>'
        sub = f'{E(who)}<br><span class="mute">{E(A.fmt_ts(p["cust_confirmed_at"]))}' + (f' · ghi nhận tại quầy bởi {E(_uname(db, p["cust_confirmed_by"]))}' if p["cust_mode"] == "counter" else "") + "</span>"
    elif total == 0: inner, sub = '<div class="mute" style="height:60px">(không phát sinh tiền bãi, không cần xác nhận)</div>', '<span class="mute">Khách hàng / người trả tiền</span>'
    else: inner, sub = '<div class="mute" style="height:60px">(chưa xác nhận)</div>', '<span class="mute">Khách hàng / người trả tiền</span>'
    paidline = (f'Bãi đã nhận tiền lúc {E(A.fmt_ts(p["paid_at"]))} ({E(G.PAY_METHODS.get(p["pay_method"], ""))}{", mã " + E(p["pay_ref"]) if p["pay_ref"] else ""}) · người nhận: {E(_uname(db, p["paid_by"]))}' if p["fee_paid"] and total > 0 else ("Không phát sinh tiền bãi (miễn phí theo bảng giá)." if total == 0 else "Bãi chưa ghi nhận đã nhận tiền"))
    dueinfo = ""
    if total > 0 and not G.is_done(p):
        due = G.due_of(p)
        dueinfo = (f'<p><b>Hạn thanh toán:</b> {E(time.strftime("%d/%m/%Y", time.localtime(due)))} · <b data-until="{int(due)}">…</b>'
                   + (f' <span class="mute">(đã gia hạn: {E(p["due_ext_reason"])})</span>' if p["due_ext_by"] else "") + "</p>")
    doc = (f'<div class="voucher"><h1>PHIẾU THANH TOÁN LƯU BÃI</h1><div class="sub">{E(D.get_setting(db, "yard_name"))} · Số {E(G.voucher_no(p))} · Phiếu ra/vào {E(p["pass_no"])}</div>'
           + kv([("Số container", f'<b class="mono">{E(p["container_no"])}</b> ({E(p["size"])} feet)'), ("Biển số xe", f'<b>{E(p["truck_plate"])}</b>'), ("Chủ xe / tài xế", E(" · ".join(x for x in (p["owner_name"], p["owner_phone"]) if x))),
                  ("Khách hàng", E(cust["full_name"] + (" · " + cust["company"] if cust["company"] else "")) if cust else ""), ("Thời gian vào bãi", E(A.fmt_ts(p["in_at"]))), ("Thời gian ra bãi", E(A.fmt_ts(p["out_at"]))),
                  ("Thời gian ở bãi", f'{E(G.dur_text(p["out_at"] - p["in_at"]))} ({E(fee_note(fee))})'), ("Bên trả phí", E(G.FEE_PARTIES.get(p["fee_party"], "")))])
           + f'<div class="wrap" style="margin-top:12px"><table><tr><th>Bậc giá</th><th>Số lượng</th><th>Đơn giá</th><th style="text-align:right">Thành tiền</th></tr>{ln}{lift}'
           + f'<tr><td colspan="3"><b>TỔNG CỘNG</b></td><td style="text-align:right"><b class="big">{G.money(total)}</b></td></tr></table></div>'
           + f'<p style="margin-top:10px"><b>Tình trạng:</b> {E(state)}<br><span class="mute">{paidline}</span></p>{dueinfo}'
           + f'<div class="sigrow"><div class="sigbox">{staffimg}<div>{E(maker)}</div><div class="mute">{E(A.fmt_ts(p["out_at"]))}</div><div class="sigttl">Người lập phiếu (ký, ghi rõ họ tên)</div></div>'
           + f'<div class="sigbox">{inner}<div>{sub}</div><div class="sigttl">Khách hàng xác nhận đã thanh toán</div></div></div></div>')
    acts = []
    if total > 0:
        if u["role"] in G.OPS and not p["fee_paid"]:
            acts.append(f'<form method="post" action="/voucher/{p["id"]}/receive" class="row2" style="grid-template-columns:1fr 1fr auto;align-items:end">{csrf_in(h)}<div><label for="pm">Hình thức nhận tiền</label><select id="pm" name="method">{opts({"cash": "Tiền mặt", "transfer": "Chuyển khoản", "other": "Khác"}, "cash")}</select></div>'
                        '<div><label for="pr">Mã tham chiếu (nếu có)</label><input id="pr" name="ref" maxlength="60"></div><div><button class="green">Bãi đã nhận tiền</button></div></form>')
        if u["role"] in G.OPS and not p["cust_confirmed_at"]:
            acts.append(f'<form method="post" action="/voucher/{p["id"]}/counter">{csrf_in(h)}<p class="mute">Khách không có tài khoản hoặc xác nhận trực tiếp tại quầy: đóng dấu đỏ ĐÃ XÁC NHẬN vào chỗ ký tên của khách.</p><button class="gray">Khách xác nhận tại quầy</button></form>')
        if u["role"] == "customer" and p["customer_id"] == u["id"] and not p["cust_confirmed_at"]:
            note = ("Chữ ký bạn đã tải sẽ được in vào phiếu." if G.has_sig(u["id"]) else 'Bạn chưa tải ảnh chữ ký nên phiếu sẽ đóng dấu đỏ ĐÃ XÁC NHẬN. <a href="/profile/signature">Tải chữ ký</a>')
            acts.append(f'<form method="post" action="/voucher/{p["id"]}/confirm">{csrf_in(h)}<p class="mute">{note}</p><button class="big2 green">Tôi xác nhận đã thanh toán</button></form>')
    if total > 0 and not G.is_done(p) and u["role"] == "admin":
        acts.append(f'<form method="post" action="/debts/extend" class="row2" style="grid-template-columns:1fr 2fr auto;align-items:end">{csrf_in(h)}<input type="hidden" name="ids" value="{p["id"]}"><div><label for="xd">Gia hạn thêm (ngày)</label><input id="xd" name="days" type="number" min="1" max="365" value="15"></div>'
                    '<div><label for="xr">Lý do gia hạn (bắt buộc)</label><input id="xr" name="reason" maxlength="200"></div><div><button class="gray">Gia hạn</button></div></form>')
    h.send(200, A.page(G.voucher_no(p), f'{flash(h)}<div class="noprint" style="max-width:860px;margin:0 auto 12px"><a href="/vouchers">◂ Danh sách phiếu thanh toán</a> · <a href="/pass/{p["id"]}">Phiếu ra/vào</a> · In: nhấn Ctrl+P</div>{doc}'
        + (f'<div class="box noprint" style="max-width:860px;margin:0 auto">' + "<hr>".join(acts) + "</div>" if acts else ""), h, "/vouchers"))

def _vact(h, pid, fn, msg):
    f = h.form()
    if not A.need_login(h) or not A.csrf_ok(h, f): return
    p = h.db.execute("SELECT * FROM gate_passes WHERE id=?", (int(pid),)).fetchone()
    if p is None or not G.can_view(h.user, p): return h.send(404, A.page("Không tìm thấy", '<div class="box"><h2>Không có phiếu</h2></div>', h))
    errs = fn(f, p)
    if errs: return h.send(409, A.page("Không thực hiện được", f'<div class="box">{A.errbox(errs)}<a href="/voucher/{p["id"]}">Quay lại</a></div>', h))
    h.redirect(f"/voucher/{p['id']}?m={msg}")

def voucher_receive(h, pid):
    if not ops(h): return
    _vact(h, pid, lambda f, p: G.receive_payment(h.db, h.user, p["id"], f.get("method", ""), f.get("ref", "")), "recv")

def voucher_confirm(h, pid):
    _vact(h, pid, lambda f, p: G.cust_confirm(h.db, h.user, p["id"], counter=False), "conf")

def voucher_counter(h, pid):
    if not ops(h): return
    _vact(h, pid, lambda f, p: G.cust_confirm(h.db, h.user, p["id"], counter=True), "conf")

def voucher_sig(h, pid, who):
    if not A.need_login(h): return
    p = get_pass(h, pid)
    if p is None: return
    rel = p["staff_sig" if who == "staff" else "cust_sig"]; path = (G.SIG_DIR / rel).resolve() if rel else None
    if not path or G.SIG_DIR.resolve() not in path.parents or not path.exists(): return h.send(404, "")
    h.send_bytes(200, path.read_bytes(), "image/png")

# ---------------------------------------------------------------- chữ ký của tôi
def sig_page(h, errs=()):
    if not A.need_login(h): return
    u = h.user; has = G.has_sig(u["id"])
    use = ("Chữ ký này được in vào <b>phiếu thanh toán</b> ở ô “Khách hàng xác nhận đã thanh toán” khi bạn bấm xác nhận. Không có chữ ký thì phiếu đóng dấu đỏ <b>ĐÃ XÁC NHẬN</b>." if u["role"] == "customer"
           else "Chữ ký này được in vào ô “Người lập phiếu” trên phiếu thanh toán do bạn xác nhận cho xe ra. Không có chữ ký thì phiếu chỉ in họ tên.")
    h.send(200, A.page("Chữ ký", f'{flash(h)}<div class="box" style="max-width:640px"><h2>Chữ ký của tôi</h2><p class="mute">{use}</p>{A.errbox(errs)}'
        f'<div class="sigprev">' + (f'<img src="/signature/me?v={int(time.time())}" alt="Chữ ký hiện tại">' if has else '<span class="mute">Chưa có chữ ký</span>') + '</div>'
        f'<form method="post" action="/profile/signature" enctype="multipart/form-data">{csrf_in(h)}<label for="sg">Tải ảnh chữ ký (PNG hoặc JPG, tối đa 1,5 MB)</label><input id="sg" type="file" name="sig" accept="image/png,image/jpeg" required>'
        '<p class="mute">Ký bút mực đậm trên giấy trắng, chụp thẳng và đủ sáng. Hệ thống tự bỏ nền trắng và cắt sát nét ký.</p><button class="full">Lưu chữ ký</button></form>'
        + (f'<form method="post" action="/profile/signature/delete" style="margin-top:10px">{csrf_in(h)}<button class="red">Xoá chữ ký</button></form>' if has else "") + '<p class="mute">Phiếu đã xác nhận trước đây giữ nguyên chữ ký lúc đó, đổi chữ ký không làm đổi phiếu cũ.</p></div>', h, "/profile/signature"))

def sig_upload(h):
    if not A.need_login(h): return
    f, files = h.multipart(cap=3 * 1024 * 1024)
    if not A.csrf_ok(h, f): return
    fn, data = files.get("sig", ("", b""))
    if not data: return sig_page(h, ["Chọn một ảnh chữ ký."])
    ok, err = G.save_signature(h.user["id"], data)
    if not ok: return sig_page(h, [err])
    D.audit(h.db, h.user["id"], "signature_set", "", h.ip()); h.redirect("/profile/signature?m=sig")

def sig_delete(h):
    f = h.form()
    if not A.need_login(h) or not A.csrf_ok(h, f): return
    G.delete_signature(h.user["id"]); D.audit(h.db, h.user["id"], "signature_del", "", h.ip()); h.redirect("/profile/signature?m=sigdel")

def sig_me(h):
    if not A.need_login(h): return
    p = G.sig_file(h.user["id"])
    if not p.exists(): return h.send(404, "")
    h.send_bytes(200, p.read_bytes(), "image/png")


# ---------------------------------------------------------------- công nợ và thanh toán gộp
def debts(h):
    if not A.need_login(h): return
    q, u = h.q, h.user; is_staff = u["role"] in G.STAFF; now = time.time(); wd = int(D.get_setting(h.db, "warn_days", "15") or 15)
    rows = G.debts(h.db, u, cust=q.get("c", "") if is_staff else "", q=q.get("q", ""), urgent=q.get("urgent") == "1", warn_days=wd)
    names = {r["id"]: r["full_name"] for r in h.db.execute("SELECT id, full_name FROM users WHERE role='customer'")}
    def cls(r):
        left = G.due_of(r) - now
        return "od" if left < 0 else ("warnrow" if left <= wd * 86400 else "")
    tb = "".join(f'<tr class="{cls(r)}"><td><input type="checkbox" name="ids" value="{r["id"]}" aria-label="Chọn phiếu {E(G.voucher_no(r))}"></td><td><a href="/voucher/{r["id"]}"><b>{E(G.voucher_no(r))}</b></a></td><td class="mono">{E(r["container_no"])}</td>'
                 f'<td>{E(names.get(r["customer_id"], "Khách vãng lai") if r["customer_id"] else "Khách vãng lai")}</td><td>{E(A.fmt_ts(r["out_at"]))}</td><td><b>{G.money(r["fee_total"])}</b></td><td>{E(time.strftime("%d/%m/%Y", time.localtime(G.due_of(r))))}</td>'
                 f'<td><b data-until="{int(G.due_of(r))}">…</b></td><td>{E(G.voucher_state(r)[0])}</td></tr>' for r in rows)
    total = sum(r["fee_total"] or 0 for r in rows); late = sum(1 for r in rows if G.due_of(r) < now)
    csel = ""
    if is_staff:
        cs = {"": "Tất cả khách", "walkin": "Khách vãng lai", **{str(i): n for i, n in names.items()}}
        csel = f'<form method="get" action="/debts" class="row2" style="grid-template-columns:2fr 2fr auto auto;align-items:end"><div><label for="q">Số phiếu / container / biển số</label><input id="q" name="q" value="{E(q.get("q", ""))}"></div><div><label for="c">Khách</label><select id="c" name="c">{opts(cs, q.get("c", ""))}</select></div><label style="margin:0;font-weight:400"><input type="checkbox" name="urgent" value="1"{" checked" if q.get("urgent") == "1" else ""}> chỉ phiếu sắp/đã quá hạn</label><div><button>Lọc</button></div></form>'
    else: csel = f'<p class="mute">Các phiếu thanh toán của bạn chưa đủ 2 xác nhận. Chọn nhiều phiếu để xác nhận một lần. Bãi sẽ đối chiếu tiền nhận được.</p>'
    acts = ""
    if u["role"] == "customer": acts = '<button formaction="/debts/confirm" class="green">Tôi xác nhận đã thanh toán các phiếu đã chọn</button>'
    if u["role"] == "gate":
        acts = (f'<div class="row2" style="grid-template-columns:1fr 2fr;align-items:end"><div><label for="pm">Hình thức nhận tiền</label><select id="pm" name="method">{opts({"cash": "Tiền mặt", "transfer": "Chuyển khoản", "other": "Khác"}, "transfer")}</select></div>'
                '<div><label for="pr">Mã tham chiếu chung (nếu có)</label><input id="pr" name="ref" maxlength="60"></div></div>'
                '<div class="btnrow"><button formaction="/debts/receive" class="green">Bãi đã nhận tiền (các phiếu đã chọn)</button><button formaction="/debts/counter" class="gray">Khách xác nhận tại quầy (đóng dấu đỏ)</button></div>')
    if u["role"] == "admin":
        acts = ('<p class="mute">Admin boss chỉ xem và gia hạn. Nhận tiền và xác nhận tại quầy do Quản trị cổng làm.</p><div class="row2" style="grid-template-columns:1fr 2fr auto;align-items:end"><div><label for="xd">Gia hạn thêm (ngày)</label><input id="xd" name="days" type="number" min="1" max="365" value="15"></div>'
                '<div><label for="xr">Lý do gia hạn (bắt buộc)</label><input id="xr" name="reason" maxlength="200"></div><div><button formaction="/debts/extend" class="gray">Gia hạn các phiếu đã chọn</button></div></div>')
    h.send(200, A.page("Công nợ", f'{flash(h)}<div class="box"><h2>Công nợ: {len(rows)} phiếu · tổng {G.money(total)}' + (f' · <span style="color:#b3321f">{late} quá hạn</span>' if late else "") + f'</h2>{csel}</div>'
        f'<div class="box"><form method="post" action="/debts/confirm">{csrf_in(h)}<div class="wrap"><table><tr><th><input type="checkbox" data-checkall="ids" aria-label="Chọn tất cả"></th><th>Phiếu TT</th><th>Container</th><th>Khách</th><th>Giờ ra</th><th>Số tiền</th><th>Hạn</th><th>Còn lại</th><th>Tình trạng</th></tr>'
        + (tb or '<tr><td colspan="9" class="mute">Không có phiếu nào cần thanh toán.</td></tr>') + f'</table></div><div class="noprint" style="margin-top:14px">{acts if rows else ""}</div></form>'
        '<p class="mute">Màu cam: còn dưới số ngày cảnh báo. Màu đỏ: đã quá hạn.</p></div>', h, "/debts"))

def _bulk_done(h, ok, errs, what):
    msg = f'<div class="okm">Đã {E(what)} cho {ok} phiếu.</div>' if ok else ""
    h.send(200 if ok else 409, A.page("Kết quả", f'<div class="box">{msg}' + (A.errbox(errs[:8]) if errs else "") + '<a href="/debts">Quay lại công nợ</a></div>', h, "/debts"))

def debts_confirm(h):
    f = h.form()
    if not A.need_login(h) or not A.csrf_ok(h, f): return
    ok, errs = G.bulk(h.db, h.user, h._lists.get("ids", []), lambda i: G.cust_confirm(h.db, h.user, i, counter=False)); _bulk_done(h, ok, errs, "ghi nhận xác nhận thanh toán")

def debts_receive(h):
    f = h.form()
    if not ops(h) or not A.csrf_ok(h, f): return
    ok, errs = G.bulk(h.db, h.user, h._lists.get("ids", []), lambda i: G.receive_payment(h.db, h.user, i, f.get("method", ""), f.get("ref", ""))); _bulk_done(h, ok, errs, "ghi nhận bãi đã nhận tiền")

def debts_counter(h):
    f = h.form()
    if not ops(h) or not A.csrf_ok(h, f): return
    ok, errs = G.bulk(h.db, h.user, h._lists.get("ids", []), lambda i: G.cust_confirm(h.db, h.user, i, counter=True)); _bulk_done(h, ok, errs, "ghi nhận khách xác nhận tại quầy")

def debts_extend(h):
    f = h.form()
    if not A.need_role(h, "admin") or not A.csrf_ok(h, f): return
    try: days = int(f.get("days", ""))
    except ValueError: days = 0
    errs = G.extend_due(h.db, h.user, h._lists.get("ids", []), days, f.get("reason", ""))
    if errs: return h.send(409, A.page("Không gia hạn được", f'<div class="box">{A.errbox(errs)}<a href="/debts">Quay lại công nợ</a></div>', h, "/debts"))
    h.redirect("/debts?m=saved")

def exceptions(h):
    if not A.need_role(h, "admin"): return
    rows = h.db.execute("SELECT e.*, p.pass_no, p.container_no, u.full_name AS who FROM gate_events e JOIN gate_passes p ON p.id=e.pass_id LEFT JOIN users u ON u.id=e.confirmed_by WHERE e.manual_override=1 ORDER BY e.id DESC LIMIT 200").fetchall()
    tb = "".join(f'<tr><td>{E(A.fmt_ts(r["ts"]))}</td><td><a href="/pass/{r["pass_id"]}">{E(r["pass_no"])}</a></td><td class="mono">{E(r["container_no"])}</td><td>{"VÀO" if r["direction"] == "in" else "RA"}</td><td>{E(r["note"])}</td><td>{E(r["who"] or "")}</td></tr>' for r in rows)
    h.send(200, A.page("Ngoại lệ cổng", f'<div class="box"><h2>Ngoại lệ cổng ({len(rows)})</h2><p class="mute">Các lần cho ra dù lệch, hoặc xác nhận mã sai số kiểm tra. Quản trị cổng bắt buộc ghi lý do; đây là chỗ chủ kiểm tra.</p><div class="wrap"><table><tr><th>Lúc</th><th>Phiếu</th><th>Container</th><th>Cổng</th><th>Nội dung</th><th>Người thao tác</th></tr>'
        + (tb or '<tr><td colspan="6" class="mute">Chưa có ngoại lệ nào.</td></tr>') + "</table></div></div>", h, "/admin/exceptions"))
