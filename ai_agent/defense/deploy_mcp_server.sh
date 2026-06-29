#!/bin/bash

# ===========================================
# 一键部署 mcp-server 服务
# 适用于 Ubuntu/Debian/CentOS 等主流 Linux 发行版
# ===========================================

set -e  # 遇错退出

# ========= 可配置参数 =========
SERVICE_NAME="mcp-server"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
APP_DIR="/home/sj/qiangwang2025/deep-behavior-adjudication/ai-agent/security-analysis-system/defense"
APP_SOURCE="./mcp_server.py"  # 当前目录下的源文件，可修改
PYTHON_CMD="/usr/bin/python3"
HOST="0.0.0.0"
PORT="8090"
USER="root"
WORKING_DIR="$APP_DIR"

# ========= 检查是否为 root 用户 =========
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ 错误：此脚本必须以 root 权限运行！"
    echo "请使用 sudo 执行：sudo $0"
    exit 1
fi

# ========= 创建应用目录并复制脚本 =========
echo "创建应用目录：$APP_DIR"
mkdir -p "$APP_DIR"

if [ -f "$APP_SOURCE" ]; then
    echo "mcp_server.py 存在，路径为$APP_DIR"
    #cp "$APP_SOURCE" "$APP_DIR/"
else
    echo "⚠️  注意：源文件 $APP_SOURCE 不存在，跳过复制。"
    echo "请确保 $APP_DIR/mcp_server.py 已存在。"
fi

# ========= 检查 Python 是否存在 =========
if ! command -v "$PYTHON_CMD" &> /dev/null; then
    echo "❌ 错误：未找到 Python 执行命令 $PYTHON_CMD"
    echo "请先安装 Python 3："
    echo "  Ubuntu/Debian: apt install python3"
    echo "  CentOS/RHEL: yum install python3"
    exit 1
fi

# ========= 写入 systemd 服务文件 =========
echo "⚙️ 生成 systemd 服务配置：$SERVICE_FILE"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=MCP Server - Python Service
After=network.target
# Requires=postgresql.service

[Service]
User=$USER
WorkingDirectory=$WORKING_DIR
ExecStart=$PYTHON_CMD mcp_server.py --host $HOST --port $PORT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

[Install]
WantedBy=multi-user.target
EOF

echo "✅ 服务配置已写入：$SERVICE_FILE"

# ========= 重载 systemd =========
echo "������ 重载 systemd 配置..."
systemctl daemon-reexec
systemctl daemon-reload

# ========= 启动服务 =========
echo "������ 启动 $SERVICE_NAME 服务..."
systemctl start "$SERVICE_NAME"

# ========= 设置开机自启 =========
echo "������ 设置开机自启..."
systemctl enable "$SERVICE_NAME"

# ========= 显示服务状态 =========
echo "������ 服务状态："
sleep 2
systemctl status "$SERVICE_NAME" --no-pager

# ========= 显示日志（最近 10 行） =========
echo "������ 最近日志（最后 10 行）："
journalctl -u "$SERVICE_NAME" -n 10 --no-pager

# ========= 完成提示 =========
echo ""
echo "������ $SERVICE_NAME 部署完成！"
echo "✅ 服务已启动并设置为开机自启。"
echo "������ 管理命令："
echo "   启动: systemctl start $SERVICE_NAME"
echo "   停止: systemctl stop $SERVICE_NAME"
echo "   重启: systemctl restart $SERVICE_NAME"
echo "   状态: systemctl status $SERVICE_NAME"
echo "   日志: journalctl -u $SERVICE_NAME -f"

exit 0
