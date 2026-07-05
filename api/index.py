"""
Vercel Python Serverless Function — ScholarMind Backend API

Vercel 约定：api/ 目录下的 .py 文件自动成为 Python Function。
本文件作为轻量包装，导入 FastAPI app 并暴露给 Vercel ASGI handler。

环境变量（Vercel Dashboard → Settings → Environment Variables 设置）：
  ENVIRONMENT=production
  JWT_SECRET_KEY=<32+ character secret>
  DEEPSEEK_API_KEY=<your key>
  DB_PATH=/tmp/scholarmind.db
  CHROMA_DIR=/tmp/chroma
  RATE_LIMIT_ENABLED=false
"""
import os as _os
import sys as _sys

# 将 repo root 加入 Python path，确保 `from src.backend.xxx` 导入正常工作
_repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)

# Vercel 环境：确保关键配置通过环境变量覆盖
_os.environ.setdefault("ENVIRONMENT", "production")
_os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
_os.environ.setdefault("DB_PATH", "/tmp/scholarmind.db")
_os.environ.setdefault("CHROMA_DIR", "/tmp/chroma")

from src.backend.app import create_app

app = create_app()
