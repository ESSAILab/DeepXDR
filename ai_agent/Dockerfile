# ========================================
# 构建阶段：安装编译依赖和 Python 包
# ========================================
# 注意：本 Dockerfile 需在 ai_agent/ 目录下构建，构建命令：
#   cd ai_agent && docker build -t security-analysis .
# ========================================
FROM python:3.11-alpine AS builder

# 替换 Alpine 系统源为清华源（国内网络环境）
RUN sed -i 's|https\?://dl-cdn.alpinelinux.org|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apk/repositories

# 仅安装编译时依赖（不在最终镜像中保留）
RUN apk add --no-cache --virtual .build-deps \
    gcc musl-dev libffi-dev openssl-dev zlib-dev

WORKDIR /build

# 先只拷贝依赖定义文件，充分利用 Docker 层缓存
COPY pyproject.toml .

# 默认官方 PyPI，国内用户可通过 --build-arg 覆盖
ARG PIP_INDEX_URL=https://pypi.org/simple

# 注意：当前脚本假设依赖定义在标准 PEP 621 [project.dependencies] 中。
# 如需安装 extras（如 [project.optional-dependencies].mcp），需扩展此脚本。
RUN python -c "import tomllib; f=open('pyproject.toml','rb'); deps=tomllib.load(f)['project']['dependencies']; open('requirements.txt','w').write('\n'.join(deps))" && \
    pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt && \
    rm requirements.txt

# ========================================
# 运行阶段：最小化镜像，仅保留运行时所需内容
# ========================================
FROM python:3.11-alpine AS runner

# OCI 标准镜像元数据
LABEL org.opencontainers.image.title="Security Analysis System" \
      org.opencontainers.image.description="AI-powered threat hunting based on MITRE ATT&CK" \
      org.opencontainers.image.licenses="MIT"

# 代理配置（构建参数，不传则无影响）
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

ENV http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 替换 Alpine 系统源为清华源（国内网络环境）
RUN sed -i 's|https\?://dl-cdn.alpinelinux.org|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apk/repositories

# 运行时保留必要的系统包
RUN apk add --no-cache ca-certificates tzdata

# 创建非 root 用户
RUN addgroup -g 10001 appgroup && \
    adduser -u 10001 -G appgroup -s /bin/sh -D appuser

WORKDIR /app
RUN chown appuser:appgroup /app

# 直接 COPY builder 的系统级 Python 包和可执行文件
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 拷贝应用源码和数据，并修正属主
# 构建上下文为 ai_agent/ 目录本身，所以用 . 表示当前目录
COPY --chown=appuser:appgroup . /app/ai_agent

# 显式确保数据目录存在且可读。MITRE RAG 使用镜像内置的 ATT&CK STIX 数据。
RUN mkdir -p /app/ai_agent/data/v18.1 && chown -R appuser:appgroup /app/ai_agent/data

# 确保日志目录存在且对非 root 用户可写
RUN mkdir -p /app/logs && chown appuser:appgroup /app/logs

# 暴露服务端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 切换非 root 用户
USER appuser

WORKDIR /app/ai_agent

# 使用 exec 形式确保 PID 1 是 python 进程，正确接收 SIGTERM
CMD ["python", "main.py"]
