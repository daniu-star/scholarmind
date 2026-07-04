# ScholarMind Backend Dockerfile
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

# 复制应用代码
COPY src/backend/ ./src/backend/
COPY prototypes/ ./prototypes/
COPY data/ ./data/
# P0 修复: 不复制 .env 到镜像中，环境变量通过 docker-compose / K8s Secrets 注入

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash scholarmind && \
    chown -R scholarmind:scholarmind /app
USER scholarmind

EXPOSE 8000

# 使用工厂模式启动
CMD ["uvicorn", "src.backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
