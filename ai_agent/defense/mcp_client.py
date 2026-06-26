import logging
import os
import requests
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger('pml_security')

class MCPClient:
    """MCP (Model Communication Protocol) 客户端
    
    用于与MCP服务器通信，执行安全干预操作
    """
    
    def __init__(self, server_url: str = None):
        """初始化MCP客户端
        
        Args:
            server_url: MCP服务器URL，如果为None则使用settings中的配置
        """
        self.server_url = server_url or os.getenv("MCP_SERVER_URL", "http://localhost:5000")
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'PML-Security-Client/1.0'
        })
        
        # 请求超时时间（秒）
        self.timeout = 30
        
        logger.info(f"🔌 MCP客户端已初始化，服务器: {self.server_url}")
    
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行MCP工具
        
        Args:
            tool_name: 工具名称，如 'security.block_ip'
            parameters: 工具参数
            
        Returns:
            工具执行结果
        """
        try:
            url = f"{self.server_url}/tools/execute"
            
            payload = {
                "tool": tool_name,
                "arguments": parameters,
                "id": f"mcp_{int(datetime.now().timestamp())}"
            }
            
            logger.debug(f"执行MCP工具: {tool_name} 参数: {parameters}")
            
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"✅ MCP工具执行成功: {tool_name}")
            return {
                "status": "success",
                "tool": tool_name,
                "result": result,
                "timestamp": datetime.now().isoformat()
            }
            
        except requests.exceptions.Timeout:
            logger.error(f"⏱️ MCP工具执行超时: {tool_name}")
            return {
                "status": "error",
                "tool": tool_name,
                "error": "request_timeout",
                "message": "MCP服务器响应超时"
            }
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"🔗 MCP连接失败: {e}")
            return {
                "status": "error",
                "tool": tool_name,
                "error": "connection_failed",
                "message": f"无法连接到MCP服务器: {e}"
            }
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ MCP HTTP错误: {e}")
            return {
                "status": "error",
                "tool": tool_name,
                "error": "http_error",
                "message": f"HTTP错误: {e}"
            }
            
        except Exception as e:
            logger.error(f"❌ MCP工具执行异常: {e}")
            return {
                "status": "error",
                "tool": tool_name,
                "error": "exception",
                "message": str(e)
            }
    
    def list_tools(self) -> Dict[str, Any]:
        """
        获取可用工具列表
        
        Returns:
            可用工具列表
        """
        try:
            url = f"{self.server_url}/tools"
            
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            tools = response.json()
            logger.info(f"📋 获取到 {len(tools.get('tools', []))} 个可用工具")
            return {
                "status": "success",
                "tools": tools
            }
            
        except Exception as e:
            logger.error(f"❌ 获取工具列表失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def get_tool_schema(self, tool_name: str) -> Dict[str, Any]:
        """
        获取工具参数模式
        
        Args:
            tool_name: 工具名称
            
        Returns:
            工具参数模式
        """
        try:
            url = f"{self.server_url}/tools/schema/{tool_name}"
            
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            schema = response.json()
            return {
                "status": "success",
                "schema": schema
            }
            
        except Exception as e:
            logger.error(f"❌ 获取工具模式失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def health_check(self) -> Dict[str, Any]:
        """
        检查MCP服务器健康状态
        
        Returns:
            健康检查结果
        """
        try:
            url = f"{self.server_url}/health"
            
            response = self.session.get(url, timeout=5)
            response.raise_for_status()
            
            health = response.json()
            return {
                "status": "healthy",
                "server_status": health
            }
            
        except Exception as e:
            logger.error(f"❌ MCP服务器健康检查失败: {e}")
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    def test_connection(self) -> bool:
        """
        测试MCP服务器连接
        
        Returns:
            连接是否成功
        """
        try:
            result = self.health_check()
            return result.get("status") == "healthy"
        except Exception:
            return False
    
    def get_security_tools(self) -> Dict[str, Any]:
        """
        获取安全相关的工具列表
        
        Returns:
            安全工具列表
        """
        all_tools = self.list_tools()
        if all_tools.get("status") != "success":
            return all_tools
        
        # 过滤安全相关的工具
        security_tools = []
        for tool in all_tools.get("tools", {}).get("tools", []):
            if tool.get("name", "").startswith("security."):
                security_tools.append(tool)
        
        return {
            "status": "success",
            "security_tools": security_tools,
            "count": len(security_tools)
        }

# 预定义的安全工具
SECURITY_TOOLS = {
    "security.block_ip_port": {
        "description": "阻止指定IP地址+端口的访问",
        "parameters": {
            "ip": {
                "type": "string",
                "description": "要阻止的IP地址",
                "required": True
            },
            "port": {
                "type": "string",
                "description": "要阻止的访问端口",
                "required": False
            },
            "duration": {
                "type": "string",
                "description": "阻止持续时间（如 '1h', '30m'）",
                "required": False,
                "default": "2h"
            }, 
            "reason": {
                "type": "string",
                "description": "阻止原因",
                "required": False
            }
        }
    },
    "security.increase_monitoring": {
        "description": "增加对指定目标的监控频率",
        "parameters": {
            "target": {
                "type": "string",
                "description": "监控目标（IP、域名、资源等）",
                "required": True
            },
            "frequency": {
                "type": "string",
                "description": "监控频率级别（low, medium, high）",
                "required": False,
                "default": "high"
            },
            "duration": {
                "type": "string",
                "description": "增强监控持续时间",
                "required": False,
                "default": "30m"
            }
        }
    },
    "security.isolate_resource": {
        "description": "隔离可疑资源",
        "parameters": {
            "resource": {
                "type": "string",
                "description": "要隔离的资源标识符",
                "required": True
            },
            "reason": {
                "type": "string",
                "description": "隔离原因",
                "required": False
            }
        }
    },
    "security.unblock_ip_port": {
        "description": "解除IP地址+端口阻止",
        "parameters": {
            "ip": {
                "type": "string",
                "description": "要解除阻止的IP地址",
                "required": True
            },
             "port": {
                "type": "string",
                "description": "要解除阻止访问的端口",
                "required": False
            }
        }
    }
}
