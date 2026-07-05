# ScholarMind Backend Dockerfile (Railway/PaaS 适配版)
# 多阶段构建：builder 安装依赖 → runtime 运行
FROM python:3.12-slim AS builder

WORKDIR /app
COPY src/backend/requirements.txt .

# 安装构建依赖
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Runtime ──
FROM python:3.12-slim

WORKDIR /app

# 从 builder 复制已安装的包
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# 仅复制后端代码（不复制 prototypes/、data/）
# - prototypes/ 由 Vercel 端构建，后端容器不需要
# - data/ 是运行时挂载的持久化卷，构建期不需要
COPY src/backend/ ./src/backend/

# 创建非 root 用户 + 预创建数据卷子目录（避免首次启动报错）
RUN useradd --create-home --shell /bin/bash scholarmind && \
    mkdir -p /app/data/uploads /app/data/chroma /app/data/skills \
             /app/data/conversations /app/data/charts /app/logs && \
    chown -R scholarmind:scholarmind /app
USER scholarmind

EXPOSE 8000

# Railway/PaaS 通过 $PORT 环境变量指定监听端口；本地 docker run 默认 8000
CMD ["sh", "-c", "uvicorn src.backend.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
