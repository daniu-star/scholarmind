"""
ScholarMind Vercel API — 完整后端包装层
"""
import os as _os, sys as _sys, traceback as _tb

_repo = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _repo not in _sys.path: _sys.path.insert(0, _repo)

_os.environ.setdefault("ENVIRONMENT", "development")
_os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
_os.environ.setdefault("PAYMENT_ENABLED", "false")

for _k, _v in {
    "DB_PATH": "/tmp/scholarmind.db",
    "DATABASE_URL": "sqlite+aiosqlite:////tmp/scholarmind_orm.db",
    "CHROMA_DIR": "/tmp/chroma",
    "UPLOAD_DIR": "/tmp/uploads",
    "SKILLS_DIR": "/tmp/skills",
    "CHARTS_DIR": "/tmp/charts",
    "CONVERSATIONS_DIR": "/tmp/conversations",
}.items():
    _os.environ.setdefault(_k, _v)

_os.environ.setdefault("JWT_SECRET_KEY", "vercel-temp-key-change-in-production-32c")

# 尝试导入完整后端
_import_error = None
try:
    from src.backend.app import create_app
    app = create_app()
except Exception as _e:
    _import_error = _tb.format_exc()

# 如果导入失败，回退到独立 WSGI app
if _import_error:
    import hashlib, json, secrets, sqlite3, time
    from datetime import datetime, timezone

    _JWT = _os.environ["JWT_SECRET_KEY"]
    _DB = "/tmp/scholarmind_auth.db"

    def _get_db():
        c = sqlite3.connect(_DB); c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,email TEXT,nickname TEXT,password_hash TEXT,is_active INTEGER DEFAULT 1,plan TEXT DEFAULT 'free',created_at TEXT DEFAULT(datetime('now')))")
        c.execute("CREATE TABLE IF NOT EXISTS verification_codes(id INTEGER PRIMARY KEY AUTOINCREMENT,target TEXT NOT NULL,code TEXT NOT NULL,purpose TEXT DEFAULT'login',used INTEGER DEFAULT 0,expires_at TEXT NOT NULL,created_at TEXT DEFAULT(datetime('now')))")
        c.commit(); return c

    def _json(status, data):
        b = json.dumps(data, ensure_ascii=False).encode()
        return f"{status}", [("Content-Type","application/json"),("Access-Control-Allow-Origin","*")], b

    def _token(uid, phone="", email=""):
        import jwt
        return jwt.encode({"sub":str(uid),"phone":phone,"email":email,"iat":int(time.time()),"exp":int(time.time())+604800}, _JWT, algorithm="HS256")

    def _verify(t):
        import jwt
        try: return jwt.decode(t, _JWT, algorithms=["HS256"])
        except: return None

    def send_code(body):
        t = (body.get("target") or "").strip()
        if len(t) < 5: return _json("422", {"detail":"请输入有效的邮箱或手机号"})
        code = str(secrets.randbelow(900000) + 100000)
        c = _get_db()
        c.execute("INSERT INTO verification_codes(target,code,purpose,expires_at) VALUES(?,?,?,?)",(t,code,body.get("purpose","login"),datetime.now(timezone.utc).isoformat()))
        c.commit(); c.close()
        # SMTP
        smtp_user = _os.environ.get("SMTP_USER",""); smtp_pw = _os.environ.get("SMTP_PASSWORD","")
        if "@" in t and smtp_user and smtp_pw:
            try:
                import smtplib; from email.mime.text import MIMEText; from email.header import Header; from email.utils import formataddr
                domain = smtp_user.rsplit("@",1)[-1].lower()
                servers = {"qq.com":("smtp.qq.com",587),"163.com":("smtp.163.com",465),"126.com":("smtp.126.com",465),"gmail.com":("smtp.gmail.com",587)}
                host, port = servers.get(domain, ("smtp.qq.com",587))
                html = f'<div style="font-family:sans-serif;padding:20px"><h2>ScholarMind 验证码</h2><p style="font-size:32px;letter-spacing:8px;font-weight:bold">{code}</p><p>10 分钟内有效</p></div>'
                msg = MIMEText(html,"html","utf-8")
                msg["Subject"] = Header(f"[ScholarMind] 验证码：{code}","utf-8")
                msg["From"] = formataddr((_os.environ.get("SMTP_FROM_NAME","ScholarMind"), smtp_user))
                msg["To"] = t
                if port == 465:
                    with smtplib.SMTP_SSL(host,port,timeout=15) as s: s.login(smtp_user,smtp_pw); s.send_message(msg)
                else:
                    with smtplib.SMTP(host,port,timeout=15) as s: s.starttls(); s.login(smtp_user,smtp_pw); s.send_message(msg)
                return _json("200", {"success":True,"message":"验证码已发送到您的邮箱，请查收"})
            except Exception as e: return _json("200", {"success":True,"message":"验证码已生成","code":code,"smtp_error":str(e)})
        return _json("200", {"success":True,"message":"验证码已生成","code":code})

    def login(body):
        code = body.get("code","").strip(); pw = body.get("password","").strip()
        email = body.get("email","").strip(); phone = body.get("phone","").strip()
        username = body.get("username","").strip(); target = email or phone or username
        if not target: return _json("422", {"detail":"请提供手机号或邮箱"})
        c = _get_db()
        if code:
            row = c.execute("SELECT * FROM verification_codes WHERE target=? AND code=? AND used=0 ORDER BY created_at DESC LIMIT 1",(target,code)).fetchone()
            if not row: c.close(); return _json("401", {"detail":"验证码错误或已过期"})
            c.execute("UPDATE verification_codes SET used=1 WHERE id=?",(row["id"],)); c.commit()
        elif pw:
            ph = hashlib.sha256(pw.encode()).hexdigest()
            u = c.execute("SELECT * FROM users WHERE (email=? OR phone=?) AND password_hash=? AND is_active=1",(target,target,ph)).fetchone()
            if not u: c.close(); return _json("401", {"detail":"密码错误或用户不存在"})
        else: c.close(); return _json("422", {"detail":"请提供验证码或密码"})
        u = c.execute("SELECT * FROM users WHERE email=? OR phone=?",(target,target)).fetchone()
        if not u:
            c.execute("INSERT INTO users(email,phone,nickname) VALUES(?,?,?)",(email,phone,target.split("@")[0][:20] if "@" in target else target[-4:]))
            c.commit(); u = c.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
        c.close()
        tk = _token(u["id"], u["phone"] or "", u["email"] or "")
        return _json("200", {"access_token":tk,"refresh_token":tk,"token_type":"bearer","user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

    def register(body):
        email = body.get("email","").strip(); phone = body.get("phone","").strip(); pw = body.get("password","").strip()
        if not email and not phone: return _json("422", {"detail":"请提供邮箱或手机号"})
        if not pw: return _json("422", {"detail":"请设置密码"})
        nn = body.get("nickname","").strip() or (email or phone).split("@")[0][:20]
        ph = hashlib.sha256(pw.encode()).hexdigest()
        c = _get_db()
        try:
            c.execute("INSERT INTO users(email,phone,nickname,password_hash) VALUES(?,?,?,?)",(email,phone,nn,ph)); c.commit()
            u = c.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
        except sqlite3.IntegrityError: c.close(); return _json("409", {"detail":"该邮箱或手机号已注册"})
        c.close()
        tk = _token(u["id"], u["phone"] or "", u["email"] or "")
        return _json("200", {"access_token":tk,"refresh_token":tk,"token_type":"bearer","user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

    def me(auth):
        if not auth or not auth.startswith("Bearer "): return _json("401", {"detail":"未登录"})
        p = _verify(auth[7:])
        if not p: return _json("401", {"detail":"登录已过期"})
        c = _get_db()
        u = c.execute("SELECT * FROM users WHERE id=?",(int(p["sub"]),)).fetchone(); c.close()
        if not u: return _json("404", {"detail":"用户不存在"})
        return _json("200", {"user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

    def application(environ, start_response):
        method = environ.get("REQUEST_METHOD","GET")
        path = (environ.get("HTTP_X_VERCEL_ORIGINAL_PATH") or environ.get("HTTP_X_FORWARDED_PATH") or environ.get("PATH_INFO","/")).rstrip("/")
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
            if method == "GET" and path == "/api/v1/auth/me": status, hdrs, resp = me(auth)
            elif method == "GET" and path == "/api/v1/debug": status, hdrs, resp = _json("200", {"status":"ok","backend":"fallback","import_error":_import_error[:500]})
            elif method == "GET" and path in ("/api/v1/health","/api/index"): status, hdrs, resp = _json("200", {"status":"ok","backend":"fallback","import_error":str(_import_error)[:300] if _import_error else None})
            elif method == "POST" and path == "/api/v1/auth/send-code": status, hdrs, resp = send_code(body)
            elif method == "POST" and path == "/api/v1/auth/login": status, hdrs, resp = login(body)
            elif method == "POST" and path == "/api/v1/auth/register": status, hdrs, resp = register(body)
            else: status, hdrs, resp = _json("404", {"detail":f"Not found: {method} {path}"})
        except Exception as e: status, hdrs, resp = _json("500", {"detail":str(e),"trace":_tb.format_exc()})
        start_response(status, hdrs)
        return [resp]

    app = application
