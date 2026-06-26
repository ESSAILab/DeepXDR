FROM python:3.11-alpine

# 设置工作目录
WORKDIR /app

# 安装系统依赖（alpine版本）
RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev

# 设置Python线程优化
ENV PYTHONOPTIMIZE=1
ENV PYTHONUNBUFFERED=1

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 精确复制应用代码（避免复制敏感文件）
COPY run_dashboard.py .
COPY src/ ./src/

# 暴露端口
EXPOSE 30003

# 设置环境变量
ENV HOST=0.0.0.0
ENV PORT=30003

# 启动应用
CMD ["python3", "run_dashboard.py"]