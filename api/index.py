"""ScholarMind API — Vercel Python (complete route coverage)"""
from __future__ import annotations
import hashlib, json, os, re, secrets, smtplib, sqlite3, time, traceback
from datetime import datetime, timezone
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

JWT_SECRET = os.environ.get("JWT_SECRET_KEY","dev-key-min-32-chars-long!!")
DB_PATH = "/tmp/scholarmind_auth.db"
SMTP_USER = os.environ.get("SMTP_USER","")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD","")
SMTP_FROM = os.environ.get("SMTP_FROM_NAME","ScholarMind")

def _get_db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,email TEXT,nickname TEXT,password_hash TEXT,is_active INTEGER DEFAULT 1,plan TEXT DEFAULT'free',created_at TEXT DEFAULT(datetime('now')))")
    c.execute("CREATE TABLE IF NOT EXISTS verification_codes(id INTEGER PRIMARY KEY AUTOINCREMENT,target TEXT NOT NULL,code TEXT NOT NULL,purpose TEXT DEFAULT'login',used INTEGER DEFAULT 0,expires_at TEXT NOT NULL,created_at TEXT DEFAULT(datetime('now')))")
    c.commit(); return c

def _json(status, data):
    b=json.dumps(data,ensure_ascii=False).encode()
    return f"{status}",[("Content-Type","application/json"),("Access-Control-Allow-Origin","*"),("Access-Control-Allow-Methods","GET,POST,OPTIONS,PATCH,DELETE"),("Access-Control-Allow-Headers","Content-Type,Authorization")],b

def _token(uid,phone="",email=""):
    import jwt
    return jwt.encode({"sub":str(uid),"phone":phone,"email":email,"iat":int(time.time()),"exp":int(time.time())+604800},JWT_SECRET,algorithm="HS256")

def _verify(t):
    import jwt
    try: return jwt.decode(t,JWT_SECRET,algorithms=["HS256"])
    except: return None

# ── Auth handlers ─────────────────────────────────────
def auth_send_code(body):
    t=(body.get("target")or"").strip()
    if len(t)<5: return _json("422",{"detail":"请输入有效的邮箱或手机号"})
    code=str(secrets.randbelow(900000)+100000)
    c=_get_db()
    c.execute("INSERT INTO verification_codes(target,code,purpose,expires_at) VALUES(?,?,?,?)",(t,code,body.get("purpose","login"),datetime.now(timezone.utc).isoformat()))
    c.commit();c.close()
    if "@" in t and SMTP_USER and SMTP_PASSWORD:
        try:
            domain=SMTP_USER.rsplit("@",1)[-1].lower()
            servers={"qq.com":("smtp.qq.com",587),"163.com":("smtp.163.com",465),"126.com":("smtp.126.com",465),"gmail.com":("smtp.gmail.com",587)}
            host,port=servers.get(domain,("smtp.qq.com",587))
            html=f'<div style="font-family:sans-serif;padding:20px"><h2>ScholarMind</h2><p style="font-size:32px;letter-spacing:8px">{code}</p><p>10分钟内有效</p></div>'
            msg=MIMEText(html,"html","utf-8"); msg["Subject"]=Header(f"[ScholarMind] 验证码：{code}","utf-8")
            msg["From"]=formataddr((SMTP_FROM,SMTP_USER)); msg["To"]=t
            if port==465:
                with smtplib.SMTP_SSL(host,port,timeout=15)as s:s.login(SMTP_USER,SMTP_PASSWORD);s.send_message(msg)
            else:
                with smtplib.SMTP(host,port,timeout=15)as s:s.starttls();s.login(SMTP_USER,SMTP_PASSWORD);s.send_message(msg)
            return _json("200",{"success":True,"message":"验证码已发送到您的邮箱，请查收"})
        except Exception as e: return _json("200",{"success":True,"message":"验证码已生成","code":code,"smtp_error":str(e)})
    return _json("200",{"success":True,"message":"验证码已生成","code":code})

