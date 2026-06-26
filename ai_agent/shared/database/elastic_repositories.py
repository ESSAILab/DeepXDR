"""
ElasticSearch数据仓库实现
专门处理STTP数据的存储和查询（替代PostgreSQL）
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from shared.models.events import EventType

from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from shared.database.elasticsearch_client_v8 import get_es_client
from shared.database.connection import get_db
from shared.database.es_common import ESError
from shared.database.models import LongTTPGeneration
from shared.utils.timezone import to_naive
from sqlalchemy import select, desc, func, and_

logger = logging.getLogger(__name__)


class ShortTTPESRepository:
    """短期TTP的ElasticSearch数据仓库"""

    def __init__(self):
        self.es_client = get_es_client()

    # 无需初始化，使用现有连接

    async def save_short_ttp(self, sttp_data: Dict[str, Any]) -> bool:
        """保存短期TTP到ElasticSearch"""
        try:
            # 转换数据格式
            es_doc = self._convert_to_es_format(sttp_data)

            # 保存到ES
            success = self.es_client.save_sttp(es_doc)
            if success:
                logger.info(f"短期TTP保存成功: {es_doc['id']}")
            return success

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"保存短期TTP失败: {e}")
            return False

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def save_short_ttps_batch(self, sttp_data_list: List[Dict[str, Any]]) -> bool:
        """批量保存短期TTP到ElasticSearch"""
        try:
            if not sttp_data_list:
                return True

            # 转换数据格式
            es_docs = [self._convert_to_es_format(data) for data in sttp_data_list]

            # 批量保存到ES
            success = self.es_client.bulk_save_sttp(es_docs)
            if success:
                logger.info(f"批量保存短期TTP成功，数量: {len(es_docs)}")
            return success

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"批量保存短期TTP失败: {e}")
            return False

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_short_ttp_by_id(self, sttp_id: str) -> Optional[Dict[str, Any]]:
        """根据ID获取短期TTP"""
        try:
            # 直接从ES查询
            result = self.es_client.get_sttp_by_id(sttp_id)
            if result:
                # 转换为API后端期望的格式
                return self._format_api_response(result)
            return None

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"获取短期TTP失败 - ID: {sttp_id}, 错误: {e}")
            return None

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_short_ttps(self, offset: int = 0, limit: int = 100,
                           start_time: Optional[datetime] = None,
                           end_time: Optional[datetime] = None,
                           min_confidence: float = 0.0,
                           max_confidence: float = 1.0) -> Dict[str, Any]:
        """获取短期TTP列表（带过滤条件）"""
        try:
            # 从ES搜索
            result = self.es_client.search_ttps_with_filter(
                start_time=start_time,
                end_time=end_time,
                min_confidence=min_confidence,
                max_confidence=max_confidence,
                offset=offset,
                limit=limit
            )

            # 格式化返回数据，保持与原有API一致
            items = []
            for item in result.get("items", []):
                formatted_item = self._format_api_response(item)
                if formatted_item:
                    items.append(formatted_item)

            return {
                "items": items,
                "total": result.get("total", 0),  # ES返回的总数
                "offset": offset,
                "limit": limit
            }

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"获取短期TTP列表失败: {e}")
            return {"items": [], "total": 0, "offset": offset, "limit": limit}

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_short_ttp_statistics(self) -> Dict[str, Any]:
        """获取短期TTP统计信息"""
        try:
            # 直接从ES获取统计
            stats = self.es_client.get_sttp_stats()

            # 与原有API保持一致
            return {
                "total_ttps": stats["total_ttps"],
                "max_confidence": stats["max_confidence"] or 0.0,
                "avg_confidence": stats["avg_confidence"] or 0.0,
                "total_events": stats["total_events"],
                "high_risk_ttps": stats["high_risk_ttps"],
                "medium_risk_ttps": stats["medium_risk_ttps"],
                "low_risk_ttps": stats["low_risk_ttps"]
            }

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"获取短期TTP统计信息失败: {e}")
            return {
                "total_ttps": 0,
                "max_confidence": 0.0,
                "avg_confidence": 0.0,
                "total_events": 0,
                "high_risk_ttps": 0,
                "medium_risk_ttps": 0,
                "low_risk_ttps": 0
            }

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def _convert_to_es_format(self, sttp_data: Dict[str, Any]) -> Dict[str, Any]:
        """转换为ES存储格式"""
        # 确保字段结构和格式正确
        es_doc = {
            "id": sttp_data.get("id"),
            "created_at": sttp_data.get("created_at"),
            "end_at": sttp_data.get("end_at"),
            "ttps": sttp_data.get("ttps", []),
            "confidence": sttp_data.get("confidence", 0.0),
            "summary": sttp_data.get("summary", ""),
            "event_count": sttp_data.get("event_count", 0),
            "source_events": sttp_data.get("source_events", []),
            "attacker_fingerprint": sttp_data.get("attacker_fingerprint"),
            "attacker_ip": sttp_data.get("attacker_ip"),  # 攻击者IP
            "event_ids": sttp_data.get("source_events", [])  # 兼容事件ID列表
        }
        return es_doc

    def _format_api_response(self, es_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """格式化为API返回格式，确保与原有接口完全一致"""
        try:
            # 维护API返回格式，保持与PostgreSQL版本完全一致
            response_data = {
                "id": es_doc.get("id"),
                "created_at": es_doc.get("created_at"),
                "end_at": es_doc.get("end_at"),
                "ttps": es_doc.get("ttps", []),
                "confidence": es_doc.get("confidence", 0.0),
                "summary": es_doc.get("summary", ""),
                "event_count": es_doc.get("event_count", 0),
                "source_events": es_doc.get("source_events", []),
                "attacker_fingerprint": es_doc.get("attacker_fingerprint"),
                "attacker_ip": es_doc.get("attacker_ip"),  # 攻击者IP
            }

            # 验证必要字段
            if not all(response_data.get(field) is not None for field in ["id", "created_at", "end_at"]):
                logger.warning(f"缺少必要字段的STTP文档: {es_doc}")
                return None

            return response_data

        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"格式化STTP响应数据失败: {e}")
            return None

        except Exception as e: # 新建一个兼容旧Postgres接口的快捷访问类
            logger.exception(f"未预期错误: {e}")
            raise
class MixedRepository:
    """混合仓库，提供向后兼容的接口"""

    def __init__(self, es_repo: ShortTTPESRepository):
        self.short_ttp = es_repo
        # 可以在这里添加其他仓库的实例

    def get_short_ttp_repository(self) -> ShortTTPESRepository:
        """获取短期TTP的ES仓库"""
        return self.short_ttp

    # ==================== Long TTP Generation 操作 ====================

    async def create_long_ttp_generation(self, generation_data: Dict[str, any]) -> str:
        """创建 Long TTP 生成记录"""

        try:
            # 确保所有日期时间都是不带时区的
            processed_data = generation_data.copy()
            if 'started_at' in processed_data and processed_data['started_at']:
                processed_data['started_at'] = to_naive(processed_data['started_at'])
            if 'completed_at' in processed_data and processed_data['completed_at']:
                processed_data['completed_at'] = to_naive(processed_data['completed_at'])

            async with get_db() as db:
                generation = LongTTPGeneration(**processed_data)
                db.add(generation)
                await db.commit()
                await db.refresh(generation)
                return generation.id
        except (SQLAlchemyError, IntegrityError) as e:
            logger.error(f"创建 Long TTP 生成记录失败: {e}")
            raise

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def update_long_ttp_generation(self, generation_id: str, update_data: Dict[str, any]):
        """更新 Long TTP 生成记录"""
        try:
            # 确保所有日期时间都是不带时区的
            processed_data = update_data.copy()
            if 'started_at' in processed_data and processed_data['started_at']:
                processed_data['started_at'] = to_naive(processed_data['started_at'])
            if 'completed_at' in processed_data and processed_data['completed_at']:
                processed_data['completed_at'] = to_naive(processed_data['completed_at'])

            async with get_db() as db:
                await db.execute(
                    LongTTPGeneration.__table__.update()
                    .where(LongTTPGeneration.id == generation_id)
                    .values(**processed_data)
                )
                await db.commit()
        except (SQLAlchemyError, IntegrityError) as e:
            logger.error(f"更新 Long TTP 生成记录失败: {e}")
            raise

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_long_ttp_generation_by_id(self, generation_id: str):
        """根据 ID 获取 Long TTP 生成记录"""
        try:
            async with get_db() as db:
                return await db.get(LongTTPGeneration, generation_id)
        except SQLAlchemyError as e:
            logger.exception(f"获取 Long TTP 生成记录失败: {e}")
            raise

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_recent_long_ttp_generation_by_short_ttp(self, short_ttp_id: str):
        """根据 Short TTP ID 获取最近一次的 Long TTP 生成记录"""
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(LongTTPGeneration)
                    .where(LongTTPGeneration.short_ttp_id == short_ttp_id)
                    .order_by(desc(LongTTPGeneration.started_at))
                    .limit(1)
                )
                return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.exception(f"获取 Long TTP 生成记录失败: {e}")
            raise

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_all_long_ttp_generations_by_short_ttp(self, short_ttp_id: str):
        """根据 Short TTP ID 获取所有 Long TTP 生成记录"""
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(LongTTPGeneration)
                    .where(LongTTPGeneration.short_ttp_id == short_ttp_id)
                    .order_by(desc(LongTTPGeneration.started_at))
                )
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.exception(f"获取 Long TTP 生成记录失败: {e}")
            raise

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_long_ttp_generations(
        self,
        hours: Optional[int] = None,
        page: int = 1,
        size: int = 10,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> Dict[str, Any]:
        """分页获取 Long TTP 生成记录列表"""
        from shared.utils.timezone import ChinaTime, to_naive
        try:
            end_time = to_naive(ChinaTime.now())
            start_time = end_time - timedelta(hours=hours) if hours else None

            # 确定排序字段
            if sort_by == "started_at":
                order_column = LongTTPGeneration.started_at
            elif sort_by == "status":
                order_column = LongTTPGeneration.status
            else:
                order_column = LongTTPGeneration.created_at

            # 确定排序方向
            if sort_order.lower() == "asc":
                order_clause = order_column.asc()
            else:
                order_clause = order_column.desc()

            # 构建查询条件
            conditions = []
            if start_time:
                conditions.append(LongTTPGeneration.created_at >= start_time)
                conditions.append(LongTTPGeneration.created_at <= end_time)

            async with get_db() as db:
                # 查询总数
                if conditions:
                    count_result = await db.execute(
                        select(func.count()).where(and_(*conditions))
                    )
                else:
                    count_result = await db.execute(select(func.count()))
                total = count_result.scalar()

                offset = (page - 1) * size

                # 查询数据
                query = select(LongTTPGeneration).order_by(order_clause).limit(size).offset(offset)
                if conditions:
                    query = query.where(and_(*conditions))

                result = await db.execute(query)
                records = result.scalars().all()

                return {
                    "items": list(records),
                    "total": total
                }

        except SQLAlchemyError as e:
            logger.exception(f"获取 Long TTP 生成记录列表失败: {e}")
            raise

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def delete_long_ttp_generation(self, generation_id: str) -> bool:
        """删除指定的Long TTP生成记录"""
        try:
            async with get_db() as db:
                await db.execute(
                    LongTTPGeneration.__table__.delete().where(LongTTPGeneration.id == generation_id)
                )
                await db.commit()
            logger.info(f"Long TTP生成记录删除成功: {generation_id}")
            return True
        except (SQLAlchemyError, IntegrityError) as e:
            logger.error(f"Long TTP生成记录删除失败: {e}")
            return False

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
_mixed_repo = None


async def get_mixed_repository() -> MixedRepository:
    """获取全局混合仓库实例"""
    global _mixed_repo
    if _mixed_repo is None:
        es_repo = ShortTTPESRepository()
        _mixed_repo = MixedRepository(es_repo)
    return _mixed_repo


class EventESRepository:
    """事件查询的ElasticSearch数据仓库"""

    # 事件类型映射 - 复用与KafkaConsumer相同的逻辑
    EVENT_TYPE_MAPPINGS = {
        "falco": {
            "alert": EventType.FALCO_ALERT,
            "raw": EventType.FALCO_RAW
        },
        "openrasp": {
            "alert": EventType.OPENRASP_ALERT,
            "raw": EventType.OPENRASP_RAW,
            "raw_sql": EventType.OPENRASP_RAW_SQL
        },
        "suricata": {
            "alert": EventType.SURICATA_ALERT
        }
    }

    # ES索引别名映射
    INDEX_ALIASES = {
        "falco": "falco-alerts",
        "openrasp": "openrasp-alerts",
        "suricata": "suricata-alerts"
    }

    def __init__(self):
        self.es_client = get_es_client()

    def _detect_falco_type(self, raw_data: Dict) -> Optional[str]:
        """检测 Falco 事件类型 - 通过是否有 behavior-collection 标签区分 alert 和 raw。"""
        if "tags" in raw_data and isinstance(raw_data.get("tags"), list):
            tags = raw_data.get("tags", [])
            if "behavior-collection" in tags:
                return EventType.FALCO_RAW.value
            return EventType.FALCO_ALERT.value
        return None

    def _detect_openrasp_type(self, raw_data: Dict) -> Optional[str]:
        """检测 OpenRASP 事件类型 - 通过 event_type 和 attack_type 字段区分。"""
        orig_event_type = raw_data.get("event_type")
        if orig_event_type == "record_log":
            if raw_data.get("attack_type") == "sql":
                return EventType.OPENRASP_RAW_SQL.value
            return EventType.OPENRASP_RAW.value
        elif orig_event_type == "attack":
            return EventType.OPENRASP_ALERT.value
        return None

    def _detect_event_type(self, raw_data: Dict) -> Optional[str]:
        """检测事件类型 - 复用KafkaConsumer相同的逻辑"""
        try:
            # 直接通过原始JSON中的type字段判断事件类型
            event_type = raw_data.get("type")

            if event_type == "falco":
                result = self._detect_falco_type(raw_data)
                if result is not None:
                    return result
            elif event_type == "openrasp":
                result = self._detect_openrasp_type(raw_data)
                if result is not None:
                    return result
            elif event_type == "suricata":
                # Suricata事件检测
                if raw_data.get("event_type") == "alert":
                    return EventType.SURICATA_ALERT.value

            # 三类事件之外的数据直接忽略
            return None

        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error(f"检测事件类型失败: {e}")
            return None

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def _convert_es_to_security_event(self, es_hit: Dict) -> Optional[Dict[str, Any]]:
        """将ES命中结果转换为SecurityEvent格式"""
        try:
            source_data = es_hit.get("_source", {})
            event_id = source_data.get("event_id")

            if not event_id:
                return None

            # 检测事件类型
            event_type = self._detect_event_type(source_data)
            if not event_type:
                logger.warning(f"无法检测到事件类型: {es_hit}")
                return None

            # 根据事件源推导source和category
            if event_type.startswith("falco"):
                source = "falco"
                category = "raw" if "_raw" in event_type else "alert"
            elif event_type.startswith("openrasp"):
                source = "openrasp"
                category = "raw" if "_raw" in event_type else "alert"
            elif event_type.startswith("suricata"):
                source = "suricata"
                category = "alert"  # Suricata只有alert类型
            else:
                source = "unknown"
                category = "unknown"

            # 构建SecurityEvent格式
            return {
                "event_id": event_id,
                "event_type": event_type,
                "raw_event": source_data,  # 原始数据直接作为raw_event
                "received_time": self._extract_received_time(source_data),  # 提取接收时间
                "source": source,
                "category": category
            }

        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error(f"转换ES事件数据失败: {e}")
            return None

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def _extract_received_time(self, source_data: Dict) -> str:
        """从原始数据中提取接收时间"""
        try:
            # 尝试从不同的事件源中提取时间戳
            if source_data.get("type") == "falco":
                return source_data.get("time", datetime.now().isoformat())
            elif source_data.get("type") == "openrasp":
                return source_data.get("event_time", datetime.now().isoformat())
            elif source_data.get("type") == "suricata":
                return source_data.get("timestamp", datetime.now().isoformat())
            else:
                return datetime.now().isoformat()
        except (ValueError, TypeError, KeyError, AttributeError):
            return datetime.now().isoformat()

    def _search_indices(self, indices: List[str], query: Dict[str, Any], offset: int, limit: int) -> tuple[List[Dict[str, Any]], int]:
        """在多个索引上执行搜索并聚合结果。"""
        results: List[Dict[str, Any]] = []
        total_hits = 0

        for index in indices:
            try:
                response = self.es_client.client.search(
                    index=index,
                    body={
                        "from": offset,
                        "size": limit,
                        "query": query,
                        "sort": [{"@timestamp": {"order": "desc"}}]
                    }
                )

                for hit in response["hits"]["hits"]:
                    converted_event = self._convert_es_to_security_event(hit)
                    if converted_event:
                        results.append(converted_event)

                total_hits += response["hits"]["total"]["value"]

            except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
                logger.warning(f"查询索引 {index} 失败: {e}")
                continue

            except Exception as e:
                logger.exception(f"未预期错误: {e}")
                raise

        return results, total_hits

    async def search_events(self,
                           hours: int = 24,
                           event_ids: Optional[List[str]] = None,
                           event_types: Optional[List[str]] = None,
                           sources: Optional[List[str]] = None,
                           offset: int = 0,
                           limit: int = 100) -> Dict[str, Any]:
        """搜索事件 - 主要查询接口"""
        try:
            from datetime import timedelta

            # 计算时间范围
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours)

            # 根据sources确定要查询的索引
            indices = []
            if sources:
                # 只查询指定的源
                for source in sources:
                    if source in self.INDEX_ALIASES:
                        indices.append(self.INDEX_ALIASES[source])
            else:
                # 查询所有索引
                indices = list(self.INDEX_ALIASES.values())

            if not indices:
                return {"items": [], "total": 0, "offset": offset, "limit": limit}

            # 构建查询体
            must_conditions = []

            # 时间范围过滤
            must_conditions.append({
                "range": {
                    "@timestamp": {
                        "gte": start_time.isoformat(),
                        "lte": end_time.isoformat()
                    }
                }
            })

            # 事件ID过滤 - 使用.keyword子字段进行精确匹配
            if event_ids:
                must_conditions.append({
                    "terms": {
                        "event_id.keyword": event_ids
                    }
                })

            query = {
                "bool": {
                    "must": must_conditions
                }
            } if must_conditions else {"match_all": {}}

            # 执行搜索
            results, total_hits = self._search_indices(indices, query, offset, limit)
            if event_types:
                filtered_results = []
                for event in results:
                    if event.get("event_type") in event_types:
                        filtered_results.append(event)
                results = filtered_results

            # 应用分页
            start = offset
            end = offset + limit
            paginated_results = results[start:end]

            return {
                "items": paginated_results,
                "total": total_hits,
                "offset": offset,
                "limit": limit
            }

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"搜索事件失败: {e}")
            return {"items": [], "total": 0, "offset": offset, "limit": limit}

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    async def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """通过ID获取单个事件"""
        try:
            # 在所有事件索引中搜索
            indices = list(self.INDEX_ALIASES.values())

            # 构建精确查询 - 使用.keyword子字段进行精确匹配
            query = {
                "term": {
                    "event_id.keyword": event_id
                }
            }

            for index in indices:
                try:
                    response = self.es_client.client.search(
                        index=index,
                        body={
                            "size": 1,
                            "query": query
                        }
                    )

                    if response["hits"]["hits"]:
                        hit = response["hits"]["hits"][0]
                        result = self._convert_es_to_security_event(hit)
                        if result:
                            return result

                except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
                    logger.warning(f"查询索引 {index} 中的事件 {event_id} 失败: {e}")
                    continue

                except Exception as e:
                    logger.exception(f"未预期错误: {e}")
                    raise
            return None

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"获取事件 {event_id} 失败: {e}")
            return None

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
_event_es_repo = None


async def get_event_es_repository() -> EventESRepository:
    """获取全局事件ES仓库实例"""
    global _event_es_repo
    if _event_es_repo is None:
        _event_es_repo = EventESRepository()
    return _event_es_repo
