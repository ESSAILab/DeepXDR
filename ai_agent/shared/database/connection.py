import json
import logging
import importlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy声明式基类"""
    
    def to_dict(self):
        """将SQLAlchemy模型转换为字典"""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, database_url: str, redis_url: str):
        self.database_url = database_url
        self.redis_url = redis_url
        self.engine = None
        self.async_session = None
        self.redis_client = None
        
    async def initialize(self):
        """初始化数据库连接"""
        try:
            # PostgreSQL连接配置
            connect_args = {}
            if 'postgresql' in self.database_url:
                # 使用环境变量配置时区
                connect_args = {
                    'server_settings': {
                        'timezone': 'Asia/Shanghai'
                    }
                }
            
            self.engine = create_async_engine(
                self.database_url,
                echo=False,
                pool_pre_ping=True,
                pool_recycle=3600,
                json_serializer=lambda x: json.dumps(x, ensure_ascii=False),
                json_deserializer=json.loads,
                **({'connect_args': connect_args} if connect_args else {})
            )
            
            self.async_session = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            # Redis连接
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                max_connections=20
            )
            
            logger.info("数据库连接初始化成功")
            
        except Exception as e:
            logger.error(f"数据库连接初始化失败: {e}")
            raise
    
    async def close(self):
        """关闭数据库连接"""
        if self.engine:
            await self.engine.dispose()
        if self.redis_client:
            await self.redis_client.close()
        logger.info("数据库连接已关闭")
    
    async def create_tables(self):
        """创建数据库表"""
        importlib.import_module("shared.database.models")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("数据库表创建完成")
    
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取数据库会话"""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"数据库会话错误: {e}")
                raise
            finally:
                await session.close()
    
    def get_redis_client(self) -> redis.Redis:
        """获取Redis客户端"""
        return self.redis_client


# 全局数据库管理器实例
_db_manager: Optional[DatabaseManager] = None


def init_db_manager(database_url: str, redis_url: str) -> DatabaseManager:
    """初始化全局数据库管理器"""
    global _db_manager
    _db_manager = DatabaseManager(database_url, redis_url)
    return _db_manager


def get_db_manager() -> DatabaseManager:
    """获取全局数据库管理器"""
    if _db_manager is None:
        raise RuntimeError("数据库管理器未初始化，请先调用init_db_manager")
    return _db_manager


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的上下文管理器"""
    if _db_manager is None:
        raise RuntimeError("数据库管理器未初始化")
    async with _db_manager.get_session() as session:
        yield session


def get_redis() -> redis.Redis:
    """获取Redis客户端"""
    if _db_manager is None:
        raise RuntimeError("数据库管理器未初始化")
    return _db_manager.get_redis_client()


class RedisKeyBuilder:
    """Redis键构建器"""
    
    @staticmethod
    def event_key(event_id: str) -> str:
        return f"event:{event_id}"
    
    @staticmethod
    def short_ttp_key(ttp_id: str) -> str:
        return f"short_ttp:{ttp_id}"
    
    @staticmethod
    def long_ttp_key(ttp_id: str) -> str:
        return f"long_ttp:{ttp_id}"
    
    @staticmethod
    def event_window_key(window_id: str) -> str:
        return f"event_window:{window_id}"
    
    @staticmethod
    def pending_events_key() -> str:
        return "pending_events"
    
    @staticmethod
    def processing_queue_key() -> str:
        return "processing_queue"
    
    @staticmethod
    def ttp_analysis_cache_key(analysis_type: str, event_ids: str) -> str:
        return f"ttp_analysis:{analysis_type}:{hash(event_ids)}"

    @staticmethod
    def feedback_session_key(session_id: str) -> str:
        return f"feedback_session:{session_id}"

    @staticmethod
    def feedback_session_by_short_ttp_key(short_ttp_id: str) -> str:
        return f"feedback_session:short_ttp:{short_ttp_id}"


class CacheTTL:
    """缓存过期时间配置（秒）"""
    EVENT_CACHE = 3600  # 1小时
    SHORT_TTP_CACHE = 7200  # 2小时
    LONG_TTP_CACHE = 86400  # 24小时
    ANALYSIS_CACHE = 1800  # 30分钟
    WINDOW_CACHE = 300  # 5分钟
    FEEDBACK_SESSION = 604800  # 7天
