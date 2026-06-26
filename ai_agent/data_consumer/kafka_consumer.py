import asyncio
import json
import logging
import os
from shared.utils.timezone import ChinaTime, to_naive
from typing import Any, Dict, Optional, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import TopicPartition
from pydantic import ValidationError

from shared.models.events import (
    SecurityEvent, FalcoAlertEvent, FalcoRawEvent,
    OpenRASPAlertEvent, OpenRASPRawEvent, OpenRASPRawSQLEvent, SuricataAlertEvent, EventType, EventSource, EventCategory
)

logger = logging.getLogger(__name__)


def _read_positive_int_env(name: str, default: int) -> int:
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
    return value


def _read_positive_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        logger.warning("%s=%r 不是有效数字，使用默认值 %s", name, raw_value, default)
        return default
    if value <= 0:
        logger.warning("%s=%s 必须为正数，使用默认值 %s", name, value, default)
        return default
    return value


class KafkaEventConsumer:
    """Kafka事件消费者"""
    
    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        event_callback: Callable[[SecurityEvent], None],
        max_poll_records: int = 500,
        session_timeout_ms: int = 30000,
        heartbeat_interval_ms: int = 10000,
        max_processing_retries: Optional[int] = None,
        processing_retry_backoff: Optional[float] = None,
        dlq_topic: Optional[str] = None,
        debug_mode: bool = False
    ):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.group_id = group_id
        self.event_callback = event_callback
        self.max_poll_records = max_poll_records
        self.session_timeout_ms = session_timeout_ms
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.max_processing_retries = (
            max_processing_retries
            if max_processing_retries is not None
            else _read_positive_int_env("KAFKA_PROCESSING_MAX_RETRIES", 3)
        )
        self.processing_retry_backoff = (
            processing_retry_backoff
            if processing_retry_backoff is not None
            else _read_positive_float_env("KAFKA_PROCESSING_RETRY_BACKOFF", 1.0)
        )
        self.dlq_topic = dlq_topic or os.getenv("KAFKA_DLQ_TOPIC", f"{topic}.dlq")
        self.debug_mode = logging.getLogger().isEnabledFor(logging.DEBUG)
        
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.producer: Optional[AIOKafkaProducer] = None
        self.running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self):
        """启动消费者"""
        try:
            self.consumer = AIOKafkaConsumer(
                self.topic,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                enable_auto_commit=False,
                max_poll_records=self.max_poll_records,
                session_timeout_ms=self.session_timeout_ms,
                heartbeat_interval_ms=self.heartbeat_interval_ms,
                max_poll_interval_ms=300000,  # 5分钟
                request_timeout_ms=305000,
                retry_backoff_ms=100
            )
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
            )
            
            await self.consumer.start()
            await self.producer.start()
            logger.info(
                "Kafka消费者已启动: topic=%s, group_id=%s, servers=%s, dlq_topic=%s, max_retries=%s",
                self.topic,
                self.group_id,
                self.bootstrap_servers,
                self.dlq_topic,
                self.max_processing_retries,
            )
            
            self.running = True
            self._task = asyncio.create_task(self._consume_messages())
            
        except Exception as e:
            logger.error(f"启动Kafka消费者失败: {e}")
            if self.producer:
                try:
                    await self.producer.stop()
                except Exception:
                    logger.exception("停止 Kafka DLQ 生产者失败")
            if self.consumer:
                try:
                    await self.consumer.stop()
                except Exception:
                    logger.exception("停止 Kafka 消费者失败")
            raise
    
    async def stop(self):
        """停止消费者"""
        self.running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self.producer:
            await self.producer.stop()
            logger.info("Kafka DLQ生产者已停止")

        if self.consumer:
            await self.consumer.stop()
            logger.info("Kafka消费者已停止")
    
    async def _process_single_record(self, record) -> bool:
        """处理单条 Kafka 记录"""
        raw_data = await self._decode_record_value(record)
        if raw_data is None:
            return True

        event = await self._parse_event(raw_data)
        if not event:
            await self._send_to_dlq(record, "parse_failed_or_unsupported")
            return True

        for attempt in range(1, self.max_processing_retries + 1):
            try:
                await self.event_callback(event)
                return True
            except Exception as e:
                if attempt >= self.max_processing_retries:
                    await self._send_to_dlq(record, "processing_failed", e)
                    return True
                logger.warning(
                    "处理 Kafka 消息失败，将重试: topic=%s partition=%s offset=%s attempt=%s/%s error=%s",
                    record.topic,
                    record.partition,
                    record.offset,
                    attempt,
                    self.max_processing_retries,
                    e,
                )
                await asyncio.sleep(self.processing_retry_backoff * attempt)

        return False

    async def _decode_record_value(self, record) -> Optional[Dict]:
        """解码 Kafka 消息体。解码失败的消息写入 DLQ 后允许提交 offset。"""
        value = record.value
        if isinstance(value, dict):
            return value

        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            if isinstance(value, str):
                decoded = json.loads(value)
            else:
                raise TypeError(f"unsupported Kafka value type: {type(value).__name__}")
            if not isinstance(decoded, dict):
                raise TypeError(f"Kafka JSON value must be an object, got {type(decoded).__name__}")
            return decoded
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as e:
            await self._send_to_dlq(record, "decode_failed", e)
            return None

    async def _commit_record(self, record) -> None:
        """提交单条记录之后的 offset。"""
        partition = TopicPartition(record.topic, record.partition)
        await self.consumer.commit({partition: record.offset + 1})

    def _seek_to_record(self, record) -> None:
        """回退到当前记录，避免未提交失败消息被同一 consumer 会话跳过。"""
        partition = TopicPartition(record.topic, record.partition)
        self.consumer.seek(partition, record.offset)

    async def _send_to_dlq(
        self,
        record,
        reason: str,
        error: Optional[Exception] = None,
    ) -> None:
        """把无法处理的消息发送到死信队列。DLQ 发送失败时抛出异常，避免提交 offset。"""
        if not self.producer:
            raise RuntimeError("Kafka DLQ生产者未初始化")

        payload: Dict[str, Any] = {
            "reason": reason,
            "error": str(error) if error else None,
            "source_topic": record.topic,
            "source_partition": record.partition,
            "source_offset": record.offset,
            "source_timestamp": record.timestamp,
            "value": self._format_dlq_value(record.value),
        }
        await self.producer.send_and_wait(self.dlq_topic, payload)
        logger.error(
            "Kafka 消息已写入 DLQ: topic=%s partition=%s offset=%s dlq_topic=%s reason=%s",
            record.topic,
            record.partition,
            record.offset,
            self.dlq_topic,
            reason,
        )

    def _format_dlq_value(self, value):
        """将原始消息转换为可 JSON 序列化的 DLQ 字段。"""
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return repr(value)
        return value

    async def _consume_messages(self):
        """消费消息"""
        while self.running:
            try:
                # 批量获取消息
                messages = await self.consumer.getmany(timeout_ms=1000)

                for _, records in messages.items():
                    for record in records:
                        try:
                            processed = await self._process_single_record(record)
                            if processed:
                                await self._commit_record(record)
                        except Exception as e:
                            self._seek_to_record(record)
                            logger.error(
                                "Kafka 消息处理未完成，已回退 offset 等待重试: topic=%s partition=%s offset=%s error=%s",
                                record.topic,
                                record.partition,
                                record.offset,
                                e,
                            )
                            await asyncio.sleep(self.processing_retry_backoff)
                            break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"消费消息异常: {e}")
                await asyncio.sleep(1)
    
    async def _parse_event(self, raw_data: Dict) -> Optional[SecurityEvent]:
        """解析原始事件数据"""
        try:
            if self.debug_mode:
                logger.debug(f"[DEBUG] 接收到原始事件数据: {raw_data}")
            
            # 检测事件类型
            event_type = self._detect_event_type(raw_data)
            
            if event_type == EventType.FALCO_ALERT:
                event = await self._parse_falco_alert(raw_data)
            elif event_type == EventType.FALCO_RAW:
                event = await self._parse_falco_raw(raw_data)
            elif event_type == EventType.OPENRASP_ALERT:
                event = await self._parse_openrasp_alert(raw_data)
            elif event_type == EventType.OPENRASP_RAW:
                event = await self._parse_openrasp_raw(raw_data)
            elif event_type == EventType.OPENRASP_RAW_SQL:
                event = await self._parse_openrasp_raw_sql(raw_data)
            elif event_type == EventType.SURICATA_ALERT:          # ✅ 新增
                event = await self._parse_suricata_alert(raw_data)
            else:
                logger.warning(f"未知事件类型: {raw_data}")
                return None
            
            if event and self.debug_mode:
                logger.debug(f"[DEBUG] 事件解析成功: {event.event_type}, ID: {event.event_id}")
            
            return event
                
        except ValidationError as e:
            logger.error(f"事件验证失败: {e}")
            return None
        except Exception as e:
            logger.error(f"解析事件失败: {e}")
            return None
    
    def _detect_falco_type(self, raw_data: Dict) -> Optional[EventType]:
        """检测 Falco 事件类型"""
        if "tags" not in raw_data or not isinstance(raw_data.get("tags"), list):
            return None
        tags = raw_data.get("tags", [])
        if "behavior-collection" in tags:
            return EventType.FALCO_RAW
        return EventType.FALCO_ALERT

    def _detect_openrasp_type(self, raw_data: Dict) -> Optional[EventType]:
        """检测 OpenRASP 事件类型"""
        orig_event_type = raw_data.get("event_type")
        if orig_event_type == "record_log":
            if raw_data.get("attack_type") == "sql":
                return EventType.OPENRASP_RAW_SQL
            return EventType.OPENRASP_RAW
        elif orig_event_type == "attack":
            return EventType.OPENRASP_ALERT
        return None

    def _detect_event_type(self, raw_data: Dict) -> Optional[EventType]:
        """检测事件类型 - 基于type字段"""
        try:
            # 直接通过Kafka原始JSON中的type字段判断事件类型
            event_type = raw_data.get("type")

            if event_type == "falco":
                return self._detect_falco_type(raw_data)
            elif event_type == "openrasp":
                return self._detect_openrasp_type(raw_data)
            elif event_type == "suricata":
                # Suricata事件检测
                if raw_data.get("event_type") == "alert":
                    return EventType.SURICATA_ALERT

            # 三类事件之外的数据直接忽略
            return None

        except Exception as e:
            logger.error(f"检测事件类型失败: {e}")
            return None
    
    async def _parse_falco_alert(self, raw_data: Dict) -> SecurityEvent:
        """解析Falco告警事件"""
        falco_event = FalcoAlertEvent.model_validate(raw_data)

        return SecurityEvent(
            event_id=raw_data.get("event_id", falco_event.uuid),  # 优先使用Kafka中的event_id
            event_type=EventType.FALCO_ALERT,
            raw_event=falco_event,
            received_time=to_naive(ChinaTime.now()),
            source=EventSource.FALCO,
            category=EventCategory.ALERT
        )
    
    async def _parse_falco_raw(self, raw_data: Dict) -> SecurityEvent:
        """解析Falco原始事件"""
        falco_event = FalcoRawEvent.model_validate(raw_data)

        return SecurityEvent(
            event_id=raw_data.get("event_id", falco_event.uuid),  # 优先使用Kafka中的event_id
            event_type=EventType.FALCO_RAW,
            raw_event=falco_event,
            received_time=to_naive(ChinaTime.now()),
            source=EventSource.FALCO,
            category=EventCategory.RAW
        )
    
    async def _parse_openrasp_alert(self, raw_data: Dict) -> SecurityEvent:
        """解析OpenRASP告警事件"""
        openrasp_event = OpenRASPAlertEvent.model_validate(raw_data)

        return SecurityEvent(
            event_id=raw_data.get("event_id"),  # 直接使用Kafka中的event_id
            event_type=EventType.OPENRASP_ALERT,
            raw_event=openrasp_event,
            received_time=to_naive(ChinaTime.now()),
            source=EventSource.OPENRASP,
            category=EventCategory.ALERT
        )
    
    async def _parse_openrasp_raw(self, raw_data: Dict) -> SecurityEvent:
        """解析OpenRASP原始事件"""
        openrasp_event = OpenRASPRawEvent.model_validate(raw_data)

        return SecurityEvent(
            event_id=raw_data.get("event_id"),  # 直接使用Kafka中的event_id
            event_type=EventType.OPENRASP_RAW,
            raw_event=openrasp_event,
            received_time=to_naive(ChinaTime.now()),
            source=EventSource.OPENRASP,
            category=EventCategory.RAW
        )
    
    async def _parse_openrasp_raw_sql(self, raw_data: Dict) -> SecurityEvent:
        """解析OpenRASP SQL原始事件"""
        openrasp_event = OpenRASPRawSQLEvent.model_validate(raw_data)

        return SecurityEvent(
            event_id=raw_data.get("event_id"),  # 直接使用Kafka中的event_id
            event_type=EventType.OPENRASP_RAW_SQL,
            raw_event=openrasp_event,
            received_time=to_naive(ChinaTime.now()),
            source=EventSource.OPENRASP,
            category=EventCategory.RAW
        )
    
    async def _parse_suricata_alert(self, raw_data: Dict) -> SecurityEvent:
        """解析Suricata告警事件"""
        try:
            # 解析完整原始数据
            suricata_event = SuricataAlertEvent.model_validate(raw_data)

            # 创建统一安全事件，直接使用Kafka中的event_id
            security_event = SecurityEvent(
                event_id=raw_data.get("event_id"),  # 直接使用Kafka中的event_id
                event_type=EventType.SURICATA_ALERT,
                raw_event=suricata_event,
                received_time=to_naive(ChinaTime.now()),
                source=EventSource.SURICATA,
                category=EventCategory.ALERT
            )

            logger.debug(f"Suricata事件解析成功: flow_id={suricata_event.flow_id}, event_id={raw_data.get('event_id')}")

            return security_event

        except ValidationError as e:
            logger.error(f"Suricata告警事件数据验证失败: {e}")
            return None
        except Exception as e:
            logger.error(f"解析Suricata告警事件时出错: {e}")
            return None
    
    async def get_consumer_stats(self) -> Dict:
        """获取消费者统计信息"""
        if not self.consumer:
            return {}
        
        try:
            # 获取当前分区分配
            partitions = self.consumer.assignment()
            stats = {
                "running": self.running,
                "partitions": [str(p) for p in partitions],
                "position": {}
            }
            
            for partition in partitions:
                position = await self.consumer.position(partition)
                stats["position"][str(partition)] = position
            
            return stats
            
        except Exception as e:
            logger.error(f"获取消费者统计失败: {e}")
            return {"error": str(e)}
