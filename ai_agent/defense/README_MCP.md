# MCP Server 部署指南

## 🎯 功能概述

MCP (Model Communication Protocol) Server 提供安全干预操作的服务器端实现，支持以下功能：

- **IP地址阻断/解除阻断** - 使用iptables实现
- **监控增强** - 记录监控请求
- **资源隔离** - 记录隔离请求
- **阻断列表查看** - 查看当前被阻断的IP

- **设置全局工作目录** - 进入指定文件目录
- **执行bash命令** - 执行 bash 命令

## 🚀 快速启动

### 方法1：直接运行
```bash
# 启动MCP服务器（需要root权限）
sudo python3 ai_agent/mcp_server.py

# 或使用自动端口
sudo python3 ai_agent/mcp_server.py --auto-port
```

### 方法2：使用启动脚本,指定主机和端口
```bash
# 指定监听地址和端口
sudo python3 ai_agent/mcp_server.py --host 0.0.0.0 --port 8080
```

### 方法3：使用守护进程
把mcp-server.service放到需要运行此服务的主机文件目录/etc/systemd/system/下，然后使能进程
```bash
systemctl daemon-reload
systemctl enable mcp-server
systemctl start mcp-server
```

## 📋 可用工具

### 1. security.block_ip_port
**功能**: 阻断指定IP地址

**参数**:
- `ip` (string, required): IP地址
- `port` (string, optional): 端口，如果是封掉IP的所有端口此参数设置为all
- `reason` (string, optional): 阻断原因

**示例**:
```bash
curl -X POST http://localhost:8080/tools/execute \
  -H "Content-Type: application/json" \
  -d '{"tool": "security.block_ip_port", "arguments": {"ip": "192.168.1.100", "port": "8080",  "reason": "威胁检测"}}'
```

### 2. security.unblock_ip_port
**功能**: 解除IP地址阻断

**参数**:
- `ip` (string, required): IP地址
- `port` (string, optional): 端口，如果是封掉IP的所有端口此参数设置为all

**示例**:
```bash
curl -X POST http://localhost:8080/tools/execute \
  -H "Content-Type: application/json" \
  -d '{"tool": "security.unblock_ip_port", "arguments": {"ip": "192.168.1.100", "port": "8080"}}'
```

### 3. security.list_blocked_ips
**功能**: 查看当前被阻断的IP列表

**示例**:
```bash
curl http://localhost:8080/tools/execute \
  -H "Content-Type: application/json" \
  -d '{"tool": "security.list_blocked_ips"}'
```

### 4. security.increase_monitoring
**功能**: 增加对目标的监控

**参数**:
- `target` (string, required): 监控目标
- `frequency` (string, optional): 监控频率，默认"high"
- `duration` (string, optional): 持续时间，默认"30m"

**示例**:
```bash
curl -X POST http://localhost:8080/tools/execute \
  -H "Content-Type: application/json" \
  -d '{"tool": "security.increase_monitoring", "arguments": {"target": "web-server"}}'
```

### 5. security.isolate_resource
**功能**: 隔离可疑资源

**参数**:
- `resource` (string, required): 资源标识符
- `reason` (string, optional): 隔离原因

**示例**:
```bash
curl -X POST http://localhost:8080/tools/execute \
  -H "Content-Type: application/json" \
  -d '{"tool": "security.isolate_resource", "arguments": {"resource": "container_123", "reason": "威胁检测"}}'
```

** bash 命令相关**
  1. 设置工作目录：
  curl -X POST http://localhost:8081/tools/execute \
    -H "Content-Type: application/json" \
    -d '{"tool": "bash.set_cwd", "arguments": {"path": "/tmp"}}'

  2. 执行bash命令：
  curl -X POST http://localhost:8081/tools/execute \
    -H "Content-Type: application/json" \
    -d '{"tool": "bash.execute_bash", "arguments": {"command": "ls -la"}}'

  3. 获取工具列表：
  curl http://localhost:8081/tools

  4. 获取特定工具schema：
  curl http://localhost:8081/tools/schema/bash.execute_bash

## 🔧 配置集成

### 威胁分析系统配置
在 `.env` 文件中设置：

```bash
# 启用MCP客户端
ENABLE_MCP=true
MCP_SERVER_URL=http://localhost:8080/mcp

# 启用干预功能
ENABLE_INTERVENTION=true
AUTO_BLOCK_THRESHOLD=高
```

## 📊 测试方法

### 1. 健康检查
```bash
curl http://localhost:8080/health
```

### 2. 查看可用工具
```bash
curl http://localhost:8080/tools
```

### 3. 查看工具模式
```bash
curl http://localhost:8080/tools/schema/security.block_ip_port
```

## ⚠️ 注意事项

1. **权限要求**: IP阻断功能需要root权限
   - 使用 `sudo` 运行服务器
   - 或配置iptables权限

2. **防火墙配置**:
   - 确保iptables已安装
   - 检查防火墙状态: `sudo iptables -L`

3. **日志文件**:
   - 阻断记录: `/tmp/security_blocks.log`
   - 监控记录: `/tmp/monitoring_requests.log`
   - 隔离记录: `/tmp/resource_isolation.log`

4. **端口占用**:
   - 默认使用8080端口
   - 如被占用，使用 `--auto-port` 自动选择端口

## 🐛 故障排除

### 权限问题
```bash
# 检查是否为root
whoami

# 使用sudo运行
sudo python3 ai_agent/mcp_server.py

# 或配置sudo权限
sudo visudo
# 添加: your_user ALL=(ALL) NOPASSWD: /sbin/iptables
```

### 端口占用
```bash
# 检查端口占用
netstat -tuln | grep :8080

# 使用其他端口
python3 ai_agent/mcp_server.py --port 8081
```

### 连接测试
```bash
# 测试MCP服务器
python3 -c "
from ai_agent.mcp_client import MCPClient
client = MCPClient('http://localhost:8080/mcp')
print(client.health_check())
print(client.list_tools())
"
```

## 🔄 集成测试

启动完整测试环境：

```bash
# 1. 启动MCP服务器
./start_mcp_server.sh

# 2. 在另一个终端，启动威胁分析系统
python3 ai_agent/main.py

# 3. 测试干预功能
python3 -c "
from ai_agent.intervention_engine import get_intervention_engine
from ai_agent.lttp_graph import LTTPAnalysis

# 模拟威胁分析结果
class MockThreat:
    def __init__(self):
        self.risk_level = '高'
        self.summary = '测试威胁'
        self.objective = '测试目标'
        self.attack_chain = ['step1', 'step2']
        self.confidence = 0.9

engine = get_intervention_engine()
result = engine.evaluate_and_act(MockThreat())
print('干预结果:', result)
"
```