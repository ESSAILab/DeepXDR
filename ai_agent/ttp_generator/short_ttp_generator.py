import asyncio
import ipaddress
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from shared.models.ttp import ShortTTP
from shared.database.elastic_repositories import get_mixed_repository
from .window_manager import DynamicEventWindowManager, EventWindow
from shared.models.events import SecurityEvent, EventType, OpenRASPAlertEvent, OpenRASPRawEvent, OpenRASPRawSQLEvent, SuricataAlertEvent
from defense.defense_manager import DefenseManager
from .dx_analyzer_api import trigger_long_ttp_generation

logger = logging.getLogger(__name__)

UNKNOWN_ATTACKER_IP_GROUP = "unknown"
DEFAULT_MAX_ATTACKER_IP_GROUPS = 10
DEFAULT_MAX_CONCURRENT_ANALYSES = 3
MAX_CONCURRENT_ANALYSES_CAP = 16
DEFAULT_PROCESSING_QUEUE_SIZE = 128
MAX_PROCESSING_QUEUE_SIZE_CAP = 1000


def _read_positive_int_env(name: str, default: int, maximum: int) -> int:
    """Read a positive integer environment variable with a hard upper bound."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("%s=%r 不是有效整数，使用默认值 %s", name, raw_value, default)
        return default

    if value < 1:
        logger.warning("%s=%s 必须为正整数，使用默认值 %s", name, value, default)
        return default

    if value > maximum:
        logger.warning("%s=%s 超过最大值 %s，已限制为最大值", name, value, maximum)
        return maximum

    return value

# ========== 攻击IP提取函数 ==========

def _normalize_ip(value: Optional[str]) -> Optional[str]:
    """验证并规范化IP地址字符串，拒绝无效或复合输入。"""
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        logger.debug(f"[IP分组] 忽略无效攻击者IP: {value}")
        return None


def extract_attacker_ip(event: SecurityEvent) -> Optional[str]:
    """
    从事件中提取攻击者IP

    优先级规则：
    1. OpenRASP: 优先使用 header.x_real_ip（经过代理的真实IP），
       其次是 attack_source（攻击源IP），最后是 client_ip

    2. Suricata: 使用 src_ip 作为攻击者IP（默认假设）

    Args:
        event: 安全事件

    Returns:
        攻击者IP，如果无法提取则返回None
    """
    raw = event.raw_event

    if isinstance(raw, (OpenRASPAlertEvent, OpenRASPRawEvent, OpenRASPRawSQLEvent)):
        # OpenRASP: 优先使用 x_real_ip，其次是 attack_source，最后是 client_ip。
        # 所有候选值均来自遥测数据，必须先校验并规范化，避免攻击者用任意字符串制造分组。
        candidates = [
            raw.header.x_real_ip if raw.header else None,
            raw.attack_source,
            raw.client_ip,
        ]
        for candidate in candidates:
            normalized_ip = _normalize_ip(candidate)
            if normalized_ip:
                return normalized_ip
        return None

    elif isinstance(raw, SuricataAlertEvent):
        # Suricata: src_ip 是源IP，默认认为是攻击者；先校验，避免异常字符串成为分组键。
        return _normalize_ip(raw.src_ip)

    return None


def split_events_by_attacker_ip(
    events: List[SecurityEvent],
    max_groups: int = DEFAULT_MAX_ATTACKER_IP_GROUPS,
) -> Dict[str, List[SecurityEvent]]:
    """
    将事件按攻击者IP分组。

    分组键来自外部遥测数据，必须限制分组数量。若一个窗口内出现过多不同
    攻击IP，则回退为单个聚合分析，避免攻击者伪造大量IP造成LLM/MCP分析扇出。

    Args:
        events: 事件列表（已过滤后的）
        max_groups: 单个窗口允许的最大IP分组数

    Returns:
        Dict[ip, events]: 按攻击IP分组的事件字典
                         key为"unknown"表示无法提取IP或回退聚合分析
    """
    if max_groups < 1:
        logger.warning(f"[IP分组] max_groups={max_groups} 无效，回退为单组聚合分析")
        return {UNKNOWN_ATTACKER_IP_GROUP: list(events)}

    ip_groups: Dict[str, List[SecurityEvent]] = {}

    for event in events:
        attacker_ip = extract_attacker_ip(event) or UNKNOWN_ATTACKER_IP_GROUP

        if attacker_ip not in ip_groups and len(ip_groups) >= max_groups:
            logger.warning(
                f"[IP分组] 攻击者IP分组数超过上限 {max_groups}，"
                f"窗口将回退为单组聚合分析，避免分析扇出"
            )
            return {UNKNOWN_ATTACKER_IP_GROUP: list(events)}

        ip_groups.setdefault(attacker_ip, []).append(event)

    return ip_groups


class ShortTTPGenerator:
    """短期TTP生成器"""
    
    def __init__(
        self,
        window_manager: DynamicEventWindowManager,
        min_events_per_window: int = 1,  # 降低要求，允许单个事件生成TTP
        max_analysis_interval: float = 5.0,
        confidence_threshold: float = 0.5  # 降低置信度阈值
    ):
        self.window_manager = window_manager
        self.min_events_per_window = min_events_per_window
        self.max_analysis_interval = max_analysis_interval
        self.confidence_threshold = confidence_threshold
        
        # 从环境变量获取并发限制，默认值为3，并限制到安全范围
        self.max_concurrent_analyses = _read_positive_int_env(
            'SHORT_TTP_MAX_CONCURRENT',
            DEFAULT_MAX_CONCURRENT_ANALYSES,
            MAX_CONCURRENT_ANALYSES_CAP,
        )
        default_queue_size = max(DEFAULT_PROCESSING_QUEUE_SIZE, self.max_concurrent_analyses * 10)
        self.max_processing_queue_size = _read_positive_int_env(
            'SHORT_TTP_QUEUE_MAX_SIZE',
            default_queue_size,
            MAX_PROCESSING_QUEUE_SIZE_CAP,
        )
        
        self.running = False
        self._analysis_task: Optional[asyncio.Task] = None
        
        # 初始化防御管理器实例（单例模式）        
        self.defense_manager = DefenseManager()
        
        # 新增：动态处理队列
        self._processing_queue: Optional[asyncio.Queue] = None
        self._window_processor_tasks: List[asyncio.Task] = []
        
        # 新增：跟踪正在处理和已排队的窗口，避免重复处理
        self._processing_windows: set = set()  # 正在处理的窗口ID
        self._queued_windows: set = set()      # 已排队等待处理的窗口ID
    
    async def start(self):
        """启动短期TTP生成器 - 使用动态队列处理"""
        self.running = True
        
        # 初始化有界处理队列，避免事件洪泛时无限保留待处理窗口
        self._processing_queue = asyncio.Queue(maxsize=self.max_processing_queue_size)
        
        # 启动窗口处理器协程
        for i in range(self.max_concurrent_analyses):
            processor_task = asyncio.create_task(self._window_processor(f"处理器-{i+1}"))
            self._window_processor_tasks.append(processor_task)
        
        # 启动主循环任务
        self._analysis_task = asyncio.create_task(self._analysis_loop())
        logger.info(f"短期TTP生成器已启动 - 动态并发处理，最大并发数: {self.max_concurrent_analyses}")
    
    async def stop(self):
        """停止短期TTP生成器 - 清理动态处理器"""
        self.running = False
        
        # 1. 取消主循环任务
        if self._analysis_task:
            self._analysis_task.cancel()
            try:
                await self._analysis_task
            except asyncio.CancelledError:
                pass
        
        # 2. 取消所有窗口处理器协程
        for processor_task in self._window_processor_tasks:
            processor_task.cancel()
        
        # 3. 等待处理器协程完成
        if self._window_processor_tasks:
            await asyncio.gather(*self._window_processor_tasks, return_exceptions=True)
        
        # 4. 清空处理器任务列表
        self._window_processor_tasks.clear()
        
        logger.info("短期TTP生成器已停止 - 动态处理器已清理")
    
    async def _window_processor(self, processor_name: str):
        """窗口处理器协程 - 持续运行"""
        logger.info(f"窗口处理器 {processor_name} 已启动")
        
        while self.running:
            try:
                # 从队列获取窗口（带超时，允许定期检查running状态）
                window = await asyncio.wait_for(
                    self._processing_queue.get(), 
                    timeout=1.0
                )
                
                if window:  # 安全检查
                    logger.debug(f"{processor_name} 开始处理窗口: {window.window_id}")
                    
                    # 标记窗口为正在处理
                    self._processing_windows.add(window.window_id)
                    
                    try:
                        # 处理窗口
                        await self._analyze_window(window)
                        await self.window_manager.mark_window_processed(window.window_id)
                        
                        logger.debug(f"{processor_name} 完成窗口处理: {window.window_id}")
                        
                    except Exception as e:
                        logger.error(f"{processor_name} 处理窗口 {window.window_id} 失败: {e}")
                        # 即使失败也标记为已处理，避免无限重试
                        await self.window_manager.mark_window_processed(window.window_id)
                        
                    finally:
                        # 清理窗口状态（无论成功还是失败）
                        self._processing_windows.discard(window.window_id)
                        self._queued_windows.discard(window.window_id)
                
            except asyncio.TimeoutError:
                # 队列空，继续循环检查running状态
                continue
            except Exception as e:
                logger.error(f"{processor_name} 处理器异常: {e}")
                await asyncio.sleep(1)
        
        logger.info(f"窗口处理器 {processor_name} 已停止")
    
    def _is_window_valid(self, window: EventWindow) -> bool:
        """判断窗口是否满足分析条件且未在处理或排队中"""
        return (
            window.get_event_count() >= self.min_events_per_window
            and window.window_id not in self._processing_windows
            and window.window_id not in self._queued_windows
        )

    def _try_enqueue_window(self, window: EventWindow) -> bool:
        """尝试将单个窗口加入处理队列，成功返回 True"""
        try:
            self._processing_queue.put_nowait(window)
            self._queued_windows.add(window.window_id)
            return True
        except asyncio.QueueFull:
            return False

    async def _analysis_loop(self):
        """新的动态并发处理循环"""
        logger.info("启动动态并发处理循环")
        processed_count = 0

        while self.running:
            try:
                # 只扫描并入队有界数量的窗口，避免一次性保留所有已关闭窗口对象
                current_queue_size = self._processing_queue.qsize()
                available_capacity = self.max_processing_queue_size - current_queue_size
                if available_capacity <= 0:
                    logger.debug("处理队列已满，等待下一轮")
                    await asyncio.sleep(0.5)
                    continue

                ready_windows = await self.window_manager.get_ready_windows(limit=available_capacity)
                windows_added = 0
                for window in ready_windows:
                    if (window.get_event_count() < self.min_events_per_window or
                        window.window_id in self._processing_windows or
                        window.window_id in self._queued_windows):
                        continue

                    try:
                        self._processing_queue.put_nowait(window)
                    except asyncio.QueueFull:
                        logger.debug("处理队列已满，等待下一轮")
                        break

                    self._queued_windows.add(window.window_id)
                    windows_added += 1
                    processed_count += 1

                    if processed_count % 10 == 0:  # 每10个窗口记录一次
                        logger.info(f"已添加 {processed_count} 个窗口到处理队列")

                if not windows_added:
                    # 没有新窗口时短暂休眠
                    await asyncio.sleep(0.5)  # 比原来的5秒更频繁
                    continue

                logger.debug(
                    f"已添加 {windows_added} 个窗口到处理队列，当前队列大小: {self._processing_queue.qsize()}"
                )
                
                if windows_added > 0:
                    logger.debug(f"已添加 {windows_added} 个窗口到处理队列")

                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                logger.info("动态处理循环被取消")
                break
            except Exception as e:
                logger.error(f"动态处理循环异常: {e}")
                await asyncio.sleep(1)

        logger.info("动态并发处理循环已停止")
    
    def get_queue_stats(self) -> Dict:
        """获取处理队列统计"""
        if not self._processing_queue:
            return {"status": "not_initialized"}
        
        return {
            "queue_size": self._processing_queue.qsize(),
            "active_processors": len(self._window_processor_tasks),
            "max_concurrent": self.max_concurrent_analyses,
            "max_queue_size": self.max_processing_queue_size,
            "running": self.running,
            "processing_windows": len(self._processing_windows),  # 正在处理的窗口数
            "queued_windows": len(self._queued_windows),          # 已排队的窗口数
            "unique_processing_ids": list(self._processing_windows),  # 正在处理的窗口ID
            "unique_queued_ids": list(self._queued_windows)          # 已排队的窗口ID
        }
    
    def _filter_events_by_priority(self, events: List[SecurityEvent]) -> Tuple[List[SecurityEvent], str]:
        """
        根据优先级筛选事件

        优先级规则：
        - OpenRASP/Suricata 事件优先级高于 Falco
        - 如果窗口中存在 OpenRASP 或 Suricata 事件，则忽略 Falco 事件
        - 否则，保留 Falco 事件

        参数:
            events: 原始事件列表

        返回:
            Tuple[List[SecurityEvent], str]: (筛选后的事件列表, 日志消息)
        """
        # 定义事件类型
        openrasp_types = {EventType.OPENRASP_ALERT, EventType.OPENRASP_RAW, EventType.OPENRASP_RAW_SQL}
        suricata_types = {EventType.SURICATA_ALERT}
        falco_types = {EventType.FALCO_ALERT, EventType.FALCO_RAW}

        # 统计各类型事件
        openrasp_events = [e for e in events if e.event_type in openrasp_types]
        suricata_events = [e for e in events if e.event_type in suricata_types]
        falco_events = [e for e in events if e.event_type in falco_types]

        # 判断是否有高优先级事件
        has_high_priority = len(openrasp_events) > 0 or len(suricata_events) > 0

        if has_high_priority:
            # 存在 OpenRASP/Suricata 事件，过滤掉 Falco
            high_priority_events = openrasp_events + suricata_events
            actual_types = []
            if openrasp_events:
                actual_types.append("openrasp")
            if suricata_events:
                actual_types.append("suricata")
            type_str = "/".join(actual_types)
            log_msg = f"当前窗口中有 {type_str} 事件类型，忽略 falco 事件输入"
            return high_priority_events, log_msg
        else:
            # 只有 Falco 事件
            log_msg = "当前窗口中仅有 falco 事件类型，接受 falco 事件输入"
            return falco_events, log_msg

    async def _analyze_window(self, window: EventWindow):
        """分析单个窗口（支持按攻击IP分组分析）"""
        try:
            logger.info(f"开始分析窗口: {window.window_id}, 事件数: {window.get_event_count()}")

            # === 根据优先级筛选事件 ===
            filtered_events, filter_log_msg = self._filter_events_by_priority(window.events)

            # 打印筛选结果日志
            logger.info(f"[事件筛选] 窗口 {window.window_id}: {filter_log_msg}")
            logger.info(f"[事件筛选] 原始事件数: {len(window.events)}, 筛选后事件数: {len(filtered_events)}")

            # 如果筛选后没有事件，跳过分析
            if not filtered_events:
                logger.info(f"[事件筛选] 窗口 {window.window_id} 筛选后无可用事件，跳过分析")
                return

            # 使用筛选后的事件列表
            events_to_analyze = filtered_events
            # ===============================

            # === 按攻击IP分组 ===
            ip_groups = split_events_by_attacker_ip(events_to_analyze)
            logger.info(f"[IP分组] 窗口 {window.window_id} 按攻击IP分为 {len(ip_groups)} 组: {list(ip_groups.keys())}")

            # 对每个攻击IP分组分别分析
            for attacker_ip, ip_events in ip_groups.items():
                await self._analyze_ip_group(window, attacker_ip, ip_events)

        except Exception as e:
            logger.error(f"分析窗口失败: {e}")

    async def _analyze_ip_group(self, window: EventWindow, attacker_ip: str, events: List[SecurityEvent]):
        """
        分析单个攻击IP的事件组

        Args:
            window: 原始窗口
            attacker_ip: 攻击者IP（或"unknown"）
            events: 该攻击者的事件列表
        """
        try:
            if not events:
                logger.debug(f"[IP分析] 攻击者 {attacker_ip} 无事件，跳过")
                return

            logger.info(f"[IP分析] 开始分析攻击者: {attacker_ip}, 事件数: {len(events)}")

            logger.debug("[DEBUG] IP组详细分析开始:")
            logger.debug(f"[DEBUG]   原始窗口ID: {window.window_id}")
            logger.debug(f"[DEBUG]   攻击者IP: {attacker_ip}")
            logger.debug(f"[DEBUG]   事件数量: {len(events)}")

            for i, event in enumerate(events):
                logger.debug(f"[DEBUG]   事件 {i+1}: {event.event_type} - {event.get_unique_id()} - {event.get_event_time()}")

            # 调用AI分析器（传入attacker_ip）
            analysis_start = datetime.now()
            from .short_ttp_workflow import ShortTTPWorkflowFinal
            workflow = ShortTTPWorkflowFinal()
            # 将"unknown"转换为None
            attacker_ip_value = attacker_ip if attacker_ip != "unknown" else None
            short_ttp = await workflow.analyze_events(events, attacker_ip=attacker_ip_value)
            analysis_end = datetime.now()
            analysis_duration = (analysis_end - analysis_start).total_seconds()

            logger.info(f"[IP分析] AI分析完成，攻击者IP:{attacker_ip}, 事件数:{len(events)}, 耗时:{analysis_duration:.2f}秒")

            import json
            logger.debug("[DEBUG] 生成的短期TTP完整结构:")
            logger.debug(json.dumps(short_ttp.model_dump(), indent=2, default=str, ensure_ascii=False))

            # 验证置信度
            if short_ttp.confidence >= self.confidence_threshold:
                # 存储短期TTP
                await self._store_short_ttp(short_ttp)

                # 执行自动防御措施
                try:
                    defense_result = await self.defense_manager.process_short_ttp(short_ttp)

                    if defense_result.get('status') == 'success':
                        actions = len(defense_result.get('actions_taken', []))
                        logger.info(f"🛡️ 短期TTP防御措施已执行: {actions} 个操作")
                    else:
                        logger.warning(f"⚠️ 短期TTP防御措施执行失败: {defense_result.get('message')}")

                except Exception as e:
                    logger.error(f"❌ 执行短期TTP防御措施失败: {e}")

                logger.info(f"短期TTP生成成功，窗口ID:{window.window_id}, 攻击者IP:{attacker_ip}, short TTP ID: {short_ttp.id}")
            else:
                logger.debug(f"短期TTP置信度不足: {short_ttp.confidence} < {self.confidence_threshold}")

        except Exception as e:
            logger.error(f"[IP分析] 分析攻击者 {attacker_ip} 失败: {e}")
    
    async def _store_short_ttp(self, short_ttp: ShortTTP):
        """存储短期TTP到ElasticSearch"""
        try:
            # 使用新的ES仓库保存STTP
            mixed_repo = await get_mixed_repository()
            success = await mixed_repo.get_short_ttp_repository().save_short_ttp(
                short_ttp.model_dump()
            )

            if success:
                logger.info(f"短期TTP已保存到ES: {short_ttp.id}")
            else:
                logger.error(f"短期TTP保存到ES失败: {short_ttp.id}")

        except Exception as e:
            logger.error(f"存储短期TTP到ES异常: {e}")
    
    def _trigger_long_ttp_generation(self, short_ttp: ShortTTP):
        """触发Long TTP生成的接口调用，具体实现由独立模块处理"""
        try:
            logger.info(f"Short TTP {short_ttp.id} 触发Long TTP生成接口")             
            logger.info("basic_demo_streaming模块导入成功")             
            asyncio.create_task(trigger_long_ttp_generation(short_ttp))
            
        except Exception as e:
            logger.error(f"触发Long TTP生成接口失败: {e}")
    
    async def get_recent_short_ttps(
        self,
        hours: int = 24,
        min_confidence: float = 0.6,
        limit: int = 100,
        offset: int = 0
    ) -> List[ShortTTP]:
        """获取最近的短期TTP（使用ElasticSearch）"""
        try:
            # 使用ES仓库查询短期TTP
            from shared.database.elastic_repositories import get_mixed_repository

            mixed_repo = await get_mixed_repository()
            es_repo = mixed_repo.get_short_ttp_repository()

            # 计算时间范围
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours)

            # 从ES查询数据
            result = await es_repo.get_short_ttps(
                offset=offset,
                limit=limit,
                start_time=start_time,
                end_time=end_time,
                min_confidence=min_confidence
            )

            # 转换数据为ShortTTP对象
            sttps = []
            raw_items = result.get("items", [])

            for item_data in raw_items:
                try:
                    sttp = ShortTTP.model_validate(item_data)
                    sttps.append(sttp)
                except Exception as e:
                    logger.error(f"转换ShortTTP对象失败: {e}, 数据: {item_data}")

            return sttps

        except Exception as e:
            logger.error(f"获取最近短期TTP失败: {e}")
            return []
    
    async def get_short_ttp_by_id(self, ttp_id: str) -> Optional[ShortTTP]:
        """通过ID获取短期TTP（使用ElasticSearch）"""
        try:
            # 使用ES仓库查询单个短期TTP
            from shared.database.elastic_repositories import get_mixed_repository

            mixed_repo = await get_mixed_repository()
            es_repo = mixed_repo.get_short_ttp_repository()

            # 从ES查询数据
            result = await es_repo.get_short_ttp_by_id(ttp_id)
            if result:
                sttp = ShortTTP.model_validate(result)
                logger.debug(f"从ES获取短期TTP: {ttp_id}")
                return sttp

            return None

        except Exception as e:
            logger.error(f"获取短期TTP失败 - ID: {ttp_id}, 错误: {e}")
            return None
    
    async def get_generation_stats(self) -> Dict:
        """获取生成统计 - 包含动态队列状态"""
        try:
            recent_ttps = await self.get_recent_short_ttps(hours=1)
            
            return {
                "running": self.running,
                "recent_ttp_count": len(recent_ttps),
                "min_events_per_window": self.min_events_per_window,
                "max_analysis_interval": self.max_analysis_interval,
                "confidence_threshold": self.confidence_threshold,
                "max_concurrent_analyses": self.max_concurrent_analyses,
                "window_stats": await self.window_manager.get_window_stats(),
                "queue_stats": self.get_queue_stats(),  # 新增队列统计
                "processing_mode": "dynamic_queue"  # 标识处理模式
            }
            
        except Exception as e:
            logger.error(f"获取生成统计失败: {e}")
            return {"error": str(e)}
    


