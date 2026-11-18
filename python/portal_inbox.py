"""
Hộp thư (4 loại). Nguyên tắc: thư THANH TOÁN, NHẮC NHỞ và VI PHẠM được TÍNH THẲNG từ trạng thái phiếu mỗi lần mở, KHÔNG lưu cờ riêng.
Vì vậy "chưa thanh toán" chỉ chuyển thành "đã thanh toán" khi phiếu thật sự đủ 2 xác nhận (bãi đã nhận tiền VÀ khách đã xác nhận), không thể lệch.
Riêng thư HỆ THỐNG (xe vào/ra) là bản ghi riêng, tự xoá sau sysmsg_days ngày (mặc định 5).
  1. Thanh toán : chưa đủ 2 xác nhận -> nằm đó đến khi đủ; đủ rồi -> còn paid_letter_days ngày (mặc định 30) rồi biến mất.
  2. Hệ thống   : xe của khách vào/ra, theo thời gian thực, giữ 5 ngày.
  3. Nhắc nhở   : phiếu còn <= warn_days ngày tới hạn (hoặc quá hạn) mà chưa xong. KHÔNG tự xoá theo thời gian, chỉ biến mất khi phiếu đủ xác nhận.
                  Khách: chưa đủ 2 xác nhận. Nhân viên/Admin boss: khách CHƯA XÁC NHẬN.
  4. Vi phạm    : sẽ do trang Vi phạm cấp (bước A3).
"""
import time
import portal_db as D, portal_gate as G

def _set(db, key, default):
    try: return int(D.get_setting(db, key, str(default)) or default)
    except ValueError: return default

def done_at(p): return max(p["paid_at"] or 0, p["cust_confirmed_at"] or 0)

def purge(db, now=None):
    """Xoá thật các thư hệ thống quá hạn giữ. Các loại còn lại không có bản ghi để xoá."""
    now = now or time.time(); db.execute("DELETE FROM system_msgs WHERE created_at < ?", (now - _set(db, "sysmsg_days", 5) * 86400,)); db.commit()

def payment_letters(db, user, now=None):
    if user["role"] != "customer": return []
    now = now or time.time(); keep = _set(db, "paid_letter_days", 30) * 86400; out = []
    for p in db.execute("SELECT * FROM gate_passes WHERE customer_id=? AND status='closed' AND COALESCE(fee_total,0)>0 ORDER BY out_at DESC", (user["id"],)):
        if G.is_done(p):
            d = done_at(p)
            if now - d <= keep: out.append({"p": p, "state": "paid", "missing": [], "expires": d + keep})
        else:
            miss = (["Bạn chưa xác nhận đã thanh toán"] if not p["cust_confirmed_at"] else []) + (["Bãi chưa ghi nhận đã nhận tiền"] if not p["fee_paid"] else [])
            out.append({"p": p, "state": "unpaid", "missing": miss, "expires": None})
    out.sort(key=lambda x: (x["state"] != "unpaid", G.due_of(x["p"]) if x["state"] == "unpaid" else -done_at(x["p"])))
    return out

def reminders(db, user, now=None):
    now = now or time.time(); wd = _set(db, "warn_days", 15) * 86400
    if user["role"] == "customer": rows = [p for p in db.execute("SELECT * FROM gate_passes WHERE customer_id=? AND status='closed' AND COALESCE(fee_total,0)>0", (user["id"],)) if not G.is_done(p)]
    elif user["role"] in G.STAFF: rows = list(db.execute("SELECT * FROM gate_passes WHERE status='closed' AND COALESCE(fee_total,0)>0 AND cust_confirmed_at IS NULL"))
    else: rows = []
    return sorted((p for p in rows if G.due_of(p) - now <= wd), key=G.due_of)

def system_letters(db, user, now=None):
    if user["role"] != "customer": return []
    now = now or time.time()
    return list(db.execute("SELECT * FROM system_msgs WHERE user_id=? AND created_at>=? ORDER BY id DESC", (user["id"], now - _set(db, "sysmsg_days", 5) * 86400)))

def violation_letters(db, user): return []      # bước A3

def counts(db, user, now=None):
    now = now or time.time(); pay = payment_letters(db, user, now); sysl = system_letters(db, user, now)
    return {"pay_unpaid": sum(1 for x in pay if x["state"] == "unpaid"), "pay_paid": sum(1 for x in pay if x["state"] == "paid"), "sys_total": len(sysl),
            "sys_unread": sum(1 for m in sysl if m["read_at"] is None), "remind": len(reminders(db, user, now)), "viol": len(violation_letters(db, user))}

