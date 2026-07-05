# ScholarMind Backend Dockerfile (Railway/PaaS 适配版)
# 多阶段构建：builder 安装依赖 → runtime 运行
FROM python:3.12-slim AS builder

WORKDIR /app
COPY src/backend/requirements.txt .

# 安装依赖到系统目录（非 --user），保证非 root 用户也能访问
RUN pip install --no-cache-dir -r requirements.txt

# ── Runtime ──
FROM python:3.12-slim

WORKDIR /app

# 从 builder 复制系统级安装的包与可执行脚本（/usr/local/lib + /usr/local/bin）
# 注意：COPY 目录是合并而非替换，runtime 镜像原有的 pip/python 仍可用
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 仅复制后端代码（不复制 prototypes/、data/）
# - prototypes/ 由 Vercel 端构建，后端容器不需要
# - data/ 是运行时挂载的持久化卷，构建期不需要
COPY src/backend/ ./src/backend/

# 预创建数据卷子目录（避免首次启动报错）
# 注意：Railway 挂载 volume 到 /app/data 时会以 root 属主覆盖构建期权限，
# 因此容器需以 root 运行（不设 USER），确保能写入 volume 挂载点。
# 安全性由 Railway 容器隔离保证；后续可通过 entrypoint+gosu 降权优化。
RUN mkdir -p /app/data/uploads /app/data/chroma /app/data/skills \
             /app/data/conversations /app/data/charts /app/logs

EXPOSE 8000

# Railway/PaaS 通过 $PORT 环境变量指定监听端口；本地 docker run 默认 8000
# 注意：railway.json 已移除 startCommand，由 Railway service-level startCommand 控制
# - backend:        python -m uvicorn src.backend.app:create_app --factory --host 0.0.0.0 --port $PORT
# - celery-worker:  python -m celery -A src.backend.scheduler.celery_app worker -l info -Q celery,charts
# - celery-beat:    python -m celery -A src.backend.scheduler.celery_app beat -l info
CMD ["sh", "-c", "uvicorn src.backend.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
