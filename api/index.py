"""
ScholarMind Auth API — Vercel Python Serverless Function

独立轻量 auth 端点，在 Vercel 上直接处理登录/注册/验证码。
避免导入完整的 src/backend/（启动链太复杂，在 Vercel 上容易崩溃）。

端点：
  POST /api/v1/auth/send-code   — 发送验证码
  POST /api/v1/auth/login       — 验证码/密码登录
  POST /api/v1/auth/register    — 注册
  GET  /api/v1/auth/me          — 获取当前用户
  GET  /api/v1/health           — 健康检查
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

import jwt

# ── 配置 ──────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "scholarmind-vercel-dev-key-min-32-chars!!")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY = 86400 * 7  # 7 天
DB_PATH = "/tmp/scholarmind_auth.db"

# ── 数据库初始化 ──────────────────────────────────────
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            email TEXT,
            nickname TEXT,
            password_hash TEXT,
            is_active INTEGER DEFAULT 1,
            plan TEXT DEFAULT 'free',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target TEXT NOT NULL,
            code TEXT NOT NULL,
            purpose TEXT DEFAULT 'login',
            used INTEGER DEFAULT 0,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ── JWT 工具 ──────────────────────────────────────────
def create_token(user_id: int, phone: str = "", email: str = "") -> str:
    payload = {
        "sub": str(user_id),
        "phone": phone,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None

# ── HTTP 处理 ─────────────────────────────────────────
def json_response(status_code: int, data: dict) -> dict:
    return {"statusCode": status_code, "body": json.dumps(data, ensure_ascii=False), "headers": {"Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization"}}

# ── 路由处理 ──────────────────────────────────────────
def handle_send_code(body: dict) -> dict:
    target = (body.get("target") or "").strip()
    purpose = body.get("purpose", "login")
    if not target or len(target) < 5:
        return json_response(422, {"detail": "请输入有效的邮箱或手机号"})

    conn = get_db()
    code = str(secrets.randbelow(900000) + 100000)
    expires = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # 简化：直接存储，不实际发邮件（Vercel 无 SMTP）
    conn.execute(
        "INSERT INTO verification_codes (target, code, purpose, expires_at) VALUES (?, ?, ?, ?)",
        (target, code, purpose, expires),
    )
    conn.commit()
    conn.close()
    # 开发模式：返回验证码明文（生产环境应通过邮件发送）
    return json_response(200, {"success": True, "message": "验证码已生成", "code": code})

def handle_login(body: dict) -> dict:
    code = body.get("code", "").strip()
    password = body.get("password", "").strip()
    phone = body.get("phone", "").strip()
    email = body.get("email", "").strip()
    username = body.get("username", "").strip()

    target = email or phone or username
    if not target:
        return json_response(422, {"detail": "请提供手机号或邮箱"})

    conn = get_db()

    if code:
        # 验证码登录
        row = conn.execute(
            "SELECT * FROM verification_codes WHERE target=? AND code=? AND used=0 ORDER BY created_at DESC LIMIT 1",
            (target, code),
        ).fetchone()
        if not row:
            conn.close()
            return json_response(401, {"detail": "验证码错误或已过期"})
        conn.execute("UPDATE verification_codes SET used=1 WHERE id=?", (row["id"],))
        conn.commit()
    elif password:
        # 密码登录
        import hashlib
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        user = conn.execute(
            "SELECT * FROM users WHERE (email=? OR phone=?) AND password_hash=? AND is_active=1",
            (target, target, pw_hash),
        ).fetchone()
        if not user:
            conn.close()
            return json_response(401, {"detail": "密码错误或用户不存在"})
    else:
        conn.close()
        return json_response(422, {"detail": "请提供验证码或密码"})

    # 查找或创建用户
    user = conn.execute(
        "SELECT * FROM users WHERE email=? OR phone=?",
        (target, target),
    ).fetchone()
    if not user:
        # 自动注册
        conn.execute(
            "INSERT INTO users (email, phone, nickname) VALUES (?, ?, ?)",
            (email, phone, (email or phone).split("@")[0] if "@" in target else (phone or "")[-4:]),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
    conn.close()

    token = create_token(user["id"], user["phone"] or "", user["email"] or "")
    return json_response(200, {
        "access_token": token,
        "refresh_token": token,
        "token_type": "bearer",
        "user": {"id": user["id"], "phone": user["phone"], "email": user["email"], "nickname": user["nickname"], "plan": user["plan"]},
        "entitlements": None,
    })

def handle_register(body: dict) -> dict:
    email = body.get("email", "").strip()
    phone = body.get("phone", "").strip()
    password = body.get("password", "").strip()
    nickname = body.get("nickname", "").strip() or (email or phone).split("@")[0][:20]

    if not email and not phone:
        return json_response(422, {"detail": "请提供邮箱或手机号"})
    if not password:
        return json_response(422, {"detail": "请设置密码"})

    import hashlib
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (email, phone, nickname, password_hash) VALUES (?, ?, ?, ?)",
            (email, phone, nickname, pw_hash),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
    except sqlite3.IntegrityError:
        conn.close()
        return json_response(409, {"detail": "该邮箱或手机号已注册"})
    conn.close()

    token = create_token(user["id"], user["phone"] or "", user["email"] or "")
    return json_response(200, {
        "access_token": token,
        "refresh_token": token,
        "token_type": "bearer",
        "user": {"id": user["id"], "phone": user["phone"], "email": user["email"], "nickname": user["nickname"], "plan": user["plan"]},
        "entitlements": None,
    })

def handle_me(auth_header: str) -> dict:
    if not auth_header or not auth_header.startswith("Bearer "):
        return json_response(401, {"detail": "未登录"})
    token = auth_header[7:]
    payload = verify_token(token)
    if not payload:
        return json_response(401, {"detail": "登录已过期"})
    user_id = int(payload.get("sub", 0))
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not user:
        return json_response(404, {"detail": "用户不存在"})
    return json_response(200, {
        "user": {"id": user["id"], "phone": user["phone"], "email": user["email"], "nickname": user["nickname"], "plan": user["plan"]},
        "entitlements": None,
    })

# ── 路由表 ────────────────────────────────────────────
ROUTES = {
    ("POST", "/api/v1/auth/send-code"): handle_send_code,
    ("POST", "/api/v1/auth/login"): handle_login,
    ("POST", "/api/v1/auth/register"): handle_register,
    ("GET", "/api/v1/auth/me"): handle_me,
    ("GET", "/api/v1/health"): lambda _b, _h: json_response(200, {"status": "ok", "version": "3.0.0-vercel"}),
}

# ── Vercel Handler ────────────────────────────────────
class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _route(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body_raw = self._read_body()
        body = json.loads(body_raw) if body_raw else {}

        # 特殊处理 /me 端点（需要 auth header）
        if (method, path) == ("GET", "/api/v1/auth/me"):
            auth = self.headers.get("Authorization", "")
            result = handle_me(auth)
        elif (method, path) in ROUTES:
            handler_fn = ROUTES[(method, path)]
            if handler_fn.__code__.co_argcount == 2:
                result = handler_fn(body, self.headers.get("Authorization", ""))
            else:
                result = handler_fn(body)
        elif path == "/api/index":
            # Vercel 内部重写，返回 200
            result = json_response(200, {"status": "ok", "message": "ScholarMind API"})
        else:
            result = json_response(404, {"detail": f"Not found: {method} {path}"})

        self.send_response(result["statusCode"])
        for key, value in result.get("headers", {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(result["body"].encode("utf-8"))

    def _read_body(self) -> str | None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            return self.rfile.read(content_length).decode("utf-8")
        return None

    def log_message(self, format, *args):
        pass  # 禁止 Vercel 日志噪音
