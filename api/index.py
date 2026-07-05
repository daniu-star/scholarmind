"""ScholarMind Auth API — Vercel Python WSGI"""
import json, os, hashlib, secrets, sqlite3, time, traceback
from datetime import datetime, timezone

JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "dev-key-min-32-characters-long!!")
DB_PATH = "/tmp/scholarmind_auth.db"
_db_ok = False

def _init_db():
    global _db_ok
    try:
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, email TEXT, nickname TEXT, password_hash TEXT, is_active INTEGER DEFAULT 1, plan TEXT DEFAULT 'free', created_at TEXT DEFAULT (datetime('now')))")
        conn.execute("CREATE TABLE IF NOT EXISTS verification_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT NOT NULL, code TEXT NOT NULL, purpose TEXT DEFAULT 'login', used INTEGER DEFAULT 0, expires_at TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))")
        conn.commit(); conn.close(); _db_ok = True
    except Exception: _db_ok = False

_init_db()

def _token(uid, phone="", email=""):
    import jwt
    return jwt.encode({"sub":str(uid),"phone":phone,"email":email,"iat":int(time.time()),"exp":int(time.time())+604800}, JWT_SECRET, algorithm="HS256")

def _verify(token):
    import jwt
    try: return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except: return None

def _json(status, data):
    body = json.dumps(data, ensure_ascii=False)
    headers = [("Content-Type","application/json; charset=utf-8"),("Access-Control-Allow-Origin","*"),("Access-Control-Allow-Methods","GET,POST,OPTIONS"),("Access-Control-Allow-Headers","Content-Type,Authorization")]
    return f"{status}", headers, body.encode()

def send_code(body):
    t = (body.get("target") or "").strip()
    if len(t) < 5: return _json("422 Unprocessable Entity", {"detail":"请输入有效的邮箱或手机号"})
    code = str(secrets.randbelow(900000)+100000)
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO verification_codes(target,code,purpose,expires_at) VALUES(?,?,?,?)",(t,code,body.get("purpose","login"),datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()
    return _json("200 OK", {"success":True,"message":"验证码已生成","code":code})

def login(body):
    code = body.get("code","").strip(); pw = body.get("password","").strip()
    email = body.get("email","").strip(); phone = body.get("phone","").strip(); username = body.get("username","").strip()
    target = email or phone or username
    if not target: return _json("422 Unprocessable Entity", {"detail":"请提供手机号或邮箱"})
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    if code:
        row = conn.execute("SELECT * FROM verification_codes WHERE target=? AND code=? AND used=0 ORDER BY created_at DESC LIMIT 1",(target,code)).fetchone()
        if not row: conn.close(); return _json("401 Unauthorized", {"detail":"验证码错误或已过期"})
        conn.execute("UPDATE verification_codes SET used=1 WHERE id=?",(row["id"],)); conn.commit()
    elif pw:
        ph = hashlib.sha256(pw.encode()).hexdigest()
        u = conn.execute("SELECT * FROM users WHERE (email=? OR phone=?) AND password_hash=? AND is_active=1",(target,target,ph)).fetchone()
        if not u: conn.close(); return _json("401 Unauthorized", {"detail":"密码错误或用户不存在"})
    else: conn.close(); return _json("422 Unprocessable Entity", {"detail":"请提供验证码或密码"})
    u = conn.execute("SELECT * FROM users WHERE email=? OR phone=?",(target,target)).fetchone()
    if not u:
        conn.execute("INSERT INTO users(email,phone,nickname) VALUES(?,?,?)",(email,phone,target.split("@")[0][:20] if "@" in target else target[-4:]))
        conn.commit(); u = conn.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
    conn.close()
    tk = _token(u["id"], u["phone"] or "", u["email"] or "")
    return _json("200 OK", {"access_token":tk,"refresh_token":tk,"token_type":"bearer","user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

def register(body):
    email = body.get("email","").strip(); phone = body.get("phone","").strip(); pw = body.get("password","").strip()
    if not email and not phone: return _json("422 Unprocessable Entity", {"detail":"请提供邮箱或手机号"})
    if not pw: return _json("422 Unprocessable Entity", {"detail":"请设置密码"})
    nn = body.get("nickname","").strip() or (email or phone).split("@")[0][:20]
    ph = hashlib.sha256(pw.encode()).hexdigest()
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    try:
        conn.execute("INSERT INTO users(email,phone,nickname,password_hash) VALUES(?,?,?,?)",(email,phone,nn,ph)); conn.commit()
        u = conn.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
    except sqlite3.IntegrityError: conn.close(); return _json("409 Conflict", {"detail":"该邮箱或手机号已注册"})
    conn.close()
    tk = _token(u["id"], u["phone"] or "", u["email"] or "")
    return _json("200 OK", {"access_token":tk,"refresh_token":tk,"token_type":"bearer","user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

def me(auth):
    if not auth or not auth.startswith("Bearer "): return _json("401 Unauthorized", {"detail":"未登录"})
    p = _verify(auth[7:])
    if not p: return _json("401 Unauthorized", {"detail":"登录已过期"})
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    u = conn.execute("SELECT * FROM users WHERE id=?",(int(p["sub"]),)).fetchone(); conn.close()
    if not u: return _json("404 Not Found", {"detail":"用户不存在"})
    return _json("200 OK", {"user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

ROUTES = {
    ("POST","/api/v1/auth/send-code"): send_code,
    ("POST","/api/v1/auth/login"): login,
    ("POST","/api/v1/auth/register"): register,
}

def application(environ, start_response):
    method = environ.get("REQUEST_METHOD","GET")
    path = environ.get("PATH_INFO","/").rstrip("/")
    auth = environ.get("HTTP_AUTHORIZATION","")
    if method == "OPTIONS":
        start_response("200 OK", [("Access-Control-Allow-Origin","*"),("Access-Control-Allow-Methods","GET,POST,OPTIONS"),("Access-Control-Allow-Headers","Content-Type,Authorization")])
        return [b""]
    try:
        cl = int(environ.get("CONTENT_LENGTH",0))
        raw = environ["wsgi.input"].read(cl) if cl else b""
        body = json.loads(raw) if raw else {}
    except: body = {}
    try:
        if method == "GET" and path == "/api/v1/auth/me":
            status, headers, resp_body = me(auth)
        elif method == "GET" and path in ("/api/v1/health","/api/index"):
            status, headers, resp_body = _json("200 OK", {"status":"ok","version":"3.0.0-vercel"})
        elif (method, path) in ROUTES:
            status, headers, resp_body = ROUTES[(method, path)](body)
        else:
            status, headers, resp_body = _json("404 Not Found", {"detail":f"Not found: {method} {path}"})
    except Exception as e:
        status, headers, resp_body = _json("500 Internal Server Error", {"detail":str(e),"trace":traceback.format_exc()})
    start_response(status, headers)
    return [resp_body]

app = application
