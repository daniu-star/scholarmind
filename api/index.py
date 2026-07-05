"""ScholarMind Auth API — Vercel Python WSGI (with SMTP email)"""
from __future__ import annotations

import hashlib, json, os, secrets, smtplib, sqlite3, time, traceback
from datetime import datetime, timezone
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

# ── 配置 ──────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "dev-key-min-32-characters-long!!")
DB_PATH = "/tmp/scholarmind_auth.db"

# SMTP 配置（通过 Vercel 环境变量设置）
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "0"))
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "ScholarMind")

# SMTP 服务器自动检测表
SMTP_SERVERS = {
    "qq.com": ("smtp.qq.com", 587), "vip.qq.com": ("smtp.qq.com", 587),
    "foxmail.com": ("smtp.qq.com", 587), "163.com": ("smtp.163.com", 465),
    "126.com": ("smtp.126.com", 465), "yeah.net": ("smtp.yeah.net", 465),
    "gmail.com": ("smtp.gmail.com", 587), "outlook.com": ("smtp-mail.outlook.com", 587),
    "hotmail.com": ("smtp-mail.outlook.com", 587), "live.com": ("smtp-mail.outlook.com", 587),
    "sina.com": ("smtp.sina.com", 465), "sina.cn": ("smtp.sina.com", 465),
    "sohu.com": ("smtp.sohu.com", 465), "aliyun.com": ("smtp.aliyun.com", 465),
    "icloud.com": ("smtp.mail.me.com", 587), "zoho.com": ("smtp.zoho.com", 587),
}

def _detect_smtp(email: str) -> tuple[str, int]:
    domain = email.rsplit("@", 1)[-1].lower()
    return SMTP_SERVERS.get(domain, ("smtp.qq.com", 587))

# ── 数据库 ────────────────────────────────────────────
def _get_db():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, email TEXT, nickname TEXT, password_hash TEXT, is_active INTEGER DEFAULT 1, plan TEXT DEFAULT 'free', created_at TEXT DEFAULT (datetime('now')))")
    conn.execute("CREATE TABLE IF NOT EXISTS verification_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT NOT NULL, code TEXT NOT NULL, purpose TEXT DEFAULT 'login', used INTEGER DEFAULT 0, expires_at TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))")
    conn.commit()
    return conn

def _mask_email(email: str) -> str:
    if "@" not in email: return "***"
    local, domain = email.rsplit("@", 1)
    return f"{local[:2]}***@{domain}"

# ── SMTP 邮件发送 ─────────────────────────────────────
def _send_email(to_email: str, code: str) -> str | None:
    """发送验证码邮件。成功返回 None，失败返回错误信息字符串。"""
    if not SMTP_USER or not SMTP_PASSWORD:
        return "SMTP 未配置（设置 SMTP_USER 和 SMTP_PASSWORD 环境变量）"

    if SMTP_HOST and SMTP_PORT > 0:
        host, port = SMTP_HOST, SMTP_PORT
    else:
        host, port = _detect_smtp(SMTP_USER)

    html = f"""\
<div style="max-width:480px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;color:#1a1a1a;background:#f0f7f1;border-radius:16px;padding:36px 28px">
  <div style="text-align:center;margin-bottom:24px">
    <div style="display:inline-block;background:linear-gradient(135deg,#2E7D32,#1B5E20);color:#fff;font-size:28px;font-weight:700;padding:8px 20px;border-radius:10px;letter-spacing:1px">ScholarMind</div>
    <div style="font-size:13px;color:#6b8e6f;margin-top:8px">智能学术研究助手 · 验证码</div>
  </div>
  <div style="background:#fff;border-radius:14px;padding:28px 24px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.06)">
    <div style="font-size:15px;color:#4a5b4c;margin-bottom:18px">您的验证码是</div>
    <div style="font-size:42px;font-weight:700;letter-spacing:10px;color:#2E7D32;margin-bottom:18px;font-family:'SF Mono','Consolas','Courier New',monospace">{code}</div>
    <div style="display:inline-block;background:#f0f7f1;color:#5a8a5e;font-size:12px;padding:6px 14px;border-radius:20px">10 分钟内有效，请勿泄露</div>
  </div>
  <div style="text-align:center;margin-top:20px;font-size:11px;color:#a0b8a2;line-height:1.6">
    此邮件由 ScholarMind 自动发送<br>如非本人操作，请忽略
  </div>
</div>"""

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = Header(f"[ScholarMind] 验证码：{code}", "utf-8")
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_USER))
    msg["To"] = to_email
    msg["Reply-To"] = SMTP_USER

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        return None  # 成功
    except smtplib.SMTPAuthenticationError:
        return "SMTP 登录失败：用户名或授权码错误（注意：需要使用邮箱授权码，而非登录密码）"
    except smtplib.SMTPConnectError as e:
        return f"无法连接邮件服务器（{host}:{port}）：{e}"
    except smtplib.SMTPException as e:
        return f"邮件发送失败：{e}"
    except Exception as e:
        return f"邮件发送异常：{e}"

