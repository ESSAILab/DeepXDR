#!/usr/bin/env python3
"""
MCP (Model Communication Protocol) Server
提供安全干预操作的服务器端实现
"""

import ipaddress
import json
import logging
import subprocess
import os
import tempfile
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import socket

# 添加Python路径以便导入utils模块
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.utils.validation import validate_ip_with_reason

logger = logging.getLogger('mcp_server')

# 配置日志输出到当前目录的文件
log_file = os.path.join(os.getcwd(), 'mcp_server.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()  # 同时保留控制台输出
    ]
)
logger.info(f"日志文件位置: {log_file}")

class SecurityTools:
    """安全工具集合"""

    BLOCKED_IPS_FILE = "/etc/nginx/blocked_ips.conf"

    _block_schedule = {}  # 存储阻断计划 {ip: {'port': port, 'expiry': datetime, 'reason': reason, 'timer': threading.Timer}}
    _persistence_file = "/tmp/security_blocks_schedule.json"
    
    @staticmethod
    def _read_blocked_ips(file_path: str) -> set:
        """读取已阻断的IP集合"""
        if not os.path.exists(file_path):
            return set()
        try:
            blocked_ips = set()
            with open(file_path, 'r') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        parts = stripped.split()
                        if len(parts) >= 2 and parts[1] == '1;':
                            blocked_ips.add(parts[0])
            return blocked_ips
        except Exception as e:
            logger.error(f"读取阻断配置失败: {e}")
            return set()

    @staticmethod
    def _remove_ip_from_file(ip: str, file_path: str) -> None:
        """从阻断文件中删除指定IP"""
        with open(file_path, 'r') as f:
            lines = f.readlines()
        with open(file_path, 'w') as f:
            target = f"{ip} 1;\n"
            f.writelines(line for line in lines if line != target)

    @staticmethod
    def _reload_nginx_with_rollback(ip: str, file_path: str) -> bool:
        """重载nginx配置，失败时回滚IP写入"""
        try:
            subprocess.run(["nginx", "-s", "reload"], capture_output=True, text=True, check=True)
            return True
        except subprocess.CalledProcessError:
            logger.error(f"nginx重载失败，回滚IP阻断规则: {ip}")
            SecurityTools._remove_ip_from_file(ip, file_path)
            return False

    @staticmethod
    def _handle_block_file_operation(ip: str, file_path: str) -> bool:
        """处理阻断文件操作：读取现有IP，若不存在则添加并重载nginx"""
        blocked_ips = SecurityTools._read_blocked_ips(file_path)

        if ip in blocked_ips:
            logger.info(f"IP阻断规则已存在: {ip}，跳过添加")
            return True

        try:
            with open(file_path, 'a') as f:
                f.write(f"{ip} 1;\n")
            logger.info(f"添加IP阻断规则: {ip}")
        except Exception as e:
            logger.error(f"写入阻断配置失败: {e}")
            return False

        if not SecurityTools._reload_nginx_with_rollback(ip, file_path):
            return False

        logger.info("nginx配置已重载")
        return True

    @staticmethod
    def _setup_block_timer(ip: str, port: str, expiry_time: datetime, reason: str) -> None:
        """设置临时阻断定时器"""
        key = f"{ip}:{port}"
        seconds = (expiry_time - datetime.now()).total_seconds()

        if key in SecurityTools._block_schedule:
            old_timer = SecurityTools._block_schedule[key].get('timer')
            if old_timer:
                old_timer.cancel()

            timer = threading.Timer(seconds, SecurityTools._auto_unblock, args=[ip, port])
            timer.start()

            SecurityTools._block_schedule[key].update({
                'expiry': expiry_time.isoformat(),
                'reason': reason,
                'timer': timer
            })

            logger.info(f"更新IP阻断时间: {ip}:{port}，新到期时间: {expiry_time.isoformat()}")
        else:
            timer = threading.Timer(seconds, SecurityTools._auto_unblock, args=[ip, port])
            timer.start()
            SecurityTools._block_schedule[key] = {
                'ip': ip,
                'port': port,
                'expiry': expiry_time.isoformat(),
                'reason': reason,
                'timer': timer
            }

