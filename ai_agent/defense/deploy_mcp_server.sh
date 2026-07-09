#!/usr/bin/env bash

# ===========================================
# 一键部署 mcp-server 服务
# 适用于 Ubuntu/Debian/CentOS 等主流 Linux 发行版
# ===========================================

set -euo pipefail
trap 'echo "错误：部署失败，出错行：$LINENO" >&2' ERR

# ========= 可配置参数 =========
SERVICE_NAME="${SERVICE_NAME:-mcp-server}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$SCRIPT_DIR}"
APP_SOURCE="${APP_SOURCE:-$APP_DIR/mcp_server.py}"
PYTHON_CMD="${PYTHON_CMD:-$(command -v python3 || true)}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8090}"
RUN_USER="${RUN_USER:-root}"
WORKING_DIR="${WORKING_DIR:-$APP_DIR}"
BLOCKED_IPS_FILE="${BLOCKED_IPS_FILE:-/etc/nginx/blocked_ips.conf}"

# ========= 检查是否为 root 用户 =========
if [ "$(id -u)" -ne 0 ]; then
    echo "错误：此脚本必须以 root 权限运行！"
    echo "请使用 sudo 执行：sudo $0"
    exit 1
fi

# ========= 检查 systemd =========
if ! command -v systemctl >/dev/null 2>&1; then
    echo "错误：未找到 systemctl，请在 systemd 环境中运行此脚本。"
    exit 1
fi

# ========= 检查应用目录和服务脚本 =========
if [ ! -d "$APP_DIR" ]; then
    echo "错误：应用目录不存在：$APP_DIR"
    exit 1
fi

if [ ! -f "$APP_SOURCE" ]; then
    echo "错误：未找到 MCP 服务脚本：$APP_SOURCE"
    exit 1
fi
echo "使用 MCP 服务脚本：$APP_SOURCE"

# ========= 检查 Python 是否存在 =========
if [ -z "$PYTHON_CMD" ] || [ ! -x "$PYTHON_CMD" ]; then
    echo "错误：未找到可执行的 Python 3。"
    echo "请先安装 Python 3："
    echo "  Ubuntu/Debian: apt install python3"
    echo "  CentOS/RHEL: yum install python3"
    exit 1
fi

# ========= 检查 nginx 阻断配置文件 =========
if ! command -v nginx >/dev/null 2>&1; then
    echo "警告：未找到 nginx 命令。MCP 服务可启动，但阻断/解除阻断功能会在重载 nginx 时失败。"
else
    mkdir -p "$(dirname "$BLOCKED_IPS_FILE")"
    touch "$BLOCKED_IPS_FILE"
    if ! nginx -t; then
        echo "错误：nginx 配置测试失败，请先修复 nginx 配置。"
        exit 1
    fi
fi

# ========= 写入 systemd 服务文件 =========
echo "生成 systemd 服务配置：$SERVICE_FILE"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=MCP Server - Python Service
After=network.target
# Requires=postgresql.service

[Service]
User=$RUN_USER
WorkingDirectory=$WORKING_DIR
ExecStart=$PYTHON_CMD $APP_SOURCE --host $HOST --port $PORT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

[Install]
WantedBy=multi-user.target
EOF

echo "服务配置已写入：$SERVICE_FILE"

# ========= 重载 systemd =========
echo "重载 systemd 配置..."
systemctl daemon-reload

# ========= 设置开机自启 =========
echo "设置开机自启..."
systemctl enable "$SERVICE_NAME"

# ========= 启动服务 =========
echo "启动 $SERVICE_NAME 服务..."
systemctl restart "$SERVICE_NAME"

# ========= 显示服务状态 =========
echo "服务状态："
sleep 2
systemctl status "$SERVICE_NAME" --no-pager

# ========= 显示日志（最近 10 行） =========
echo "最近日志（最后 10 行）："
journalctl -u "$SERVICE_NAME" -n 10 --no-pager

# ========= 完成提示 =========
echo ""
echo "$SERVICE_NAME 部署完成！"
echo "服务已启动并设置为开机自启。"
echo "管理命令："
echo "   启动: systemctl start $SERVICE_NAME"
echo "   停止: systemctl stop $SERVICE_NAME"
echo "   重启: systemctl restart $SERVICE_NAME"
echo "   状态: systemctl status $SERVICE_NAME"
echo "   日志: journalctl -u $SERVICE_NAME -f"

exit 0
