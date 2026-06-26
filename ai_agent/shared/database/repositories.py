import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, func, select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from shared.utils.timezone import ChinaTime, to_naive

from shared.models.events import SecurityEvent, EventType, EventSource, EventCategory
from shared.models.ttp import ShortTTP, LongTTP
from .models import Event, ShortTTP as ShortTTPModel, LongTTP as LongTTPModel, LongTTPGeneration
from .connection import CacheTTL, RedisKeyBuilder
from shared.models.events import FalcoAlertEvent, FalcoRawEvent, OpenRASPAlertEvent, OpenRASPRawEvent

logger = logging.getLogger(__name__)


class EventRepository:
    """事件数据仓库"""
    
    def __init__(self, db: AsyncSession, redis):
        self.db = db
        self.redis = redis
    
    async def store_event(self, event: SecurityEvent) -> bool:
        """存储事件到数据库和缓存"""
        try:
            # 使用Pydantic的model_dump处理datetime序列化，确保所有datetime都被转换为字符串
            raw_data_dict = event.raw_event.model_dump(mode='json')
            
            # 存储到PostgreSQL
            db_event = Event(
                id=event.get_unique_id(),
                event_type=event.event_type.value,
                source=event.source.value,
                category=event.category.value,
                raw_data=raw_data_dict,
                received_time=to_naive(event.received_time)
            )
            
            self.db.add(db_event)
            await self.db.commit()
            
            # 存储到Redis缓存
            event_key = RedisKeyBuilder.event_key(event.get_unique_id())
            # 使用Pydantic的model_dump_json来处理datetime序列化
            await self.redis.setex(
                event_key,
                CacheTTL.EVENT_CACHE,
                event.model_dump_json()
            )

            logger.debug(f"事件存储成功: {event.get_unique_id()}")
            return True
            
        except (SQLAlchemyError, IntegrityError) as e:
            await self.db.rollback()
            logger.error(f"事件存储失败（数据库错误）: {e}")
            return False
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"事件存储失败（缓存错误）: {e}")
            return False
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise

    async def get_event(self, event_id: str) -> Optional[SecurityEvent]:
        """获取单个事件"""
        try:
            # 先从缓存获取
            event_key = RedisKeyBuilder.event_key(event_id)
            cached_event = await self.redis.get(event_key)
            
            if cached_event:
                event_data = json.loads(cached_event)
                return SecurityEvent.model_validate(event_data)
            
            # 从数据库获取
            result = await self.db.execute(
                select(Event).where(Event.id == event_id)
            )
            db_event = result.scalar_one_or_none()
            
            if not db_event:
                return None
            
            # 重建SecurityEvent对象
            raw_data = db_event.raw_data
            event_type = EventType(db_event.event_type)
            
            # 根据事件类型重建原始事件对象
            if event_type == EventType.FALCO_ALERT:
                raw_event = FalcoAlertEvent.model_validate(raw_data)
            elif event_type == EventType.FALCO_RAW:
                raw_event = FalcoRawEvent.model_validate(raw_data)
            elif event_type == EventType.OPENRASP_ALERT:
                raw_event = OpenRASPAlertEvent.model_validate(raw_data)
            elif event_type == EventType.OPENRASP_RAW:
                raw_event = OpenRASPRawEvent.model_validate(raw_data)
            elif event_type == EventType.OPENRASP_RAW_SQL:
                from shared.models.events import OpenRASPRawSQLEvent
                raw_event = OpenRASPRawSQLEvent.model_validate(raw_data)
            elif event_type == EventType.SURICATA_ALERT:
                from shared.models.events import SuricataAlertEvent
                raw_event = SuricataAlertEvent.model_validate(raw_data)
            else:
                return None
            
            security_event = SecurityEvent(
                event_id=db_event.id,
                event_type=event_type,
                raw_event=raw_event,
                received_time=db_event.received_time,
                source=EventSource(db_event.source),
                category=EventCategory(db_event.category)
            )
            
            # 缓存到Redis
            await self.redis.setex(
                event_key,
                CacheTTL.EVENT_CACHE,
                security_event.model_dump_json()
            )
            
            return security_event
            
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取事件失败: {e}")
            return None
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_events_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        event_types: Optional[List[EventType]] = None,
        sources: Optional[List[EventSource]] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[SecurityEvent]:
        """按时间范围获取事件"""
        try:
            # 确保时间参数是offset-naive
            start_time_naive = to_naive(start_time)
            end_time_naive = to_naive(end_time)
            
            query = select(Event).where(
                and_(
                    Event.received_time >= start_time_naive,
                    Event.received_time <= end_time_naive
                )
            ).order_by(Event.received_time.desc()).limit(limit).offset(offset)
            
            if event_types:
                event_type_values = [et.value for et in event_types]
                query = query.where(Event.event_type.in_(event_type_values))
            
            if sources:
                source_values = [s.value for s in sources]
                query = query.where(Event.source.in_(source_values))
            
            result = await self.db.execute(query)
            db_events = result.scalars().all()
            
            events = []
            for db_event in db_events:
                event = await self.get_event(db_event.id)
                if event:
                    events.append(event)
            
            return events
            
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"按时间范围获取事件失败: {e}")
            return []
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_unprocessed_events(
        self,
        limit: int = 1000,
        offset: int = 0
    ) -> List[SecurityEvent]:
        """获取未处理的事件"""
        try:
            result = await self.db.execute(
                select(Event)
                .where(Event.processed == False)
                .order_by(Event.received_time.asc())
                .limit(limit)
                .offset(offset)
            )
            db_events = result.scalars().all()
            
            events = []
            for db_event in db_events:
                event = await self.get_event(db_event.id)
                if event:
                    events.append(event)
            
            return events
            
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取未处理事件失败: {e}")
            return []
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def mark_events_processed(self, event_ids: List[str]) -> bool:
        """标记事件为已处理"""
        try:
            await self.db.execute(
                Event.__table__.update()
                .where(Event.id.in_(event_ids))
                .values(processed=True)
            )
            await self.db.commit()
            return True
            
        except (SQLAlchemyError, IntegrityError) as e:
            await self.db.rollback()
            logger.error(f"标记事件处理状态失败: {e}")
            return False
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_event_statistics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, int]:
        """获取事件统计信息"""
        try:
            query = select(
                Event.event_type,
                func.count().label('count')
            )
            
            if start_time and end_time:
                # 确保时间参数是offset-naive
                start_time_naive = to_naive(start_time)
                end_time_naive = to_naive(end_time)
                query = query.where(
                    and_(
                        Event.received_time >= start_time_naive,
                        Event.received_time <= end_time_naive
                    )
                )
            
            query = query.group_by(Event.event_type)
            result = await self.db.execute(query)
            
            stats = {
                'total_events': 0,
                'falco_alert': 0,
                'falco_raw': 0,
                'openrasp_alert': 0,
                'openrasp_raw': 0
            }
            
            for row in result:
                event_type = row[0]
                count = row[1]
                stats[event_type] = count
                stats['total_events'] += count
            
            return stats
            
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取事件统计失败: {e}")
            return {'total_events': 0}


        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
