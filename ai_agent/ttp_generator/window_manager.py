"""
动态事件窗口管理器
实现动态事件窗口算法，将连续间隔不超过1秒的事件分组
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
import uuid
import heapq
from shared.utils.timezone import ChinaTime, to_china_time, to_naive

from shared.models.events import SecurityEvent

logger = logging.getLogger(__name__)

DEFAULT_MAX_ACTIVE_WINDOWS = 1000
MAX_ACTIVE_WINDOWS_CAP = 10000
DEFAULT_MAX_CLOSED_WINDOWS = 1000
MAX_CLOSED_WINDOWS_CAP = 10000
DEFAULT_MAX_PENDING_EVENTS = 5000
MAX_PENDING_EVENTS_CAP = 50000


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


class EventWindow:
    """事件窗口"""
    
    def __init__(self, window_id: str, start_time: datetime):
        self.window_id = window_id
        # 确保开始时间是东八区时间
        from shared.utils.timezone import to_china_time
        self.start_time = to_china_time(start_time)
        self.end_time = self.start_time
        self.events: List[SecurityEvent] = []
        self.last_event_time = self.start_time
        self.closed = False
        # 从环境变量获取窗口间隔时间，默认为1秒
        self.window_interval = float(os.getenv('SHORT_TTP_WINDOW_INTERVAL', 1.0))
    
    def add_event(self, event: SecurityEvent) -> bool:
        """添加事件到窗口"""
        if self.closed:
            return False
        
        # 使用标准化的事件时间（转换为东八区时间）
        event_time = event.get_event_time()
        # 确保事件时间也是东八区时间
        event_time = to_china_time(event_time)
        
        # 检查事件是否可以加入当前窗口
        if self.events and (event_time - self.last_event_time).total_seconds() > self.window_interval:
            return False
        
        self.events.append(event)
        self.last_event_time = event_time
        self.end_time = max(self.end_time, event_time)
        return True
    
    def close_window(self):
        """关闭窗口"""
        self.closed = True
    
    def get_event_count(self) -> int:
        """获取事件数量"""
        return len(self.events)
    
    def get_duration(self) -> float:
        """获取窗口持续时间（秒）"""
        if not self.events:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()
    
    def get_event_ids(self) -> List[str]:
        """获取事件ID列表"""
        return [event.get_unique_id() for event in self.events]


class DynamicEventWindowManager:
    """动态事件窗口管理器"""
    
    def __init__(
        self,
        max_window_size: int = 1000,
        window_timeout: float = 2.0,
        cleanup_interval: float = 60.0
    ):
        self.max_window_size = max_window_size
        self.window_timeout = window_timeout
        self.cleanup_interval = cleanup_interval
        
        self.active_windows: Dict[str, EventWindow] = {}
        self.closed_windows: Dict[str, EventWindow] = {}
        self.pending_events: List[SecurityEvent] = []
        self.max_active_windows = _read_positive_int_env(
            'SHORT_TTP_MAX_ACTIVE_WINDOWS',
            DEFAULT_MAX_ACTIVE_WINDOWS,
            MAX_ACTIVE_WINDOWS_CAP,
        )
        self.max_closed_windows = _read_positive_int_env(
            'SHORT_TTP_MAX_CLOSED_WINDOWS',
            DEFAULT_MAX_CLOSED_WINDOWS,
            MAX_CLOSED_WINDOWS_CAP,
        )
        self.max_pending_events = _read_positive_int_env(
            'SHORT_TTP_MAX_PENDING_EVENTS',
            DEFAULT_MAX_PENDING_EVENTS,
            MAX_PENDING_EVENTS_CAP,
        )
        
        self.running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        self._process_task: Optional[asyncio.Task] = None
        self._timeout_check_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """启动窗口管理器"""
        self.running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._process_task = asyncio.create_task(self._process_loop())
        self._timeout_check_task = asyncio.create_task(self._timeout_check_loop())
        logger.info("动态事件窗口管理器已启动")
    
    async def stop(self):
        """停止窗口管理器"""
        self.running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
        
        if self._timeout_check_task:
            self._timeout_check_task.cancel()
            try:
                await self._timeout_check_task
            except asyncio.CancelledError:
                pass
        
        # 处理剩余的事件
        if self.pending_events:
            await self._process_pending_events()
        
        logger.info("动态事件窗口管理器已停止")
    
    async def add_event(self, event: SecurityEvent):
        """添加事件到处理队列"""
        logger.debug(f"添加事件到处理队列: {event.event_type}, ID: {event.get_unique_id()}, 时间: {event.get_event_time()}")
        if len(self.pending_events) >= self.max_pending_events:
            dropped_event = self.pending_events.pop(0)
            logger.warning(
                "待处理事件队列已达上限 %s，丢弃最早事件: %s",
                self.max_pending_events,
                dropped_event.get_unique_id(),
            )
        self.pending_events.append(event)
    
    async def _process_loop(self):
        """处理事件循环"""
        while self.running:
            try:
                if self.pending_events:
                    await self._process_pending_events()
                
                await asyncio.sleep(0.1)  # 100ms检查一次
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"处理事件循环异常: {e}")
                await asyncio.sleep(1)
    
    async def _process_pending_events(self):
        """处理待处理事件"""
        if not self.pending_events:
            return
        
        logger.debug(f"开始处理待处理事件，共 {len(self.pending_events)} 个事件")
        
        # 按时间排序事件
        self.pending_events.sort(key=lambda e: e.get_event_time())
        
        for event in self.pending_events:
            placed = False
            
            # 尝试将事件放入现有的活动窗口
            for window in self.active_windows.values():
                if window.add_event(event):
                    placed = True
                    logger.debug(f"事件已添加到现有窗口, window_id: {window.window_id}")
                    break
            
            # 如果无法放入现有窗口，创建新窗口
            if not placed:
                new_window = EventWindow(
                    window_id=str(uuid.uuid4()),
                    start_time=event.get_event_time()
                )
                new_window.add_event(event)
                self.active_windows[new_window.window_id] = new_window
                await self._enforce_active_window_limit()
                
                logger.debug(f"创建新窗口: {new_window.window_id}")
                logger.debug(f"事件已添加到新窗口, window_id: {new_window.window_id}")
            
        
        # 清空已处理的事件
        self.pending_events.clear()
        
        logger.debug(f"当前活跃窗口: {len(self.active_windows)}, 已关闭窗口: {len(self.closed_windows)}")
        
        # 检查并关闭超时的窗口
        await self._check_timeout_windows()
    
    async def _check_timeout_windows(self):
        """检查并关闭超时的窗口"""
        current_time = ChinaTime.now()  # 已经是东八区时间
        windows_to_close = []
        
        for window_id, window in self.active_windows.items():
            # 确保时间比较的一致性，将current_time转换为offset-naive
            current_time_naive = to_naive(current_time)
            
            if window.events and (current_time_naive - window.last_event_time).total_seconds() > self.window_timeout:
                logger.debug(f"窗口ID:{window_id},current_time:{current_time_naive},window.last_event_time:{window.last_event_time},间隔时长{(current_time_naive - window.last_event_time).total_seconds()}超过阈值{self.window_timeout}")
                windows_to_close.append(window_id)
        
        # 关闭超时的窗口
        for window_id in windows_to_close:
            window = self.active_windows[window_id]
            window.close_window()
            
            # 如果窗口中有事件，就移动到已关闭窗口
            if window.get_event_count() >= 1:  # 至少1个事件就有效
                await self._store_closed_window(window)
                logger.debug(f"窗口已关闭: {window_id}, 事件数: {window.get_event_count()}, 持续时间: {window.get_duration()}秒")
                for event in window.events:
                    logger.debug(f"窗口事件详情 - ID: {event.get_unique_id()}, 类型: {event.event_type}, 时间: {event.get_event_time()}")
            else:
                logger.debug(f"窗口丢弃（事件不足）: {window_id}, 事件数: {window.get_event_count()}")
            
            del self.active_windows[window_id]
    
    async def _store_closed_window(self, window: EventWindow):
        """Store a closed window while enforcing the closed-window backlog limit."""
        self.closed_windows[window.window_id] = window
        await self._enforce_closed_window_limit()

    async def _enforce_closed_window_limit(self):
        """Drop oldest closed windows once the backlog reaches its configured cap."""
        while len(self.closed_windows) > self.max_closed_windows:
            oldest_window_id, oldest_window = min(
                self.closed_windows.items(),
                key=lambda item: item[1].start_time,
            )
            del self.closed_windows[oldest_window_id]
            logger.warning(
                "已关闭窗口积压超过上限 %s，丢弃最早窗口: %s",
                self.max_closed_windows,
                oldest_window.window_id,
            )

    async def _enforce_active_window_limit(self):
        """Bound active windows by closing and queuing the oldest windows first."""
        while len(self.active_windows) > self.max_active_windows:
            oldest_window_id, oldest_window = min(
                self.active_windows.items(),
                key=lambda item: item[1].start_time,
            )
            oldest_window.close_window()
            if oldest_window.get_event_count() >= 1:
                await self._store_closed_window(oldest_window)
            del self.active_windows[oldest_window_id]
            logger.warning(
                "活跃窗口数量超过上限 %s，提前关闭最早窗口: %s",
                self.max_active_windows,
                oldest_window.window_id,
            )

    async def _timeout_check_loop(self):
        """超时检查循环 - 独立于事件处理"""
        while self.running:
            try:
                await asyncio.sleep(self.window_timeout / 2)  # 每半窗口超时时间检查一次
                await self._check_timeout_windows()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"超时检查循环异常: {e}")
                await asyncio.sleep(1)
    
    async def _cleanup_loop(self):
        """清理循环"""
        while self.running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_old_windows()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理循环异常: {e}")
                await asyncio.sleep(10)
    
    async def _cleanup_old_windows(self):
        """清理旧的已关闭窗口"""
        from shared.utils.timezone import to_naive
        cutoff_time_naive = to_naive(ChinaTime.now() - timedelta(hours=1))
        
        windows_to_remove = []
        for window_id, window in self.closed_windows.items():
            if window.end_time < cutoff_time_naive:
                windows_to_remove.append(window_id)
        
        for window_id in windows_to_remove:
            del self.closed_windows[window_id]
            logger.debug(f"清理旧窗口: {window_id}")
    
    async def get_ready_windows(self, limit: Optional[int] = None) -> List[EventWindow]:
        """获取已准备好处理的窗口，可通过limit限制一次返回数量"""
        if limit is not None:
            limit = max(0, limit)
            if limit == 0:
                return []
            return heapq.nsmallest(limit, self.closed_windows.values(), key=lambda w: w.start_time)

        ready_windows = list(self.closed_windows.values())
        ready_windows.sort(key=lambda w: w.start_time)

        return ready_windows
    
    async def get_window_stats(self) -> Dict:
        """获取窗口统计信息"""
        return {
            "active_windows": len(self.active_windows),
            "closed_windows": len(self.closed_windows),
            "pending_events": len(self.pending_events),
            "total_events_processed": sum(
                len(w.events) for w in list(self.active_windows.values()) + list(self.closed_windows.values())
            ),
            "max_window_size": self.max_window_size,
            "window_timeout": self.window_timeout,
            "max_active_windows": self.max_active_windows,
            "max_closed_windows": self.max_closed_windows,
            "max_pending_events": self.max_pending_events
        }
    
    async def mark_window_processed(self, window_id: str):
        """标记窗口已处理"""
        if window_id in self.closed_windows:
            del self.closed_windows[window_id]
            logger.debug(f"窗口已标记为处理完成: {window_id}")
    
    async def get_event_distribution(self) -> Dict[str, int]:
        """获取事件类型分布"""
        distribution = defaultdict(int)
        
        # 统计活动窗口中的事件
        for window in self.active_windows.values():
            for event in window.events:
                distribution[event.event_type.value] += 1
        
        # 统计已关闭窗口中的事件
        for window in self.closed_windows.values():
            for event in window.events:
                distribution[event.event_type.value] += 1
        
        return dict(distribution)
    
    async def force_close_all_windows(self):
        """强制关闭所有活动窗口"""
        for window_id, window in list(self.active_windows.items()):
            window.close_window()
            
            if window.get_event_count() >= 2:
                await self._store_closed_window(window)
                logger.debug(f"窗口强制关闭: {window_id}, 事件数: {window.get_event_count()}")
            
            del self.active_windows[window_id]
        
        logger.info(f"已强制关闭 {len(self.active_windows)} 个活动窗口")