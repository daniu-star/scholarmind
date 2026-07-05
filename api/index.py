"""
Vercel Python Serverless Function — ScholarMind Backend API

Vercel 约定：api/ 目录下的 .py 文件自动成为 Python Function。
本文件作为轻量包装，导入 FastAPI app 并暴露给 Vercel ASGI handler。

重要：不要设置 ENVIRONMENT=production！validate_production() 会强制要求
PostgreSQL 并拒绝 SQLite，导致启动崩溃。保持默认 "development"。

Vercel Dashboard 需设置的环境变量：
  JWT_SECRET_KEY=<32+ 字符密钥>
  DEEPSEEK_API_KEY=<你的 DeepSeek API key>
"""
import os as _os
import sys as _sys

# 将 repo root 加入 Python path，确保 `from src.backend.xxx` 导入正常工作
_repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)

# Vercel 环境覆盖：使用 /tmp 目录（唯一可写位置），关闭需要外部服务的功能
_os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
_os.environ.setdefault("DB_PATH", "/tmp/scholarmind.db")
_os.environ.setdefault("CHROMA_DIR", "/tmp/chroma")
_os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/scholarmind_orm.db")

from src.backend.app import create_app

app = create_app()