# ── JWT ───────────────────────────────────────────────
def _token(uid, phone="", email=""):
    import jwt
    return jwt.encode({"sub":str(uid),"phone":phone,"email":email,"iat":int(time.time()),"exp":int(time.time())+604800}, JWT_SECRET, algorithm="HS256")

def _verify(token):
    import jwt
    try: return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except: return None

# ── HTTP 响应 ─────────────────────────────────────────
def _json(status, data):
    body = json.dumps(data, ensure_ascii=False)
    headers = [("Content-Type","application/json; charset=utf-8"),("Access-Control-Allow-Origin","*"),("Access-Control-Allow-Methods","GET,POST,OPTIONS"),("Access-Control-Allow-Headers","Content-Type,Authorization")]
    return f"{status}", headers, body.encode()

# ── 路由处理 ──────────────────────────────────────────
def send_code(body):
    target = (body.get("target") or "").strip()
    if len(target) < 5: return _json("422 Unprocessable Entity", {"detail":"请输入有效的邮箱或手机号"})
    code = str(secrets.randbelow(900000) + 100000)

    # 存储验证码
    conn = _get_db()
    conn.execute("INSERT INTO verification_codes(target,code,purpose,expires_at) VALUES(?,?,?,?)",
                 (target, code, body.get("purpose", "login"), datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()

    # 如果是邮箱，尝试发送邮件
    is_email = "@" in target
    if is_email:
        smtp_err = _send_email(target, code)
        if smtp_err:
            # SMTP 未配置或发送失败 — 返回 code 方便测试
            return _json("200 OK", {
                "success": True,
                "message": f"验证码已生成（邮件发送失败：{smtp_err}）",
                "code": code,  # 调试用，SMTP 配置后会自动隐藏
                "smtp_error": smtp_err,
            })
        # 邮件发送成功 — 不返回 code
        return _json("200 OK", {"success": True, "message": "验证码已发送到您的邮箱，请查收（含垃圾邮件箱）"})

    # 手机号 — 不发送短信，仅存储
    return _json("200 OK", {"success": True, "message": "验证码已生成", "code": code})

def login(body):
    code = body.get("code","").strip(); pw = body.get("password","").strip()
    email = body.get("email","").strip(); phone = body.get("phone","").strip(); username = body.get("username","").strip()
    target = email or phone or username
    if not target: return _json("422 Unprocessable Entity", {"detail":"请提供手机号或邮箱"})
    conn = _get_db()
    if code:
        row = conn.execute("SELECT * FROM verification_codes WHERE target=? AND code=? AND used=0 ORDER BY created_at DESC LIMIT 1",
                           (target, code)).fetchone()
        if not row: conn.close(); return _json("401 Unauthorized", {"detail":"验证码错误或已过期"})
        conn.execute("UPDATE verification_codes SET used=1 WHERE id=?",(row["id"],)); conn.commit()
    elif pw:
        ph = hashlib.sha256(pw.encode()).hexdigest()
        u = conn.execute("SELECT * FROM users WHERE (email=? OR phone=?) AND password_hash=? AND is_active=1",
                         (target, target, ph)).fetchone()
        if not u: conn.close(); return _json("401 Unauthorized", {"detail":"密码错误或用户不存在"})
    else: conn.close(); return _json("422 Unprocessable Entity", {"detail":"请提供验证码或密码"})
    u = conn.execute("SELECT * FROM users WHERE email=? OR phone=?",(target, target)).fetchone()
    if not u:
        conn.execute("INSERT INTO users(email,phone,nickname) VALUES(?,?,?)",
                     (email, phone, target.split("@")[0][:20] if "@" in target else target[-4:]))
        conn.commit(); u = conn.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
    conn.close()
    tk = _token(u["id"], u["phone"] or "", u["email"] or "")
    return _json("200 OK", {"access_token":tk,"refresh_token":tk,"token_type":"bearer",
        "user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

def register(body):
    email = body.get("email","").strip(); phone = body.get("phone","").strip(); pw = body.get("password","").strip()
    if not email and not phone: return _json("422 Unprocessable Entity", {"detail":"请提供邮箱或手机号"})
    if not pw: return _json("422 Unprocessable Entity", {"detail":"请设置密码"})
    nn = body.get("nickname","").strip() or (email or phone).split("@")[0][:20]
    ph = hashlib.sha256(pw.encode()).hexdigest()
    conn = _get_db()
    try:
        conn.execute("INSERT INTO users(email,phone,nickname,password_hash) VALUES(?,?,?,?)",(email,phone,nn,ph)); conn.commit()
        u = conn.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
    except sqlite3.IntegrityError: conn.close(); return _json("409 Conflict", {"detail":"该邮箱或手机号已注册"})
    conn.close()
    tk = _token(u["id"], u["phone"] or "", u["email"] or "")
    return _json("200 OK", {"access_token":tk,"refresh_token":tk,"token_type":"bearer",
        "user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

def me(auth):
    if not auth or not auth.startswith("Bearer "): return _json("401 Unauthorized", {"detail":"未登录"})
    p = _verify(auth[7:])
    if not p: return _json("401 Unauthorized", {"detail":"登录已过期"})
    conn = _get_db()
    u = conn.execute("SELECT * FROM users WHERE id=?",(int(p["sub"]),)).fetchone(); conn.close()
    if not u: return _json("404 Not Found", {"detail":"用户不存在"})
    return _json("200 OK", {"user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

ROUTES = {
    ("POST","/api/v1/auth/send-code"): send_code,
    ("POST","/api/v1/auth/login"): login,
    ("POST","/api/v1/auth/register"): register,
}

# ── WSGI Application ──────────────────────────────────
def application(environ, start_response):
    method = environ.get("REQUEST_METHOD","GET")
    path = (environ.get("HTTP_X_VERCEL_ORIGINAL_PATH") or
            environ.get("HTTP_X_FORWARDED_PATH") or
            environ.get("PATH_INFO","/")).rstrip("/")
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
        elif method == "GET" and path == "/api/v1/debug":
            info = {k: str(v) for k, v in environ.items() if k.startswith(("HTTP_","PATH_","REQUEST_","SERVER_"))}
            info["smtp_configured"] = bool(SMTP_USER and SMTP_PASSWORD)
            info["smtp_user"] = _mask_email(SMTP_USER) if SMTP_USER else "not set"
            status, headers, resp_body = _json("200 OK", {"status":"ok","path":path,"environ":info})
        elif method == "GET" and path in ("/api/v1/health","/api/index"):
            status, headers, resp_body = _json("200 OK", {"status":"ok","version":"3.0.0-vercel","smtp":bool(SMTP_USER and SMTP_PASSWORD)})
        elif (method, path) in ROUTES:
            status, headers, resp_body = ROUTES[(method, path)](body)
        else:
            status, headers, resp_body = _json("404 Not Found", {"detail":f"Not found: {method} {path}"})
    except Exception as e:
        status, headers, resp_body = _json("500 Internal Server Error", {"detail":str(e),"trace":traceback.format_exc()})
    start_response(status, headers)
    return [resp_body]

app = application
