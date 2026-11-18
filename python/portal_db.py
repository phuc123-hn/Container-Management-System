"""
Cơ sở dữ liệu + tài khoản cho cổng SmartPort (bước 1). Chỉ dùng thư viện có sẵn của Python.

- SQLite, file mặc định: data/smartport.db (đổi bằng biến môi trường SMARTPORT_DB).
- Mật khẩu băm bằng scrypt (hashlib), không bao giờ lưu mật khẩu gốc.
- Phiên đăng nhập: token ngẫu nhiên, trong DB chỉ lưu bản băm SHA-256 của token.
- Khoá tạm tài khoản sau nhiều lần sai mật khẩu.
Các bảng orders / gate_passes / gate_events / documents đã tạo sẵn cho bước 2 (cổng vào/ra), bước 1 chưa dùng.
"""
import hashlib, hmac, os, re, secrets, sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROLES = {"admin": "Admin boss (chủ)", "gate": "Quản trị cổng", "customer": "Khách hàng"}   # 'dispatcher' cũ đã gộp vào 'gate'
PAY_TERMS = {"prepaid": "Trả trước tại cổng", "credit": "Công nợ (trả sau)"}
STATUSES = {"pending": "Chờ duyệt", "active": "Đang hoạt động", "disabled": "Đã khoá"}
SESSION_SECONDS = 8 * 3600
MAX_FAILS, LOCK_SECONDS = 5, 300
_N, _R, _P, _MAXMEM = 2 ** 14, 8, 1, 128 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  full_name TEXT NOT NULL, email TEXT, company TEXT,
  pw_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'customer' CHECK(role IN ('admin','dispatcher','gate','customer')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','disabled')),
  fails INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, last_login REAL);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT NOT NULL UNIQUE,
  customer_id INTEGER REFERENCES users(id), kind TEXT NOT NULL CHECK(kind IN ('in','out')),
  container_no TEXT NOT NULL, truck_plate TEXT, note TEXT,
  status TEXT NOT NULL DEFAULT 'open', created_by INTEGER REFERENCES users(id), created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS gate_passes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, pass_no TEXT NOT NULL UNIQUE,
  order_id INTEGER REFERENCES orders(id), customer_id INTEGER REFERENCES users(id),
  container_no TEXT NOT NULL, truck_plate TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','inside','closed','rejected')),
  in_at REAL, out_at REAL, created_by INTEGER REFERENCES users(id), created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_pass_cont ON gate_passes(container_no, status);
CREATE TABLE IF NOT EXISTS gate_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, pass_id INTEGER REFERENCES gate_passes(id),
  direction TEXT NOT NULL CHECK(direction IN ('in','out')), ts REAL NOT NULL,
  container_read TEXT, votes INTEGER, of_frames INTEGER, conf REAL,
  image_path TEXT, run_id TEXT, confirmed_by INTEGER REFERENCES users(id),
  manual_override INTEGER NOT NULL DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT, pass_id INTEGER NOT NULL REFERENCES gate_passes(id),
  doc_type TEXT NOT NULL, doc_no TEXT, created_at REAL NOT NULL, created_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tariff_tiers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, size TEXT NOT NULL CHECK(size IN ('20','40','45','all')),
  day_from INTEGER NOT NULL CHECK(day_from>=1), day_to INTEGER, rate INTEGER NOT NULL CHECK(rate>=0), hour_rate INTEGER);
CREATE TABLE IF NOT EXISTS system_msgs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  pass_id INTEGER REFERENCES gate_passes(id), kind TEXT NOT NULL CHECK(kind IN ('in','out')),
  title TEXT NOT NULL, body TEXT NOT NULL, created_at REAL NOT NULL, read_at REAL);
CREATE INDEX IF NOT EXISTS ix_sysmsg_user ON system_msgs(user_id, created_at);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, user_id INTEGER,
  action TEXT NOT NULL, detail TEXT, ip TEXT);
