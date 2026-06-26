"""
人机反馈会话管理模块
用于管理 LangGraph interrupt 状态下的人机交互会话
基于 Redis 持久化，支持服务重启后恢复
"""
import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from shared.database.connection import CacheTTL, RedisKeyBuilder, get_redis

logger = logging.getLogger(__name__)


class FeedbackStatus(str, Enum):
    """反馈会话状态"""
    GENERATING = "generating"    # 正在生成中
    PENDING = "pending"          # 等待用户反馈
    RESPONDED = "responded"      # 用户已反馈，正在恢复执行
    COMPLETED = "completed"      # 流程已完成
    ERROR = "error"              # 执行出错
    TIMEOUT = "timeout"          # 超时


@dataclass
class FeedbackHistoryItem:
    """人机反馈历史记录项"""
    step: int
    timestamp: datetime
    question: str
    notes_preview: Optional[str] = None
    research_brief: Optional[str] = None
    user_feedback: Optional[str] = None
    status: str = "interrupt"  # interrupt / responded
    responded_at: Optional[datetime] = None  # 用户提交反馈的时间


@dataclass
class FeedbackSession:
    """人机反馈会话"""
    session_id: str
    thread_id: str
    short_ttp_id: str
    status: FeedbackStatus = FeedbackStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Interrupt 相关信息（当前/最后一次）
    interrupt_data: Optional[Dict[str, Any]] = None
    interrupt_question: str = ""

    # 用户反馈（当前/最后一次）
    user_feedback: Optional[str] = None

    # 执行结果
    final_report: Optional[str] = None
    error_message: Optional[str] = None

    # 关联的数据库生成记录ID（LongTTPGeneration.id）
    generation_id: Optional[str] = None

    # Short TTP 摘要（用于 human_feedback 节点展示，config 丢失时可兜底）
    short_ttp_summary: Optional[str] = None

    # 人机反馈完整历史记录
    feedback_history: List[FeedbackHistoryItem] = field(default_factory=list)
    _current_step: int = 0

    # 回调函数，用于恢复图执行（不序列化到 Redis）
    resume_callback: Optional[Callable] = None


# ========== Serialization Helpers ==========

