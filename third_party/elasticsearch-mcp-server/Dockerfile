# Dockerfile for elasticsearch-mcp-server
# 使用官方 Python 3.11 镜像作为基础
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 配置 pip 使用国内镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv 包管理工具
RUN pip install --no-cache-dir uv

# 复制项目文件
COPY pyproject.toml uv.lock ./
COPY LICENSE ./
COPY README.md ./
COPY src/ ./src/

# 使用 uv 安装依赖（使用清华镜像源）
RUN uv pip install --system --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e .

# 设置环境变量默认值
ENV PYTHONUNBUFFERED=1
ENV ELASTICSEARCH_HOSTS=""
ENV VERIFY_CERTS="false"
ENV DISABLE_HIGH_RISK_OPERATIONS="true"
ENV EQL_MAX_FIELD_LENGTH="1000"
ENV EQL_MAX_LIST_ITEMS="5"

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "src.server", "elasticsearch-mcp-server", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000", "--path", "/mcp"]
