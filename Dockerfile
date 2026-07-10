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

# 复制 Pipeline 技能到 /app/skills_builtin/（非 volume 挂载点，不会被覆盖）
# 同时复制到 /app/data/skills/（兼容旧逻辑，volume 挂载时可能被覆盖）
COPY skills/cyclical-paper-generation/ /app/skills_builtin/cyclical-paper-generation/
COPY skills/cyclical-paper-review/ /app/skills_builtin/cyclical-paper-review/
COPY skills/cyclical-paper-generation/ /app/data/skills/cyclical-paper-generation/
COPY skills/cyclical-paper-review/ /app/data/skills/cyclical-paper-review/

# 设置技能目录环境变量（pipeline_llm_bridge / paper_pipeline_service 统一使用）
ENV SKILLS_DIR=/app/data/skills
# 备用技能目录（volume 挂载覆盖 /app/data 时使用）
ENV SKILLS_BUILTIN_DIR=/app/skills_builtin

# 预创建数据卷子目录（避免首次启动报错）
RUN mkdir -p /app/data/uploads /app/data/chroma /app/data/skills \
             /app/data/conversations /app/data/charts /app/logs

EXPOSE 8000

# Railway/PaaS 通过 $PORT 环境变量指定监听端口；本地 docker run 默认 8000
CMD ["sh", "-c", "python -m src.backend.scripts.prestart && uvicorn src.backend.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