"""

def db_path(): return Path(os.environ.get("SMARTPORT_DB") or ROOT / "data" / "smartport.db")

# cột bổ sung cho gate_passes (thêm bằng ALTER nên chạy được cả trên CSDL cũ của bước 1)
PASS_COLS = {"mode": "TEXT NOT NULL DEFAULT 'manual'", "token": "TEXT", "size": "TEXT NOT NULL DEFAULT '40'", "iso_type": "TEXT", "plate_key": "TEXT",
             "owner_name": "TEXT", "owner_phone": "TEXT", "fee_party": "TEXT NOT NULL DEFAULT 'chu_xe'", "fee_total": "INTEGER", "fee_detail": "TEXT",
             "fee_paid": "INTEGER NOT NULL DEFAULT 0", "in_by": "INTEGER", "out_by": "INTEGER", "note": "TEXT", "in_image": "TEXT", "out_image": "TEXT", "cancel_reason": "TEXT",
             "plate_image": "TEXT", "paid_at": "REAL", "paid_by": "INTEGER", "pay_method": "TEXT", "pay_ref": "TEXT",
             "due_at": "REAL", "due_ext_by": "INTEGER", "due_ext_reason": "TEXT", "cust_confirmed_at": "REAL", "cust_confirmed_by": "INTEGER", "cust_mode": "TEXT", "cust_sig": "TEXT", "staff_sig": "TEXT"}
# Bảng giá MẶC ĐỊNH CHỈ ĐỂ DEMO (số tạm). Sửa ở trang "Bảng giá & mô hình" theo biểu giá thật của bãi.
DEFAULT_TIERS = {"20": (0, 40000, 80000), "40": (0, 70000, 140000), "45": (0, 80000, 160000)}
DEFAULT_SETTINGS = {"model_path": "result\\train_container\\yolo26n\\weights\\best.pt", "imgsz": "960", "conf": "0.25",
                    "hour_round": "up", "warn_days": "15", "bubble_seconds": "5", "paid_letter_days": "30", "sysmsg_days": "5", "lift_fee_20": "0", "lift_fee_40": "0", "lift_fee_45": "0", "yard_name": "Bãi container SmartPort"}

USER_COLS = {"phone": "TEXT", "pay_terms": "TEXT NOT NULL DEFAULT 'prepaid'", "credit_days": "INTEGER NOT NULL DEFAULT 30"}

def init_db():
    p = db_path(); p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p); c.execute("PRAGMA journal_mode=WAL"); c.executescript(SCHEMA)
    have = {r[1] for r in c.execute("PRAGMA table_info(gate_passes)")}
    for name, ddl in PASS_COLS.items():
        if name not in have: c.execute(f"ALTER TABLE gate_passes ADD COLUMN {name} {ddl}")
    have_u = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    for name, ddl in USER_COLS.items():
        if name not in have_u: c.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
    if {"role", "status"} <= have_u:
        c.execute("UPDATE users SET role='gate' WHERE role='dispatcher'")                       # gộp điều độ vào quản trị cổng
        c.execute("UPDATE users SET status='active' WHERE role='customer' AND status='pending'")   # khách hàng không cần duyệt
    if "hour_rate" not in {r[1] for r in c.execute("PRAGMA table_info(tariff_tiers)")}: c.execute("ALTER TABLE tariff_tiers ADD COLUMN hour_rate INTEGER")   # NULL = đơn giá ngày chia 24
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_pass_token ON gate_passes(token)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_pass_plate ON gate_passes(plate_key)")
    for k, v in DEFAULT_SETTINGS.items(): c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    if not c.execute("SELECT 1 FROM tariff_tiers").fetchone():
        for sz, (f, r1, r2) in DEFAULT_TIERS.items():
            c.executemany("INSERT INTO tariff_tiers(size,day_from,day_to,rate) VALUES(?,?,?,?)", [(sz, 1, 3, f), (sz, 4, 10, r1), (sz, 11, None, r2)])
    c.commit(); c.close()

def reset_tiers(db):
    """Xoá bảng giá hiện tại, nạp lại bảng giá mặc định (số tạm để chạy thử)."""
    db.execute("DELETE FROM tariff_tiers")
    for sz, (f, r1, r2) in DEFAULT_TIERS.items():
        db.executemany("INSERT INTO tariff_tiers(size,day_from,day_to,rate) VALUES(?,?,?,?)", [(sz, 1, 3, f), (sz, 4, 10, r1), (sz, 11, None, r2)])
    db.commit()

def get_setting(db, key, default=""):
    r = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default

def set_setting(db, key, value):
    db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value))); db.commit()

def connect():
    c = sqlite3.connect(db_path(), timeout=10); c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON"); return c

# ------------------------------------------------------------ mật khẩu
def hash_password(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${h.hex()}"

def verify_password(pw, stored):
    try:
        _, n, r, p, salt, h = stored.split("$"); want = bytes.fromhex(h)
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), maxmem=_MAXMEM, dklen=len(want))
        return hmac.compare_digest(got, want)
    except Exception:
        return False

_DUMMY = None
def _dummy():
    global _DUMMY
    if _DUMMY is None: _DUMMY = hash_password("khong-ai-biet-mat-khau-nay")
    return _DUMMY

# ------------------------------------------------------------ kiểm tra dữ liệu nhập
def validate_new_user(username, full_name, email, password, password2, phone=""):
    """Trả danh sách lỗi (rỗng = hợp lệ)."""
    e = []
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username or ""): e.append("Tên đăng nhập 3-32 ký tự: chữ không dấu, số, dấu . _ -")
    if not (full_name or "").strip() or len(full_name) > 100: e.append("Họ tên không được để trống (tối đa 100 ký tự).")
    if phone and not re.fullmatch(r"(?:\+?84|0)\d{9}", re.sub(r"[ .\-]", "", phone)): e.append("Số điện thoại không đúng (10 số, ví dụ 0909123456).")
    if email and not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,255}", email): e.append("Email không đúng định dạng.")
    if len(password or "") < 8: e.append("Mật khẩu phải có ít nhất 8 ký tự.")
    elif len(password) > 128: e.append("Mật khẩu tối đa 128 ký tự.")
    elif (password or "").lower() == (username or "").lower(): e.append("Mật khẩu không được trùng tên đăng nhập.")
    elif password.isdigit() or password.isalpha(): e.append("Mật khẩu nên gồm cả chữ và số.")
    if password != password2: e.append("Hai lần nhập mật khẩu không giống nhau.")
    return e

def create_user(db, username, full_name, email, company, password, role="customer", status="pending", phone=None, pay_terms="prepaid", credit_days=30):
    if role not in ROLES or status not in STATUSES or pay_terms not in PAY_TERMS: raise ValueError("role/status không hợp lệ")
    try:
        cur = db.execute("INSERT INTO users(username,full_name,email,company,pw_hash,role,status,created_at,phone,pay_terms,credit_days) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (username, full_name.strip(), (email or "").strip() or None, (company or "").strip() or None, hash_password(password), role, status, time.time(), (phone or "").strip() or None, pay_terms, int(credit_days)))
        db.commit(); return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Tên đăng nhập này đã có người dùng.")

def authenticate(db, username, password):
    """Trả (user, lỗi). Thông báo sai tài khoản/mật khẩu luôn giống nhau để không lộ tài khoản nào tồn tại."""
    generic = "Sai tên đăng nhập hoặc mật khẩu."
    u = db.execute("SELECT * FROM users WHERE username=?", (username or "",)).fetchone()
    if u is None:
        verify_password(password or "", _dummy()); return None, generic
    now = time.time()
    if u["locked_until"] > now:
        return None, f"Tài khoản tạm khoá do nhập sai nhiều lần. Thử lại sau {int((u['locked_until'] - now) // 60) + 1} phút."
    if not verify_password(password or "", u["pw_hash"]):
        fails = u["fails"] + 1
        if fails >= MAX_FAILS: db.execute("UPDATE users SET fails=0, locked_until=? WHERE id=?", (now + LOCK_SECONDS, u["id"]))
        else: db.execute("UPDATE users SET fails=? WHERE id=?", (fails, u["id"]))
        db.commit(); return None, generic
    if u["status"] == "pending": return None, "Tài khoản đang chờ Admin boss duyệt."
    if u["status"] == "disabled": return None, "Tài khoản đã bị khoá. Liên hệ quản trị viên."
    db.execute("UPDATE users SET fails=0, locked_until=0, last_login=? WHERE id=?", (now, u["id"])); db.commit()
    return u, ""

# ------------------------------------------------------------ phiên đăng nhập
def _th(token): return hashlib.sha256(token.encode()).hexdigest()

def new_session(db, user_id):
    token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(24), time.time()
    db.execute("DELETE FROM sessions WHERE expires<?", (now,))
    db.execute("INSERT INTO sessions(token_hash,user_id,csrf,created,expires) VALUES(?,?,?,?,?)", (_th(token), user_id, csrf, now, now + SESSION_SECONDS))
    db.commit(); return token

def get_session(db, token):
    if not token: return None
    return db.execute("SELECT s.csrf AS csrf, u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.status='active'",
                      (_th(token), time.time())).fetchone()

def drop_session(db, token):
    if token: db.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),)); db.commit()

def audit(db, user_id, action, detail="", ip=""):
    db.execute("INSERT INTO audit_log(ts,user_id,action,detail,ip) VALUES(?,?,?,?,?)", (time.time(), user_id, action, detail, ip)); db.commit()
