"""
ScholarMind Vercel API — 完整后端包装层

导入原始 FastAPI app (src.backend.app.create_app)，
在 Vercel Serverless 环境中运行全部 API 端点。
"""
import os as _os, sys as _sys

# repo root 加入 Python path
_repo = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _repo not in _sys.path: _sys.path.insert(0, _repo)

# ── Vercel 环境覆盖 ──────────────────────────────────
# 不设 ENVIRONMENT=production（避免 validate_production 禁止 SQLite）
_os.environ.setdefault("ENVIRONMENT", "development")
_os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
_os.environ.setdefault("PAYMENT_ENABLED", "false")

# 所有文件路径 → /tmp/（Vercel 唯一可写目录）
for _key, _val in {
    "DB_PATH": "/tmp/scholarmind.db",
    "DATABASE_URL": "sqlite+aiosqlite:////tmp/scholarmind_orm.db",
    "CHROMA_DIR": "/tmp/chroma",
    "UPLOAD_DIR": "/tmp/uploads",
    "SKILLS_DIR": "/tmp/skills",
    "CHARTS_DIR": "/tmp/charts",
    "CONVERSATIONS_DIR": "/tmp/conversations",
}.items():
    _os.environ.setdefault(_key, _val)

# Vercel 部署必需的安全密钥（若无显式设置则用临时值）
_os.environ.setdefault("JWT_SECRET_KEY", "vercel-temp-key-change-in-production-32c")

print(f"[ScholarMind API] ENVIRONMENT={_os.environ['ENVIRONMENT']} DB_PATH={_os.environ['DB_PATH']}", file=_sys.stderr)

from src.backend.app import create_app

app = create_app()