class TTPRepository:
    """TTP数据仓库"""
    
    def __init__(self, db: AsyncSession, redis):
        self.db = db
        self.redis = redis
    
    async def store_short_ttp(self, short_ttp: ShortTTP) -> bool:
        """存储短期TTP"""
        try:
            # 存储到PostgreSQL
            db_short_ttp = ShortTTPModel(
                id=short_ttp.id,
                created_at=to_naive(short_ttp.created_at),
                end_at=to_naive(short_ttp.end_at),
                confidence=short_ttp.confidence,
                summary=short_ttp.summary,
                event_count=short_ttp.event_count,
                source_event_ids=short_ttp.source_events,
                ttps_data=[t.model_dump(mode='json') for t in short_ttp.ttps]
            )
            
            self.db.add(db_short_ttp)
            await self.db.commit()
            
            # 刷新对象以获取数据库生成的值
            await self.db.refresh(db_short_ttp)
            
            # 打印created_at_db值
            logger.info(f"📝 ShortTTP存储完成 - ID: {short_ttp.id}")
            logger.info(f"   📅 TTP创建时间: {short_ttp.created_at}")
            logger.info(f"   🗄️  数据库创建时间: {db_short_ttp.created_at_db}")
            logger.info(f"   ⚡ 时间差: {db_short_ttp.created_at_db - to_naive(short_ttp.created_at)}")
            
            # 存储到Redis缓存
            ttp_key = RedisKeyBuilder.short_ttp_key(short_ttp.id)
            await self.redis.setex(
                ttp_key,
                CacheTTL.SHORT_TTP_CACHE,
                short_ttp.model_dump_json()
            )
            
            logger.debug(f"短期TTP存储成功: {short_ttp.id}")
            return True
            
        except (SQLAlchemyError, IntegrityError) as e:
            await self.db.rollback()
            logger.error(f"短期TTP存储失败: {e}")
            return False
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_short_ttp(self, ttp_id: str) -> Optional[ShortTTP]:
        """获取短期TTP"""
        try:
            # 从缓存获取
            ttp_key = RedisKeyBuilder.short_ttp_key(ttp_id)
            cached_ttp = await self.redis.get(ttp_key)
            
            if cached_ttp:
                return ShortTTP.model_validate_json(cached_ttp)
            
            # 从数据库获取
            result = await self.db.execute(
                select(ShortTTPModel).where(ShortTTPModel.id == ttp_id)
            )
            db_ttp = result.scalar_one_or_none()
            
            if not db_ttp:
                return None
            
            # 打印数据库创建时间
            logger.info(f"🔍 获取ShortTTP - ID: {db_ttp.id}")
            logger.info(f"   📅 TTP创建时间: {db_ttp.created_at}")
            logger.info(f"   🗄️  数据库创建时间: {db_ttp.created_at_db}")
            logger.info(f"   ⚡ 时间差: {db_ttp.created_at_db - db_ttp.created_at}")
            
            # 重建ShortTTP对象
            short_ttp = ShortTTP(
                id=db_ttp.id,
                created_at=db_ttp.created_at,
                end_at=db_ttp.end_at,
                ttps=db_ttp.ttps_data,
                confidence=db_ttp.confidence,
                summary=db_ttp.summary,
                event_count=db_ttp.event_count,
                source_events=db_ttp.source_event_ids
            )
            
            # 缓存到Redis
            await self.redis.setex(
                ttp_key,
                CacheTTL.SHORT_TTP_CACHE,
                short_ttp.model_dump_json()
            )
            
            return short_ttp
            
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取短期TTP失败: {e}")
            return None
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_short_ttps_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        min_confidence: float = 0.0,
        limit: int = 1000,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> List[ShortTTP]:
        """按时间范围获取短期TTP"""
        try:
            # 确保时间参数是offset-naive
            start_time_naive = to_naive(start_time)
            end_time_naive = to_naive(end_time)
            
            # 确定排序字段
            if sort_by == "created_at_db":
                order_column = ShortTTPModel.created_at_db
            elif sort_by == "confidence":
                order_column = ShortTTPModel.confidence
            elif sort_by == "event_count":
                order_column = ShortTTPModel.event_count
            else:
                order_column = ShortTTPModel.created_at
            
            # 确定排序方向
            if sort_order.lower() == "asc":
                order_clause = order_column.asc()
            else:
                order_clause = order_column.desc()
            
            result = await self.db.execute(
                select(ShortTTPModel)
                .where(
                    and_(
                        ShortTTPModel.created_at_db >= start_time_naive,
                        ShortTTPModel.created_at_db <= end_time_naive,
                        ShortTTPModel.confidence >= min_confidence
                    )
                )
                .order_by(order_clause)
                .limit(limit)
                .offset(offset)
            )
            db_ttps = result.scalars().all()
            
            ttps = []            
            for db_ttp in db_ttps:
                ttp = await self.get_short_ttp(db_ttp.id)
                if ttp:
                    ttps.append(ttp)
            
            return ttps
            
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"按时间范围获取短期TTP失败: {e}")
            return []
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def store_long_ttp(self, long_ttp: LongTTP) -> bool:
        """存储长期TTP"""
        try:
            # 存储到PostgreSQL
            db_long_ttp = LongTTPModel(
                id=long_ttp.id,
                created_at=to_naive(long_ttp.created_at),
                updated_at=to_naive(long_ttp.updated_at),
                analysis_start_time=to_naive(long_ttp.analysis_start_time),
                analysis_end_time=to_naive(long_ttp.analysis_end_time),
                short_ttps=long_ttp.short_ttps,
                summary=long_ttp.summary,
                total_events=long_ttp.total_events,
                risk_score=long_ttp.risk_score,
                key_threats=long_ttp.key_threats,
                recommendations=long_ttp.recommendations,
                apts_data=[apt.model_dump(mode='json') for apt in long_ttp.apts]
            )
            
            self.db.add(db_long_ttp)
            await self.db.commit()
            
            # 存储到Redis缓存
            ttp_key = RedisKeyBuilder.long_ttp_key(long_ttp.id)
            await self.redis.setex(
                ttp_key,
                CacheTTL.LONG_TTP_CACHE,
                long_ttp.model_dump_json()
            )
            
            logger.debug(f"长期TTP存储成功: {long_ttp.id}")
            return True
            
        except (SQLAlchemyError, IntegrityError) as e:
            await self.db.rollback()
            logger.error(f"长期TTP存储失败: {e}")
            return False
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_long_ttp(self, ttp_id: str) -> Optional[LongTTP]:
        """获取长期TTP"""
        try:
            # 从缓存获取
            ttp_key = RedisKeyBuilder.long_ttp_key(ttp_id)
            cached_ttp = await self.redis.get(ttp_key)
            
            if cached_ttp:
                return LongTTP.model_validate_json(cached_ttp)
            
            # 从数据库获取
            result = await self.db.execute(
                select(LongTTPModel).where(LongTTPModel.id == ttp_id)
            )
            db_ttp = result.scalar_one_or_none()
            
            if not db_ttp:
                return None
            
            # 重建LongTTP对象
            long_ttp = LongTTP(
                id=db_ttp.id,
                created_at=db_ttp.created_at,
                updated_at=db_ttp.updated_at,
                analysis_start_time=db_ttp.analysis_start_time,
                analysis_end_time=db_ttp.analysis_end_time,
                short_ttps=db_ttp.short_ttps,
                summary=db_ttp.summary,
                apts=db_ttp.apts_data,
                total_events=db_ttp.total_events,
                risk_score=db_ttp.risk_score,
                key_threats=db_ttp.key_threats,
                recommendations=db_ttp.recommendations
            )
            
            # 缓存到Redis
            await self.redis.setex(
                ttp_key,
                CacheTTL.LONG_TTP_CACHE,
                long_ttp.model_dump_json()
            )
            
            return long_ttp
            
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取长期TTP失败: {e}")
            return None
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_long_ttps_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        min_risk_score: float = 0.0,
        limit: int = 100,
        offset: int = 0
    ) -> List[LongTTP]:
        """按时间范围获取长期TTP"""
        try:
            # 确保时间参数是offset-naive
            start_time_naive = to_naive(start_time)
            end_time_naive = to_naive(end_time)
            
            result = await self.db.execute(
                select(LongTTPModel)
                .where(
                    and_(
                        LongTTPModel.created_at >= start_time_naive,
                        LongTTPModel.created_at <= end_time_naive,
                        LongTTPModel.risk_score >= min_risk_score
                    )
                )
                .order_by(desc(LongTTPModel.created_at))
                .limit(limit)
                .offset(offset)
            )
            db_ttps = result.scalars().all()
            
            ttps = []
            for db_ttp in db_ttps:
                ttp = await self.get_long_ttp(db_ttp.id)
                if ttp:
                    ttps.append(ttp)
            
            return ttps
            
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"按时间范围获取长期TTP失败: {e}")
            return []
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_long_ttps(
        self,
        hours: Optional[int] = None,
        min_risk_score: float = 0.0,
        page: int = 1,
        size: int = 10,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> Dict[str, Any]:
        """分页获取长期TTP列表"""
        try:
            end_time = to_naive(ChinaTime.now())
            start_time = end_time - timedelta(hours=hours) if hours else None

            # 确定排序字段
            if sort_by == "risk_score":
                order_column = LongTTPModel.risk_score
            elif sort_by == "total_events":
                order_column = LongTTPModel.total_events
            else:
                order_column = LongTTPModel.created_at

            # 确定排序方向
            if sort_order.lower() == "asc":
                order_clause = order_column.asc()
            else:
                order_clause = order_column.desc()

            # 构建查询条件
            conditions = [LongTTPModel.risk_score >= min_risk_score]
            if start_time:
                conditions.append(LongTTPModel.created_at >= start_time)
                conditions.append(LongTTPModel.created_at <= end_time)

            # 查询总数
            count_result = await self.db.execute(
                select(func.count()).where(and_(*conditions))
            )
            total = count_result.scalar()

            offset = (page - 1) * size

            result = await self.db.execute(
                select(LongTTPModel)
                .where(and_(*conditions))
                .order_by(order_clause)
                .limit(size)
                .offset(offset)
            )
            db_ttps = result.scalars().all()

            ttps = []
            for db_ttp in db_ttps:
                ttp = await self.get_long_ttp(db_ttp.id)
                if ttp:
                    ttps.append(ttp)

            return {
                "items": ttps,
                "total": total
            }

        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取长期TTP列表失败: {e}")
            return {"items": [], "total": 0}

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_top_risk_long_ttps(
        self,
        limit: int = 10,
        hours: int = 24
    ) -> List[LongTTP]:
        """获取高风险的长期TTP"""
        try:
            end_time = to_naive(ChinaTime.now())
            start_time = end_time - timedelta(hours=hours)
            
            result = await self.db.execute(
                select(LongTTPModel)
                .where(
                    and_(
                        LongTTPModel.created_at >= start_time,
                        LongTTPModel.created_at <= end_time
                    )
                )
                .order_by(desc(LongTTPModel.risk_score))
                .limit(limit)
            )
            db_ttps = result.scalars().all()
            
            ttps = []
            for db_ttp in db_ttps:
                ttp = await self.get_long_ttp(db_ttp.id)
                if ttp:
                    ttps.append(ttp)
            
            return ttps
            
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取高风险长期TTP失败: {e}")
            return []
    
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    
    async def create_long_ttp_generation(self, generation_data: Dict[str, any]) -> str:
        """创建 Long TTP 生成记录"""
        try:
            generation = LongTTPGeneration(**generation_data)
            self.db.add(generation)
            await self.db.commit()
            await self.db.refresh(generation)
            return generation.id
        except (SQLAlchemyError, IntegrityError) as e:
            await self.db.rollback()
            logger.error(f"创建 Long TTP 生成记录失败: {e}")
            raise

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def update_long_ttp_generation(self, generation_id: str, update_data: Dict[str, any]):
        """更新 Long TTP 生成记录"""
        try:
            await self.db.execute(
                LongTTPGeneration.__table__.update()
                .where(LongTTPGeneration.id == generation_id)
                .values(**update_data)
            )
            await self.db.commit()
        except (SQLAlchemyError, IntegrityError) as e:
            await self.db.rollback()
            logger.error(f"更新 Long TTP 生成记录失败: {e}")
            raise

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_long_ttp_generation_by_id(self, generation_id: str) -> Optional[LongTTPGeneration]:
        """根据 ID 获取 Long TTP 生成记录"""
        try:
            return await self.db.get(LongTTPGeneration, generation_id)
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取 Long TTP 生成记录失败: {e}")
            return None

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_recent_long_ttp_generation_by_short_ttp(self, short_ttp_id: str) -> Optional[LongTTPGeneration]:
        """根据 Short TTP ID 获取最近一次的 Long TTP 生成记录"""
        try:
            result = await self.db.execute(
                select(LongTTPGeneration)
                .where(LongTTPGeneration.short_ttp_id == short_ttp_id)
                .order_by(desc(LongTTPGeneration.started_at))
                .limit(1)
            )
            return result.scalar_one_or_none()
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取 Long TTP 生成记录失败: {e}")
            return None

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_all_long_ttp_generations_by_short_ttp(self, short_ttp_id: str) -> List[LongTTPGeneration]:
        """根据 Short TTP ID 获取所有 Long TTP 生成记录"""
        try:
            result = await self.db.execute(
                select(LongTTPGeneration)
                .where(LongTTPGeneration.short_ttp_id == short_ttp_id)
                .order_by(desc(LongTTPGeneration.started_at))
            )
            return list(result.scalars().all())
        except (SQLAlchemyError, ValueError, TypeError) as e:
            logger.error(f"获取 Long TTP 生成记录失败: {e}")
            return []

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def delete_long_ttp(self, long_ttp_id: str) -> bool:
        """删除指定的长期TTP及其关联数据"""
        try:
            from shared.database.models import LongTTPModel, LongTTPEvent, LongTTPShortTTP

            # 删除关联的事件关联
            await self.db.execute(
                LongTTPEvent.__table__.delete().where(LongTTPEvent.long_ttp_id == long_ttp_id)
            )

            # 删除关联的短期TTP关联
            await self.db.execute(
                LongTTPShortTTP.__table__.delete().where(LongTTPShortTTP.long_ttp_id == long_ttp_id)
            )

            # 删除长期TTP本身
            await self.db.execute(
                LongTTPModel.__table__.delete().where(LongTTPModel.id == long_ttp_id)
            )

            # 删除Redis缓存
            ttp_key = RedisKeyBuilder.long_ttp_key(long_ttp_id)
            await self.redis.delete(ttp_key)

            await self.db.commit()

            logger.info(f"长期TTP删除成功: {long_ttp_id}")
            return True

        except (SQLAlchemyError, IntegrityError) as e:
            await self.db.rollback()
            logger.error(f"长期TTP删除失败: {e}")
            return False

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def delete_long_ttp_generation(self, generation_id: str) -> bool:
        """删除指定的Long TTP生成记录"""
        try:
            await self.db.execute(
                LongTTPGeneration.__table__.delete().where(LongTTPGeneration.id == generation_id)
            )

            await self.db.commit()

            logger.info(f"Long TTP生成记录删除成功: {generation_id}")
            return True

        except (SQLAlchemyError, IntegrityError) as e:
            await self.db.rollback()
            logger.error(f"Long TTP生成记录删除失败: {e}")
            return False
        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
