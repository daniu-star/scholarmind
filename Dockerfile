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
COPY src/backend/ ./src/backend/

# 复制 Pipeline 技能到 /app/skills_builtin/（非 volume 挂载点）
# Railway 挂载 volume 到 /app/data 时会覆盖构建期 /app/data 的内容，
# 因此技能必须放到 /app/skills_builtin/，启动时同步到 /app/data/skills/
COPY skills/cyclical-paper-generation/ /app/skills_builtin/cyclical-paper-generation/
COPY skills/cyclical-paper-review/ /app/skills_builtin/cyclical-paper-review/

# 设置技能目录环境变量
ENV SKILLS_DIR=/app/data/skills

EXPOSE 8000

# 启动时先同步内置技能到 volume 挂载点，再启动应用
CMD ["sh", "-c", "mkdir -p /app/data/skills /app/data/uploads /app/data/chroma /app/data/conversations /app/data/charts /app/logs && cp -rn /app/skills_builtin/* /app/data/skills/ 2>/dev/null; python -m src.backend.scripts.prestart && uvicorn src.backend.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