class SecurityTools:
    """安全工具集合"""
    
    _block_schedule = {}  # 存储阻断计划 {ip: {'port': port, 'expiry': datetime, 'reason': reason, 'timer': threading.Timer}}
    _persistence_file = "/tmp/security_blocks_schedule.json"
    _blocked_ips_file = "/etc/nginx/blocked_ips.conf"

    @staticmethod
    def _normalize_block_address(ip: str) -> str:
        """验证并规范化可写入nginx阻断配置的IP/CIDR。"""
        if not isinstance(ip, str):
            raise ValueError("IP地址必须是字符串")

        if ip != ip.strip() or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in ip):
            raise ValueError("IP地址不能包含空白字符或控制字符")

        if any(ch in ip for ch in (';', '{', '}')):
            raise ValueError("IP地址不能包含nginx配置控制字符")

        try:
            if "/" in ip:
                network = ipaddress.ip_network(ip, strict=True)
                min_prefixlen = 24 if network.version == 4 else 64
                if network.prefixlen < min_prefixlen:
                    raise ValueError(f"CIDR网段范围过大，IPv{network.version}前缀长度必须至少为/{min_prefixlen}")
                return str(network)
            return str(ipaddress.ip_address(ip))
        except ValueError as exc:
            raise ValueError("必须是有效的IPv4/IPv6地址或允许范围内的CIDR网段") from exc

    @staticmethod
    def _run_nginx_command(args):
        """运行nginx命令并在失败时返回可读错误。"""
        return subprocess.run(args, capture_output=True, text=True, check=True)

    @staticmethod
    def _commit_nginx_blocklist(blocked_ips_file: str, lines) -> None:
        """原子写入阻断配置，测试nginx配置，失败时回滚。"""
        directory = os.path.dirname(blocked_ips_file) or "."
        original_content = None
        file_existed = os.path.exists(blocked_ips_file)
        if file_existed:
            with open(blocked_ips_file, 'r') as f:
                original_content = f.read()

        fd, temp_path = tempfile.mkstemp(prefix=".blocked_ips.", suffix=".conf", dir=directory, text=True)
        try:
            with os.fdopen(fd, 'w') as f:
                for line in lines:
                    f.write(line.rstrip('\n') + '\n')
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_path, blocked_ips_file)
            try:
                SecurityTools._run_nginx_command(["nginx", "-t"])
                SecurityTools._run_nginx_command(["nginx", "-s", "reload"])
            except Exception:
                if file_existed:
                    with open(blocked_ips_file, 'w') as f:
                        f.write(original_content)
                else:
                    try:
                        os.remove(blocked_ips_file)
                    except FileNotFoundError:
                        pass
                raise
        finally:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
    
    @staticmethod
    def block_ip_port(ip: str, port: str, duration: str = "permanent", reason: str = "Security threat") -> Dict[str, Any]:
        """使用nginx配置文件阻断IP地址"""
        try:
            # 首先验证并规范化IP/CIDR，避免将未受信任的文本写入nginx配置。
            try:
                normalized_ip = SecurityTools._normalize_block_address(ip)
            except ValueError as e:
                logger.warning(f"无效的IP地址 '{ip}': {e}")
                return {
                    "status": "error",
                    "message": f"IP地址无效: {e}",
                    "ip": ip
                }

            ip = normalized_ip
            blocked_ips_file = SecurityTools._blocked_ips_file
            
            # 解析时间期限
            expiry_time = None
            if duration != "permanent":
                try:
                    # 支持格式：30m, 2h, 1d, 7d
                    if duration.endswith('m'):
                        minutes = int(duration[:-1])
                        expiry_time = datetime.now() + timedelta(minutes=minutes)
                    elif duration.endswith('h'):
                        hours = int(duration[:-1])
                        expiry_time = datetime.now() + timedelta(hours=hours)
                    elif duration.endswith('d'):
                        days = int(duration[:-1])
                        expiry_time = datetime.now() + timedelta(days=days)
                    else:
                        return {
                            "status": "error",
                            "message": "无效的时间格式，请使用：30m, 2h, 1d, 7d 或 permanent"
                        }
                except ValueError:
                    return {
                        "status": "error",
                        "message": "无效的时间格式，请使用：30m, 2h, 1d, 7d 或 permanent"
                    }
            
            # 读取现有blocked IPs
            blocked_ips = {}
            config_lines = []
            if os.path.exists(blocked_ips_file):
                try:
                    with open(blocked_ips_file, 'r') as f:
                        for raw_line in f:
                            config_lines.append(raw_line.rstrip('\n'))
                            line = raw_line.strip()
                            if line and not line.startswith('#'):
                                parts = line.split()
                                if len(parts) >= 2 and parts[1] == '1;':
                                    blocked_ips[parts[0]] = True
                except Exception as e:
                    logger.error(f"读取blocked_ips.conf失败: {e}")
            
            # 检查IP是否已存在
            if ip in blocked_ips:
                logger.info(f"IP阻断规则已存在: {ip}，跳过添加")
            else:
                # 添加新IP到blocked_ips.conf，先测试nginx配置，失败时回滚。
                try:
                    updated_lines = config_lines + [f"{ip} 1;"]
                    SecurityTools._commit_nginx_blocklist(blocked_ips_file, updated_lines)
                    logger.info(f"添加IP阻断规则: {ip}")
                    logger.info(f"nginx配置已测试并重载")
                    
                except Exception as e:
                    logger.error(f"写入blocked_ips.conf、测试或重载nginx失败: {e}")
                    return {
                        "status": "error",
                        "ip": ip,
                        "error": str(e)
                    }
            
            # 如果是临时阻断，设置定时器
            timer = None
            if expiry_time:
                SecurityTools._setup_block_timer(ip, port, expiry_time, reason)

            # 记录阻断日志
            expiry_str = expiry_time.isoformat() if expiry_time else "permanent"
            logger.info("BLOCKED %s - %sport - %s - expires: %s", ip, port, reason, expiry_str)

            return {
                "status": "success",
                "ip": ip,
                "port": port,
                "reason": reason,
                "duration": duration,
                "expiry": expiry_time.isoformat() if expiry_time else "permanent",
                "command": f"write validated block entry to {blocked_ips_file}; nginx -t; nginx -s reload",
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"阻断IP失败: {e}")
            return {
                "status": "error",
                "ip": ip,
                "error": str(e)
            }

    @staticmethod
    def _save_schedule():
        """保存阻断计划到文件"""
        try:
            schedule_data = {}
            for key, info in SecurityTools._block_schedule.items():
                # 只保存定时器信息，不保存timer对象
                schedule_data[key] = {
                    'ip': info['ip'],
                    'port': info['port'],
                    'expiry': info['expiry'],
                    'reason': info['reason']
                }
            
            with open(SecurityTools._persistence_file, 'w') as f:
                json.dump(schedule_data, f, indent=2)
        except Exception as e:
            logger.error(f"保存阻断计划失败: {e}")
    
    @staticmethod
    def _load_schedule():
        """从文件加载阻断计划"""
        try:
            if not os.path.exists(SecurityTools._persistence_file):
                return
                
            with open(SecurityTools._persistence_file, 'r') as f:
                schedule_data = json.load(f)
            
            current_time = datetime.now()
            for key, info in schedule_data.items():
                expiry_time = datetime.fromisoformat(info['expiry'])
                
                # 如果已经过期，跳过
                if expiry_time <= current_time:
                    continue
                
                # 重新创建定时器
                remaining_seconds = (expiry_time - current_time).total_seconds()
                timer = threading.Timer(remaining_seconds, SecurityTools._auto_unblock, 
                                      args=[info['ip'], info['port']])
                timer.start()
                
                SecurityTools._block_schedule[key] = {
                    'ip': info['ip'],
                    'port': info['port'],
                    'expiry': info['expiry'],
                    'reason': info['reason'],
                    'timer': timer
                }
                
                logger.info(f"重新加载计划阻断: {info['ip']}:{info['port']} 到期时间: {info['expiry']}")
                
        except Exception as e:
            logger.error(f"加载阻断计划失败: {e}")
    
    @staticmethod
    def _auto_unblock(ip: str, port: str):
        """自动解除IP地址阻断（内部使用）"""
        try:
            logger.info(f"自动解除IP阻断: {ip}:{port}")
            SecurityTools.unblock_ip_port(ip, port, from_auto=True)
            
            # 从计划中移除
            key = f"{ip}:{port}"
            if key in SecurityTools._block_schedule:
                del SecurityTools._block_schedule[key]
                
            # 保存更新后的计划
            SecurityTools._save_schedule()
                
        except Exception as e:
            logger.error(f"自动解除阻断失败: {e}")
    
    @staticmethod
    def unblock_ip_port(ip: str, port: str, from_auto: bool = False) -> Dict[str, Any]:
        """解除IP地址阻断（从nginx配置文件中删除）"""
        try:
            # 首先验证IP地址的有效性 (可选验证，因为可能是之前未经检查就保存的IP)
            valid, validation_reason = validate_ip_with_reason(ip)
            if not valid:
                logger.warning(f"尝试解除无效IP地址 '{ip}': {validation_reason}")
                # 这里只是警告，继续执行解封，因为我们可能是在清理旧的无效条目

            blocked_ips_file = SecurityTools.BLOCKED_IPS_FILE

            try:
                result = SecurityTools._remove_ip_from_blocklist(ip, blocked_ips_file)
                if result is None:
                    return {
                        "status": "error",
                        "ip": ip,
                        "message": "blocked_ips.conf文件不存在"
                    }
                if result is False:
                    return {
                        "status": "warning",
                        "ip": ip,
                        "message": "IP阻断规则不存在，可能已被删除"
                    }
            except Exception as e:
                logger.error(f"更新blocked_ips.conf或重载nginx失败: {e}")
                return {
                    "status": "error",
                    "ip": ip,
                    "error": str(e)
                }

            action_type = "AUTO_UNBLOCKED" if from_auto else "UNBLOCKED"
            logger.info("%s %s:%s", action_type, ip, port)

            # 如果是手动解除，取消相应的定时器
            if not from_auto:
                key = f"{ip}:{port}"
                if key in SecurityTools._block_schedule:
                    timer = SecurityTools._block_schedule[key].get('timer')
                    if timer:
                        timer.cancel()
                    del SecurityTools._block_schedule[key]
                    # 保存更新后的计划
                    SecurityTools._save_schedule()

            logger.info(f"已解除IP阻断: {ip}:{port}")

            return {
                "status": "success",
                "ip": ip,
                "port": port,
                "command": f"sed -i '/^{ip} 1;$/d' {blocked_ips_file} && nginx -s reload",
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"解除IP阻断失败: {e}")
            return {
                "status": "error",
                "ip": ip,
                "error": str(e)
            }
    
    
    @staticmethod
    def list_blocked_ips() -> Dict[str, Any]:
        """列出nginx配置文件中已阻断的IP地址"""
        try:
            blocked_ips_file = SecurityTools.BLOCKED_IPS_FILE

            # 检查blocked_ips.conf文件是否存在
            if not os.path.exists(blocked_ips_file):
                return {
                    "status": "success",
                    "blocked_ips": [],
                    "count": 0,
                    "message": "blocked_ips.conf文件不存在",
                    "timestamp": datetime.now().isoformat()
                }
            
            blocked_ips = []
            
            try:
                with open(blocked_ips_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            parts = line.split()
                            if len(parts) >= 2 and parts[1] == '1;':
                                ip = parts[0]
                                blocked_ips.append(ip)
            except Exception as e:
                logger.error(f"读取blocked_ips.conf失败: {e}")
                return {
                    "status": "error",
                    "error": f"读取配置文件失败: {str(e)}"
                }
            
            return {
                "status": "success",
                "blocked_ips": blocked_ips,
                "count": len(blocked_ips),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"获取阻断列表失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    @staticmethod
    def list_scheduled_blocks() -> Dict[str, Any]:
        """列出计划中的临时阻断"""
        scheduled = []
        for _, info in SecurityTools._block_schedule.items():
            remaining = "expired"
            if datetime.fromisoformat(info['expiry']) > datetime.now():
                remaining_seconds = (datetime.fromisoformat(info['expiry']) - datetime.now()).total_seconds()
                remaining = f"{int(remaining_seconds)}s"
            
            scheduled.append({
                "ip": info['ip'],
                "port": info['port'],
                "reason": info['reason'],
                "expiry": info['expiry'],
                "remaining": remaining
            })
        
        return {
            "status": "success",
            "scheduled_blocks": scheduled,
            "count": len(scheduled),
            "timestamp": datetime.now().isoformat()
        }
    
# 工具注册表：集中定义所有可用工具，避免在 do_GET/_execute_tool/_get_tool_schema 中重复硬编码
_TOOLS_REGISTRY: Dict[str, Dict[str, Any]] = {
    "security.block_ip_port": {
        "handler": SecurityTools.block_ip_port,
        "description": "阻止指定IP地址+端口的访问",
        "schema": {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "要阻止的IP地址"},
                "port": {"type": "string", "description": "要阻止的端口，填写'all'表示阻止所有端口"},
                "reason": {"type": "string", "description": "阻止原因"},
                "duration": {"type": "string", "description": "阻断期限，格式：30m, 2h, 1d, 7d 或 permanent", "default": "permanent"}
            },
            "required": ["ip"]
        }
    },
    "security.unblock_ip_port": {
        "handler": SecurityTools.unblock_ip_port,
        "description": "解除IP地址+端口的阻止",
        "schema": {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "要解除阻止的IP地址"},
                "port": {"type": "string", "description": "要解除阻止的端口，填写'all'表示阻止所有端口"}
            },
            "required": ["ip"]
        }
    },
    "security.list_blocked_ips": {
        "handler": SecurityTools.list_blocked_ips,
        "description": "列出已阻断的IP地址",
        "schema": {"type": "object", "properties": {}, "required": []}
    },
    "security.list_scheduled_blocks": {
        "handler": SecurityTools.list_scheduled_blocks,
        "description": "列出计划中的临时阻断",
        "schema": {"type": "object", "properties": {}, "required": []}
    },
}