def badge(db, user, now=None):
    """Con số đỏ trên menu: khách = thư thanh toán chưa xong + thư hệ thống chưa đọc; nhân viên = phiếu khách chưa xác nhận sắp/đã hạn."""
    c = counts(db, user, now); return c["pay_unpaid"] + c["sys_unread"] if user["role"] == "customer" else c["remind"]

def mark_sys_read(db, user, now=None):
    now = now or time.time(); db.execute("UPDATE system_msgs SET read_at=? WHERE user_id=? AND read_at IS NULL", (now, user["id"])); db.commit()

# ---------------------------------------------------------------- giao diện
INBOX_CSS = """.badge{background:#c0392b;color:#fff;border-radius:10px;padding:0 7px;font-size:12px;font-weight:700;margin-left:4px;display:inline-block;min-width:18px;text-align:center}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.tabs a{padding:8px 14px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);text-decoration:none;font-weight:600}.tabs a.on{background:var(--blue);color:#fff;border-color:var(--blue)}.tabs a.on .badge{background:#fff;color:#c0392b}
.letter{background:#fff;border:1px solid var(--line);border-left:5px solid #9aa9b4;border-radius:6px;padding:12px 14px;margin-bottom:10px}.letter.unpaid{border-left-color:#c0392b}.letter.paid{border-left-color:#1e7a3c}.letter.remind{border-left-color:#d98c00}.letter.overdue{border-left-color:#7a1f14;background:#fdf3f1}.letter.sys{border-left-color:#2457a6}
.letter .lt{font-size:15px}.letter .lb{color:var(--mute);margin:4px 0}.letter .lc{font-size:13px;color:var(--ink)}.letter .new{display:inline-block;width:9px;height:9px;border-radius:50%;background:#2457a6;margin-right:6px}.dayhead{font-weight:700;color:var(--mute);margin:16px 0 6px}"""
V = None

def install(views):
    global V
    V = views; views.A.g["CSS"] += INBOX_CSS; views.A.ROUTES[("GET", "/inbox")] = inbox

def _vn_date(ts): return time.strftime("%d/%m/%Y", time.localtime(ts))

def _pay_card(x):
    E = V.E; p = x["p"]; unpaid = x["state"] == "unpaid"
    head = '<b>%s</b> · <span class="mono">%s</span> · <b>%s</b> <span class="tag %s">%s</span>' % (E(G.voucher_no(p)), E(p["container_no"]), G.money(p["fee_total"]), "pending" if unpaid else "active", "Chưa thanh toán" if unpaid else "Đã thanh toán")
    line = "Xe %s, ra bãi %s." % (E(p["truck_plate"]), E(V.A.fmt_ts(p["out_at"])))
    if unpaid: line += ' Hạn thanh toán %s (<b data-until="%d">…</b>).' % (_vn_date(G.due_of(p)), int(G.due_of(p)))
    marks = "Khách xác nhận: %s · Bãi nhận tiền: %s" % ("✔" if p["cust_confirmed_at"] else "✘", "✔" if p["fee_paid"] else "✘")
    tail = ("Còn thiếu: " + "; ".join(E(m) for m in x["missing"]) + ".") if unpaid else "Thư này tự xoá sau %s." % _vn_date(x["expires"])
    return '<div class="letter %s"><div class="lt">%s</div><div class="lb">%s</div><div class="lc">%s · %s</div><div style="margin-top:8px"><a class="btn sm" href="/voucher/%d">Mở phiếu thanh toán</a></div></div>' % (x["state"], head, line, marks, tail, p["id"])

def _remind_card(p, now, staff, names):
    E = V.E; left = G.due_of(p) - now; late = left < 0
    who = (names.get(p["customer_id"]) or "Khách vãng lai") if staff else ""
    title = ("Cần xác nhận phiếu thanh toán" + (" · " + E(who) if who else "")) if staff else "Đến hạn xác nhận và thanh toán"
    need = "khách CHƯA XÁC NHẬN" if staff else ("bạn chưa xác nhận" if not p["cust_confirmed_at"] else "") + (" và " if (not p["cust_confirmed_at"] and not p["fee_paid"]) else "") + ("bãi chưa ghi nhận nhận tiền" if not p["fee_paid"] else "")
    return ('<div class="letter remind%s"><div class="lt"><b>%s</b></div><div class="lb"><b>%s</b> · <span class="mono">%s</span> · %s · hạn %s (<b data-until="%d">…</b>) · %s.</div>'
            '<div style="margin-top:8px"><a class="btn sm" href="/voucher/%d">Mở phiếu thanh toán</a></div></div>') % (" overdue" if late else "", title, E(G.voucher_no(p)), E(p["container_no"]), G.money(p["fee_total"]), _vn_date(G.due_of(p)), int(G.due_of(p)), E(need), p["id"])