def auth_login(body):
    code=body.get("code","").strip();pw=body.get("password","").strip()
    email=body.get("email","").strip();phone=body.get("phone","").strip()
    username=body.get("username","").strip();target=email or phone or username
    if not target: return _json("422",{"detail":"请提供手机号或邮箱"})
    c=_get_db()
    if code:
        row=c.execute("SELECT * FROM verification_codes WHERE target=? AND code=? AND used=0 ORDER BY created_at DESC LIMIT 1",(target,code)).fetchone()
        if not row: c.close(); return _json("401",{"detail":"验证码错误或已过期"})
        c.execute("UPDATE verification_codes SET used=1 WHERE id=?",(row["id"],));c.commit()
    elif pw:
        ph=hashlib.sha256(pw.encode()).hexdigest()
        u=c.execute("SELECT * FROM users WHERE (email=? OR phone=?) AND password_hash=? AND is_active=1",(target,target,ph)).fetchone()
        if not u: c.close(); return _json("401",{"detail":"密码错误或用户不存在"})
    else: c.close(); return _json("422",{"detail":"请提供验证码或密码"})
    u=c.execute("SELECT * FROM users WHERE email=? OR phone=?",(target,target)).fetchone()
    if not u:
        c.execute("INSERT INTO users(email,phone,nickname) VALUES(?,?,?)",(email,phone,target.split("@")[0][:20] if "@" in target else target[-4:]))
        c.commit(); u=c.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
    c.close(); tk=_token(u["id"],u["phone"]or"",u["email"]or"")
    return _json("200",{"access_token":tk,"refresh_token":tk,"token_type":"bearer","user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

def auth_register(body):
    email=body.get("email","").strip();phone=body.get("phone","").strip();pw=body.get("password","").strip()
    if not email and not phone: return _json("422",{"detail":"请提供邮箱或手机号"})
    if not pw: return _json("422",{"detail":"请设置密码"})
    nn=body.get("nickname","").strip()or(email or phone).split("@")[0][:20]
    ph=hashlib.sha256(pw.encode()).hexdigest(); c=_get_db()
    try:
        c.execute("INSERT INTO users(email,phone,nickname,password_hash) VALUES(?,?,?,?)",(email,phone,nn,ph));c.commit()
        u=c.execute("SELECT * FROM users WHERE rowid=last_insert_rowid()").fetchone()
    except sqlite3.IntegrityError: c.close(); return _json("409",{"detail":"该邮箱或手机号已注册"})
    c.close(); tk=_token(u["id"],u["phone"]or"",u["email"]or"")
    return _json("200",{"access_token":tk,"refresh_token":tk,"token_type":"bearer","user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

def auth_me(auth):
    if not auth or not auth.startswith("Bearer "): return _json("401",{"detail":"未登录"})
    p=_verify(auth[7:])
    if not p: return _json("401",{"detail":"登录已过期"})
    c=_get_db(); u=c.execute("SELECT * FROM users WHERE id=?",(int(p["sub"]),)).fetchone();c.close()
    if not u: return _json("404",{"detail":"用户不存在"})
    return _json("200",{"user":{"id":u["id"],"phone":u["phone"],"email":u["email"],"nickname":u["nickname"],"plan":u["plan"]},"entitlements":None})

# ── Payment stubs ─────────────────────────────────────
def payment_packages():
    return _json("200",{"packages":[
        {"id":"single","name":"单次生成","price":4.99,"tokens":1,"model":"flash","description":"单次论文生成"},
        {"id":"bundle5","name":"论文套餐5篇","price":19.99,"tokens":5,"model":"flash","description":"5次论文生成"},
        {"id":"monthly","name":"月度畅享","price":39.90,"tokens":-1,"model":"flash","description":"30天不限次"},
        {"id":"monthly_pro","name":"月度Pro","price":59.90,"tokens":-1,"model":"pro","description":"30天Pro模型不限次"},
    ]})

def payment_orders():
    return _json("200",{"order_no":"DEMO-"+str(int(time.time())),"message":"演示模式：虚拟订单已创建","amount":0,"payment_url":""})

def payment_order_status(order_no):
    return _json("200",{"order_no":order_no,"status":"pending","message":"演示模式：请使用虚拟订单号"})

def payment_confirm():
    return _json("200",{"success":True,"message":"演示模式：支付确认成功"})

# ── Agent stubs ───────────────────────────────────────
def agent_agents():
    return _json("200",{"agents":[
        {"id":"researcher","name":"研究员","color":"amber","description":"选题与研究设计"},
        {"id":"reviewer","name":"审查员","color":"blue","description":"论文评审与反馈"},
        {"id":"architect","name":"架构师","color":"teal","description":"论文结构设计"},
        {"id":"synthesizer","name":"综述员","color":"purple","description":"文献综合与归纳"},
        {"id":"polisher","name":"润色员","color":"green","description":"语言润色与优化"},
        {"id":"external_reviewer","name":"外审专家","color":"amber","description":"专家级论文审稿"},
    ]})

def agent_chat(body):
    return _json("200",{"reply":"您好！我是 ScholarMind AI 助手。当前为演示模式，完整 Agent 对话功能即将上线。","session_id":"demo-"+str(int(time.time()))})

def agent_sessions():
    return _json("200",{"sessions":[]})

def agent_topics(disc):
    return _json("200",{"topics":["研究选题建议","文献综述方法","研究设计指导","数据分析策略"]})

def agent_conversation(sid):
    return _json("200",{"messages":[]})

# ── Knowledge / Chart / Upload stubs ──────────────────
def knowledge_status():
    return _json("200",{"status":"ok","documents":0,"rag_ready":False})

def chart_generate(body):
    return _json("200",{"chart_id":"demo","image_url":"","message":"演示模式：图表功能即将上线"})

def upload_file(body=None):
    return _json("200",{"success":True,"file_id":"demo","message":"演示模式：文件上传功能即将上线"})

def skills_list():
    return _json("200",{"skills":[]})

def pipeline_start():
    return _json("200",{"pipeline_id":"demo","status":"started","message":"演示模式：论文管线功能即将上线"})

def pipeline_status(pid):
    return _json("200",{"status":"completed","progress":100})

# ── Router ────────────────────────────────────────────
ROUTES = [
    # Auth
    (r"POST /api/v1/auth/send-code", auth_send_code),
    (r"POST /api/v1/auth/login", auth_login),
    (r"POST /api/v1/auth/register", auth_register),
    (r"GET /api/v1/auth/me", auth_me),
    # Payment
    (r"GET /api/v1/payment/packages", lambda b,a: payment_packages()),
    (r"POST /api/v1/payment/orders", lambda b,a: payment_orders()),
    (r"GET /api/v1/payment/orders/([^/]+)/status", lambda b,a,m: payment_order_status(m)),
    (r"POST /api/v1/payment/confirm", lambda b,a: payment_confirm()),
    (r"GET /api/v1/payment/admin/pending", lambda b,a: _json("200",{"orders":[]})),
    (r"POST /api/v1/payment/admin/([^/]+)/approve", lambda b,a,m: _json("200",{"success":True})),
    (r"POST /api/v1/payment/admin/([^/]+)/reject", lambda b,a,m: _json("200",{"success":True})),
    # Agent
    (r"GET /api/v1/agent/agents", lambda b,a: agent_agents()),
    (r"GET /api/v1/agent/sessions", lambda b,a: agent_sessions()),
    (r"GET /api/v1/agent/conversation/(.+)", lambda b,a,m: agent_conversation(m)),
    (r"DELETE /api/v1/agent/conversation/(.+)", lambda b,a,m: _json("200",{"success":True})),
    (r"GET /api/v1/agent/topics/(.+)", lambda b,a,m: agent_topics(m)),
    (r"POST /api/v1/agent/stream", lambda b,a: _json("200",{"reply":"演示模式","session_id":"demo"})),
    (r"POST /api/v1/agent/chat", lambda b,a: agent_chat(b)),
    (r"PATCH /api/v1/agent/sessions/(.+)", lambda b,a,m: _json("200",{"success":True})),
    (r"DELETE /api/v1/agent/sessions/(.+)", lambda b,a,m: _json("200",{"success":True})),
    # Knowledge
    (r"GET /api/v1/knowledge/status", lambda b,a: knowledge_status()),
    (r"POST /api/v1/knowledge/academic/search", lambda b,a: _json("200",{"results":[]})),
    # Chart / Upload / Skills / Pipeline / Paper
    (r"POST /api/v1/chart/generate", lambda b,a: chart_generate(b)),
    (r"GET /api/v1/chart/(.+)", lambda b,a,m: _json("200",{"message":"Chart ready"})),
    (r"POST /api/v1/upload", lambda b,a: upload_file(b)),
    (r"POST /api/v1/upload/(.+)", lambda b,a,m: upload_file(b)),
    (r"GET /api/v1/skills", lambda b,a: skills_list()),
    (r"POST /api/v1/skills", lambda b,a: _json("200",{"success":True})),
    (r"POST /api/v1/paper-pipeline/start", lambda b,a: pipeline_start()),
    (r"GET /api/v1/paper-pipeline/(.+)/status", lambda b,a,m: pipeline_status(m)),
    (r"GET /api/v1/paper-pipeline/(.+)/result", lambda b,a,m: _json("200",{"result":"ready"})),
    (r"POST /api/v1/paper-review/start", lambda b,a: pipeline_start()),
    (r"GET /api/v1/paper-review/(.+)/status", lambda b,a,m: pipeline_status(m)),
    (r"GET /api/v1/paper-review/(.+)/result", lambda b,a,m: _json("200",{"result":"ready"})),
    # Health / Debug
    (r"GET /api/v1/health", lambda b,a: _json("200",{"status":"ok","version":"3.0.0","smtp":bool(SMTP_USER and SMTP_PASSWORD)})),
    (r"GET /api/v1/debug", lambda b,a: _json("200",{"status":"ok","smtp_configured":bool(SMTP_USER and SMTP_PASSWORD),"routes":len(ROUTES)})),
    (r"GET /api/index", lambda b,a: _json("200",{"status":"ok"})),
]

# ── WSGI ──────────────────────────────────────────────
def application(environ, start_response):
    method=environ.get("REQUEST_METHOD","GET")
    path=(environ.get("HTTP_X_VERCEL_ORIGINAL_PATH")or environ.get("HTTP_X_FORWARDED_PATH")or environ.get("PATH_INFO","/")).rstrip("/")
    auth=environ.get("HTTP_AUTHORIZATION","")
    if method=="OPTIONS":
        start_response("200 OK",[("Access-Control-Allow-Origin","*"),("Access-Control-Allow-Methods","GET,POST,OPTIONS,PATCH,DELETE"),("Access-Control-Allow-Headers","Content-Type,Authorization")])
        return [b""]
    try:
        cl=int(environ.get("CONTENT_LENGTH",0))
        raw=environ["wsgi.input"].read(cl) if cl else b""
        body=json.loads(raw) if raw else {}
    except: body={}
    try:
        for pattern, handler in ROUTES:
            m=re.match("^"+pattern.replace("/","\\/").replace("(.+)","(.+?)").replace("([^/]+)","([^/]+?)")+"$", f"{method} {path}")
            if m:
                groups=m.groups()
                if len(groups)==0: status,hdrs,resp=handler(body,auth)
                elif len(groups)==1: status,hdrs,resp=handler(body,auth,groups[0])
                else: status,hdrs,resp=handler(body,auth,groups)
                break
        else:
            status,hdrs,resp=_json("404",{"detail":f"Not found: {method} {path}"})
    except Exception as e:
        status,hdrs,resp=_json("500",{"detail":str(e),"trace":traceback.format_exc()})
    start_response(status,hdrs)
    return [resp]

app=application