class MCPRequestHandler(BaseHTTPRequestHandler):
    """MCP请求处理器"""
    
    def _build_tools_list(self) -> list:
        """构建工具列表"""
        tools = []
        for name, info in _TOOLS_REGISTRY.items():
            schema = info["schema"]
            parameters = {}
            for prop_name, prop in schema.get("properties", {}).items():
                parameters[prop_name] = {
                    "type": prop.get("type"),
                    "required": prop_name in schema.get("required", []),
                }
                if "default" in prop:
                    parameters[prop_name]["default"] = prop["default"]
            tools.append({
                "name": name,
                "description": info["description"],
                "parameters": parameters
            })
        return tools

    def do_GET(self):
        """处理GET请求"""
        parsed_path = urlparse(self.path)

        if parsed_path.path == "/health":
            self._send_json_response({
                "status": "healthy",
                "server": "MCP Security Server",
                "timestamp": datetime.now().isoformat()
            })

        elif parsed_path.path == "/tools":
            self._send_json_response({"tools": self._build_tools_list()})

        elif parsed_path.path.startswith("/tools/schema/"):
            tool_name = parsed_path.path.split("/")[-1]
            schema = self._get_tool_schema(tool_name)
            if schema:
                self._send_json_response(schema)
            else:
                self._send_json_response({"error": "Tool not found"}, 404)

        else:
            self._send_json_response({"error": "Not found"}, 404)
    
    def do_POST(self):
        """处理POST请求"""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == "/tools/execute":
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                try:
                    post_data = self.rfile.read(content_length)
                    request_data = json.loads(post_data.decode('utf-8'))
                    
                    result = self._execute_tool(request_data)
                    self._send_json_response(result)
                    
                except json.JSONDecodeError as e:
                    self._send_json_response({"error": f"Invalid JSON: {e}"}, 400)
                except Exception as e:
                    self._send_json_response({"error": str(e)}, 500)
            else:
                self._send_json_response({"error": "No data provided"}, 400)
                
        else:
            self._send_json_response({"error": "Not found"}, 404)
    
    def _execute_tool(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具"""
        tool_name = request_data.get("tool")
        arguments = request_data.get("arguments", {})

        if not tool_name:
            return {"error": "Tool name is required"}

        tool_info = _TOOLS_REGISTRY.get(tool_name)
        if tool_info:
            return tool_info["handler"](**arguments)

        return {"error": f"Unknown tool: {tool_name}"}
    
    def _get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取工具模式"""
        tool_info = _TOOLS_REGISTRY.get(tool_name)
        if not tool_info:
            return None
        return {
            "name": tool_name,
            "description": tool_info["description"],
            "inputSchema": tool_info["schema"]
        }
    
    def _send_json_response(self, data: Dict[str, Any], status_code: int = 200):
        """发送JSON响应"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        
        response = json.dumps(data, ensure_ascii=False, indent=2)
        self.wfile.write(response.encode('utf-8'))
    
    def do_OPTIONS(self):
        """处理OPTIONS请求（CORS预检）"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def log_message(self, format, *args):
        """自定义日志格式"""
        logger.info(f"{self.client_address[0]} - {format % args}")

class MCPServer:
    """MCP服务器"""
    
    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self.server = None
    
    def start(self):
        """启动服务器"""
        try:
            # 加载持久化的阻断计划
            SecurityTools._load_schedule()
            
            self.server = HTTPServer((self.host, self.port), MCPRequestHandler)
            logger.info(f"🚀 MCP服务器启动成功 - http://{self.host}:{self.port}")
            logger.info("📋 可用工具:")
            logger.info("   - security.block_ip_port: 阻断IP地址port端口")
            logger.info("   - security.unblock_ip_port: 解除IP地址port端口的阻断")
            logger.info("   - security.list_blocked_ips: 查看阻断列表")
            logger.info("   - security.list_scheduled_blocks: 查看计划中的临时阻断")
            logger.info("📝 访问 /health 检查服务器状态")
            logger.info("📝 访问 /tools 查看工具列表")
            
            self.server.serve_forever()
            
        except KeyboardInterrupt:
            logger.info("🛑 服务器停止中...")
        except Exception as e:
            logger.error(f"❌ 服务器启动失败: {e}")
        finally:
            if self.server:
                self.server.shutdown()
    
    def stop(self):
        """停止服务器"""
        if self.server:
            self.server.shutdown()
            logger.info("✅ MCP服务器已停止")

def get_free_port(start_port: int = 8080) -> int:
    """获取可用端口"""
    port = start_port
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            port += 1
            if port > 9000:
                raise RuntimeError("无法找到可用端口")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='MCP Security Server')
    parser.add_argument('--host', default='localhost', help='监听主机 (默认: localhost)')
    parser.add_argument('--port', type=int, default=8090, help='监听端口 (默认: 8090)')
    parser.add_argument('--auto-port', action='store_true', help='自动选择可用端口')
    
    args = parser.parse_args()
    
    if args.auto_port:
        port = get_free_port(args.port)
    else:
        port = args.port
    
    # 检查nginx配置文件访问权限
    blocked_ips_file = SecurityTools.BLOCKED_IPS_FILE
    if not os.path.exists(blocked_ips_file):
        logger.warning(f"⚠️  nginx阻断配置文件不存在: {blocked_ips_file}")
        logger.warning(f"   创建文件命令: sudo touch {blocked_ips_file} && sudo chown $USER:$USER {blocked_ips_file}")
    elif not os.access(blocked_ips_file, os.W_OK):
        logger.warning(f"⚠️  没有写入nginx阻断配置文件的权限: {blocked_ips_file}")
        logger.warning(f"   修改权限命令: sudo chown $USER:$USER {blocked_ips_file}")
    else:
        logger.info("✅ nginx阻断配置文件权限正常")
    
    server = MCPServer(args.host, port)
    
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()

if __name__ == "__main__":
    main()