def _serialize_datetime(obj: Any) -> Any:
    """将 datetime 和 Enum 序列化为 JSON 可编码格式"""
    if isinstance(obj, datetime):
        return {"__type__": "datetime", "value": obj.isoformat()}
    if isinstance(obj, Enum):
        return {"__type__": "enum", "class": obj.__class__.__name__, "value": obj.value}
    if isinstance(obj, list):
        return [_serialize_datetime(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize_datetime(v) for k, v in obj.items()}
    return obj


def _deserialize_datetime(obj: Any) -> Any:
    """从 JSON 反序列化 datetime 和 Enum"""
    if isinstance(obj, dict) and obj.get("__type__") == "datetime":
        return datetime.fromisoformat(obj["value"])
    if isinstance(obj, dict) and obj.get("__type__") == "enum":
        if obj["class"] == "FeedbackStatus":
            return FeedbackStatus(obj["value"])
        return obj["value"]
    if isinstance(obj, list):
        return [_deserialize_datetime(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _deserialize_datetime(v) for k, v in obj.items()}
    return obj


def _session_to_dict(session: FeedbackSession) -> Dict[str, Any]:
    """FeedbackSession → dict（排除 resume_callback）"""
    data = asdict(session)
    data.pop("resume_callback", None)
    data["status"] = session.status.value
    return _serialize_datetime(data)


def _dict_to_session(data: Dict[str, Any]) -> FeedbackSession:
    """dict → FeedbackSession"""
    data = _deserialize_datetime(data)
    # 移除不需要的字段
    data.pop("resume_callback", None)
    # 重建 FeedbackHistoryItem 列表
    history = data.pop("feedback_history", [])
    feedback_history = [
        FeedbackHistoryItem(**item) if isinstance(item, dict) else item
        for item in history
    ]
    # 解析 status
    status_str = data.pop("status", "pending")
    status = FeedbackStatus(status_str) if isinstance(status_str, str) else status_str
    return FeedbackSession(
        feedback_history=feedback_history,
        status=status,
        **data
    )


def _is_short_ttp_mapping_key(key) -> bool:
    """判断是否为 short_ttp 反向映射 key"""
    if isinstance(key, bytes):
        return b"short_ttp" in key
    return "short_ttp" in key


async def _load_session_from_redis_key(redis, key) -> Optional[FeedbackSession]:
    """从 Redis key 加载单个会话"""
    data = await redis.get(key)
    if not data:
        return None
    try:
        return _dict_to_session(json.loads(data))
    except Exception as e:
        logger.warning(f"反序列化会话失败: {e}")
        return None


# ========== Redis-based Session Manager ==========

class HumanFeedbackSessionManager:
    """人机反馈会话管理器（基于 Redis 持久化）"""

    def __init__(self):
        self._lock = asyncio.Lock()

    def _redis(self):
        return get_redis()

    async def create_session(self, short_ttp_id: str, thread_id: str) -> FeedbackSession:
        """创建新的人机反馈会话"""
        async with self._lock:
            session_id = str(uuid4())
            session = FeedbackSession(
                session_id=session_id,
                thread_id=thread_id,
                short_ttp_id=short_ttp_id
            )
            await self._save_session(session)
            logger.info(f"创建人机反馈会话: {session_id}, short_ttp_id: {short_ttp_id}")
            return session

    async def get_session(self, session_id: str) -> Optional[FeedbackSession]:
        """获取会话信息"""
        redis = self._redis()
        key = RedisKeyBuilder.feedback_session_key(session_id)
        data = await redis.get(key)
        if data:
            return _dict_to_session(json.loads(data))
        return None

    async def get_session_by_short_ttp(self, short_ttp_id: str) -> Optional[FeedbackSession]:
        """通过 Short TTP ID 获取会话"""
        redis = self._redis()
        mapping_key = RedisKeyBuilder.feedback_session_by_short_ttp_key(short_ttp_id)
        session_id = await redis.get(mapping_key)
        if session_id:
            return await self.get_session(session_id)
        return None

    async def delete_session(self, session_id: str) -> bool:
        """删除会话及其 short_ttp 反向映射"""
        redis = self._redis()
        session = await self.get_session(session_id)
        if session:
            mapping_key = RedisKeyBuilder.feedback_session_by_short_ttp_key(session.short_ttp_id)
            await redis.delete(mapping_key)
        key = RedisKeyBuilder.feedback_session_key(session_id)
        result = await redis.delete(key)
        logger.info(f"删除会话: {session_id}, short_ttp_id={session.short_ttp_id if session else None}")
        return bool(result)

    async def update_interrupt_info(
        self,
        session_id: str,
        interrupt_data: Dict[str, Any],
        question: str
    ):
        """更新 interrupt 信息并记录历史"""
        async with self._lock:
            session = await self.get_session(session_id)
            if session:
                session.interrupt_data = interrupt_data
                session.interrupt_question = question
                session.updated_at = datetime.now()
                session.status = FeedbackStatus.PENDING

                # 记录到历史
                session._current_step += 1
                history_item = FeedbackHistoryItem(
                    step=session._current_step,
                    timestamp=datetime.now(),
                    question=question,
                    notes_preview=interrupt_data.get("notes_preview"),
                    research_brief=interrupt_data.get("research_brief"),
                    status="interrupt"
                )
                session.feedback_history.append(history_item)
                await self._save_session(session)
                logger.debug(f"会话 {session_id} 更新 interrupt 信息，步骤 {session._current_step}")

    async def submit_feedback(
        self,
        session_id: str,
        feedback: str
    ) -> Optional[FeedbackSession]:
        """提交用户反馈"""
        async with self._lock:
            session = await self.get_session(session_id)
            if not session:
                logger.error(f"会话 {session_id} 不存在")
                return None

            if session.status != FeedbackStatus.PENDING:
                logger.error(f"会话 {session_id} 状态不是 PENDING，当前状态: {session.status}")
                return None

            session.user_feedback = feedback
            session.status = FeedbackStatus.RESPONDED
            session.updated_at = datetime.now()

            # 在历史记录中补充用户反馈（找到最后一个未补充 feedback 的 interrupt 记录）
            for item in reversed(session.feedback_history):
                if item.status == "interrupt" and item.user_feedback is None:
                    item.user_feedback = feedback
                    item.status = "responded"
                    item.responded_at = datetime.now()
                    break

            await self._save_session(session)
            logger.info(f"会话 {session_id} 收到用户反馈: {feedback}")
            return session

    async def complete_session(
        self,
        session_id: str,
        final_report: str
    ):
        """完成会话"""
        async with self._lock:
            session = await self.get_session(session_id)
            if session:
                session.final_report = final_report
                session.status = FeedbackStatus.COMPLETED
                session.updated_at = datetime.now()
                await self._save_session(session)
                logger.info(f"会话 {session_id} 已完成")

    async def fail_session(
        self,
        session_id: str,
        error_message: str
    ):
        """标记会话失败"""
        async with self._lock:
            session = await self.get_session(session_id)
            if session:
                session.error_message = error_message
                session.status = FeedbackStatus.ERROR
                session.updated_at = datetime.now()
                await self._save_session(session)
                logger.error(f"会话 {session_id} 失败: {error_message}")

    async def get_pending_sessions(self) -> list[FeedbackSession]:
        """获取所有待处理的会话"""
        sessions = await self.get_all_sessions()
        return [
            session for session in sessions
            if session.status == FeedbackStatus.PENDING
        ]

    async def get_all_sessions(self) -> list[FeedbackSession]:
        """获取所有会话（包括 generating、pending、responded、completed、error 等）"""
        redis = self._redis()
        # 使用 scan 遍历所有 feedback_session:* 的 key
        sessions = []
        cursor = 0
        pattern = "feedback_session:*"
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            # 过滤掉反向映射 key（feedback_session:short_ttp:*）
            for key in keys:
                if _is_short_ttp_mapping_key(key):
                    continue
                session = await _load_session_from_redis_key(redis, key)
                if session:
                    sessions.append(session)
            if cursor == 0:
                break
        return sessions


    def get_session_count(self) -> int:
        """获取会话总数（异步方法，返回 coroutine）"""
        return self._get_session_count_async()

    async def _get_session_count_async(self) -> int:
        redis = self._redis()
        count = 0
        cursor = 0
        pattern = "feedback_session:*"
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                if "short_ttp" not in key_str:
                    count += 1
            if cursor == 0:
                break
        return count

    # ========== Internal Helpers ==========

    async def _save_session(self, session: FeedbackSession):
        """保存会话到 Redis"""
        redis = self._redis()
        key = RedisKeyBuilder.feedback_session_key(session.session_id)
        data = json.dumps(_session_to_dict(session), ensure_ascii=False)
        await redis.set(key, data, ex=CacheTTL.FEEDBACK_SESSION)

        # 维护反向映射：short_ttp_id -> session_id
        mapping_key = RedisKeyBuilder.feedback_session_by_short_ttp_key(session.short_ttp_id)
        await redis.set(mapping_key, session.session_id, ex=CacheTTL.FEEDBACK_SESSION)


# 全局会话管理器实例
session_manager = HumanFeedbackSessionManager()
