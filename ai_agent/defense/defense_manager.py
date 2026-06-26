"""
防御管理器
集成MCP客户端，在检测到威胁时自动执行防御措施
"""
import asyncio
import logging
from typing import Dict, Any
import os

from shared.models.ttp import ShortTTP, LongTTP
from defense.mcp_client import MCPClient

logger = logging.getLogger(__name__)


class DefenseManager:
    """防御管理器 - 基于威胁分析结果执行自动防御"""
    
    def __init__(self, mcp_server_url: str = None):
        """
        初始化防御管理器
        
        Args:
            mcp_server_url: MCP服务器URL，如果为None则使用环境变量或默认值
        """
        self.mcp_server_url = mcp_server_url or os.getenv(
            'MCP_SERVER_URL', 
            'http://localhost:8080'
        )
        self.mcp_client = MCPClient(self.mcp_server_url)
        self.enabled = os.getenv('DEFENSE_ENABLED', 'true').lower() == 'true'
        self.auto_block_threshold = float(os.getenv('AUTO_BLOCK_THRESHOLD', '0.8'))
        self.auto_block_ips = os.getenv('AUTO_BLOCK_IPS', 'true').lower() == 'true'
        self.app_port = os.getenv('APP_PORT', '8080')
        self.defense_duration = os.getenv('DEFENSE_DURATION', '2h')
        
        logger.info("🛡️ 防御管理器已初始化")
        logger.info(f"   MCP服务器: {self.mcp_server_url}")
        logger.info(f"   自动阻断: {self.auto_block_ips}")
        logger.info(f"   阻断阈值: {self.auto_block_threshold}")
    
    async def check_mcp_health(self) -> bool:
        """检查MCP服务器健康状态"""
        try:
            result = self.mcp_client.health_check()
            healthy = result.get('status') == 'healthy'
            if healthy:
                logger.info("✅ MCP服务器健康检查通过")
            else:
                logger.warning("⚠️ MCP服务器健康检查失败")
            return healthy
        except Exception as e:
            logger.error(f"❌ MCP服务器连接失败: {e}")
            return False
    
    async def _execute_short_ttp_defense(self, short_ttp: ShortTTP, actions_taken: list) -> None:
        """执行短期TTP的防御措施（阻断IP和增强监控）"""
        if short_ttp.attacker_fingerprint and self.auto_block_ips:
            primary_ip = short_ttp.attacker_fingerprint.primary_ip
            if primary_ip and primary_ip != "unknown":
                result = await self._block_ip_async(
                    primary_ip,
                    self.app_port,
                    self.defense_duration,
                    f"短期TTP置信度{short_ttp.confidence}: {short_ttp.summary[:100]}"
                )
                actions_taken.append({
                    "action": "block_ip_port",
                    "ip": primary_ip,
                    "port": self.app_port,
                    "duration": self.defense_duration,
                    "result": result
                })

        if short_ttp.attacker_fingerprint:
            for ip in short_ttp.attacker_fingerprint.ip_list:
                if ip != "unknown":
                    result = await self._increase_monitoring_async(
                        ip,
                        "high",
                        self.defense_duration
                    )
                    actions_taken.append({
                        "action": "increase_monitoring",
                        "target": ip,
                        "duration": self.defense_duration,
                        "result": result
                    })

    async def process_short_ttp(self, short_ttp: ShortTTP) -> Dict[str, Any]:
        """处理短期TTP，执行相应防御措施"""
        if not self.enabled:
            return {"status": "disabled", "message": "防御功能已禁用"}
        
        if not await self.check_mcp_health():
            return {"status": "error", "message": "MCP服务器不可用"}
        
        actions_taken = []

        try:
            # 检查置信度是否达到自动阻断阈值
            if short_ttp.confidence >= self.auto_block_threshold:
                logger.info(f"🚨 短期TTP置信度{short_ttp.confidence} >= 阈值{self.auto_block_threshold}，执行自动防御")
                await self._execute_short_ttp_defense(short_ttp, actions_taken)
            else:
                logger.info(f"ℹ️ 短期TTP置信度{short_ttp.confidence} < 阈值{self.auto_block_threshold}，不执行自动防御")

            return {
                "status": "success",
                "ttp_id": short_ttp.id,
                "actions_taken": actions_taken,
                "confidence": short_ttp.confidence
            }

        except Exception as e:
            logger.error(f"处理短期TTP时出错: {e}")
            return {
                "status": "error",
                "error": str(e),
                "ttp_id": short_ttp.id
            }
    
    async def _process_high_risk_long_ttp(self, long_ttp: LongTTP, actions_taken: list) -> None:
        """处理高风险长期TTP"""
        logger.warning(f"🚨 高风险长期TTP检测: {long_ttp.id}")

        for apt in long_ttp.apts:
            primary_ip = apt.attacker_fingerprint.primary_ip
            if primary_ip != "unknown":
                result = await self._block_ip_async(
                    primary_ip,
                    self.app_port,
                    "24h",
                    f"高风险APT攻击: {apt.name}"
                )
                actions_taken.append({
                    "action": "block_ip_apt",
                    "ip": primary_ip,
                    "apt_name": apt.name,
                    "result": result
                })

            for ip in apt.attacker_fingerprint.ip_list:
                if ip != primary_ip and ip != "unknown":
                    result = await self._block_ip_async(
                        ip,
                        self.app_port,
                        "6h",
                        f"APT相关IP: {apt.name}"
                    )
                    actions_taken.append({
                        "action": "block_related_ip",
                        "ip": ip,
                        "apt_name": apt.name,
                        "result": result
                    })

            for system in apt.affected_systems:
                result = await self._increase_monitoring_async(
                    system,
                    "high",
                    "24h"
                )
                actions_taken.append({
                    "action": "increase_system_monitoring",
                    "system": system,
                    "result": result
                })

    async def _process_medium_risk_long_ttp(self, long_ttp: LongTTP, actions_taken: list) -> None:
        """处理中等风险长期TTP"""
        logger.info(f"⚠️ 中等风险长期TTP检测: {long_ttp.id}")

        for apt in long_ttp.apts:
            primary_ip = apt.attacker_fingerprint.primary_ip
            if primary_ip != "unknown":
                result = await self._increase_monitoring_async(
                    primary_ip,
                    "medium",
                    "12h"
                )
                actions_taken.append({
                    "action": "monitor_suspicious_ip",
                    "ip": primary_ip,
                    "result": result
                })

    async def process_long_ttp(self, long_ttp: LongTTP) -> Dict[str, Any]:
        """处理长期TTP，执行高级防御措施"""
        if not self.enabled:
            return {"status": "disabled", "message": "防御功能已禁用"}
        
        if not await self.check_mcp_health():
            return {"status": "error", "message": "MCP服务器不可用"}
        
        actions_taken = []

        try:
            logger.info(f"🔥 处理长期TTP: {long_ttp.id} (风险评分: {long_ttp.risk_score})")

            # 高风险自动执行更强防御措施
            if long_ttp.risk_score >= 8.0:
                await self._process_high_risk_long_ttp(long_ttp, actions_taken)
            # 中等风险增加监控
            elif long_ttp.risk_score >= 5.0:
                await self._process_medium_risk_long_ttp(long_ttp, actions_taken)

            return {
                "status": "success",
                "ttp_id": long_ttp.id,
                "risk_score": long_ttp.risk_score,
                "actions_taken": actions_taken
            }

        except Exception as e:
            logger.error(f"处理长期TTP时出错: {e}")
            return {
                "status": "error",
                "error": str(e),
                "ttp_id": long_ttp.id
            }
    
    async def _block_ip_async(self, ip: str, port: str, duration: str, reason: str) -> Dict[str, Any]:
        """异步阻断IP"""
        try:
            # 在事件循环中执行阻塞操作
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                self.mcp_client.execute_tool,
                "security.block_ip_port",
                {"ip": ip, "port": port, "duration": duration, "reason": reason}
            )
            return result
        except Exception as e:
            logger.error(f"阻断IP {ip} 失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _increase_monitoring_async(self, target: str, frequency: str, duration: str) -> Dict[str, Any]:
        """异步增加监控"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.mcp_client.execute_tool,
                "security.increase_monitoring",
                {"target": target, "frequency": frequency, "duration": duration}
            )
            return result
        except Exception as e:
            logger.error(f"增加监控 {target} 失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def get_blocked_ips(self) -> Dict[str, Any]:
        """获取当前被阻断的IP列表"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.mcp_client.execute_tool,
                "security.list_blocked_ips",
                {}
            )
            return result
        except Exception as e:
            logger.error(f"获取阻断IP列表失败: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_config(self) -> Dict[str, Any]:
        """获取当前防御配置"""
        return {
            "enabled": self.enabled,
            "mcp_server_url": self.mcp_server_url,
            "auto_block_threshold": self.auto_block_threshold,
            "auto_block_ips": self.auto_block_ips,
            "app_port": self.app_port
        }