def inbox(h):
    A, E = V.A, V.E
    if not A.need_login(h): return
    db, u = h.db, h.user; now = time.time(); purge(db, now); c = counts(db, u, now); cust = u["role"] == "customer"
    tabs = ([("pay", "Thanh toán", c["pay_unpaid"]), ("sys", "Hệ thống", c["sys_unread"]), ("remind", "Nhắc nhở", c["remind"]), ("viol", "Vi phạm", c["viol"])] if cust else [("remind", "Nhắc nhở xác nhận", c["remind"])])
    tab = h.q.get("tab", "")
    if tab not in [t[0] for t in tabs]: tab = ("pay" if c["pay_unpaid"] else "sys" if c["sys_unread"] else "remind" if c["remind"] else "pay") if cust else "remind"
    head = '<div class="tabs">' + "".join('<a href="/inbox?tab=%s" class="%s">%s%s</a>' % (k, "on" if k == tab else "", E(lbl), (' <span class="badge">%d</span>' % n) if n else "") for k, lbl, n in tabs) + "</div>"
    wd = _set(db, "warn_days", 15)
    if tab == "pay":
        items = payment_letters(db, u, now); note = ('<p class="mute">Thư <b>chưa thanh toán</b> nằm đây đến khi phiếu đủ <b>2 xác nhận</b> (bãi đã nhận tiền và bạn đã xác nhận). Đủ rồi thì chuyển thành <b>đã thanh toán</b> và tự xoá sau %d ngày.</p>' % _set(db, "paid_letter_days", 30))
        body = "".join(_pay_card(x) for x in items) or '<p class="mute">Chưa có thư thanh toán nào.</p>'
    elif tab == "sys":
        items = system_letters(db, u, now); groups = {}
        for m in items: groups.setdefault(time.strftime("%Y-%m-%d", time.localtime(m["created_at"])), []).append(m)
        today, yest = time.strftime("%Y-%m-%d", time.localtime(now)), time.strftime("%Y-%m-%d", time.localtime(now - 86400)); parts = []
        for day, ms in groups.items():
            label = "Hôm nay" if day == today else ("Hôm qua" if day == yest else _vn_date(time.mktime(time.strptime(day, "%Y-%m-%d"))))
            parts.append('<div class="dayhead">%s</div>' % label + "".join('<div class="letter sys"><div class="lt">%s<b>%s</b> · %s</div><div class="lb">%s</div><div><a href="/pass/%d">Xem phiếu</a></div></div>' % ('<span class="new" title="Chưa đọc"></span>' if m["read_at"] is None else "", E(m["title"]), time.strftime("%H:%M", time.localtime(m["created_at"])), E(m["body"]), m["pass_id"]) for m in ms))
        body = "".join(parts) or '<p class="mute">Chưa có thư hệ thống trong %d ngày gần đây.</p>' % _set(db, "sysmsg_days", 5)
        note = '<p class="mute">Thông báo xe của bạn vào/ra theo thời gian thực. Thư tự xoá sau %d ngày. Xem toàn cảnh ở trang <a href="/timeline">Dòng thời gian</a>. Trang tự làm mới mỗi 30 giây.</p>' % _set(db, "sysmsg_days", 5)
        mark_sys_read(db, u, now)
    elif tab == "remind":
        names = {r["id"]: r["full_name"] for r in db.execute("SELECT id, full_name FROM users WHERE role='customer'")}; items = reminders(db, u, now)
        note = ('<p class="mute">%s Thư nhắc nhở <b>không tự xoá theo thời gian</b>: chỉ biến mất khi phiếu đã đủ xác nhận. Hiện khi còn dưới %d ngày tới hạn hoặc đã quá hạn.</p>' % ("Các phiếu khách CHƯA XÁC NHẬN thanh toán." if not cust else "Các phiếu của bạn sắp hoặc đã quá hạn xác nhận và thanh toán.", wd))
        body = "".join(_remind_card(p, now, not cust, names) for p in items) or '<p class="mute">Không có phiếu nào cần nhắc.</p>'
    else:
        note = '<p class="mute">Thông báo vi phạm do bãi lập.</p>'; body = '<p class="mute">Chưa có thư vi phạm nào.</p>'
    h.send(200, A.page("Hộp thư", '<div class="box"><h2>Hộp thư</h2>%s%s%s</div>' % (head, note, body), h, "/inbox", refresh=30))
