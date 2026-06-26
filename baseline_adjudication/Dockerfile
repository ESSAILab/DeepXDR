# 使用 Python 3.11 Alpine 作为基础镜像
FROM python:3.11-alpine

# 安装 bash
RUN apk add --no-cache bash

# 设置工作目录
WORKDIR /app

# 拷贝当前目录下的文件到容器的 /app 目录
COPY . /app/

# 切换到 app目录
WORKDIR /app/

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 启动应用（使用 nohup 后台运行）
CMD ["python", "anomaly_detector.py"]
