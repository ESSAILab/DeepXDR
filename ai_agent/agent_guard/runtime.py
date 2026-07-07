from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from shared.database.connection import get_db

from .command_runner import SubprocessCommandRunner
from .config import AgentGuardConfig
from .consumer import AgentSessionEventHandler
from .llm import OpenAICompletionLLM
from .publisher import JsonKafkaPublisher, RollbackRequestPublisher
from .sql_repository import SqlAlchemyAgentSessionRepository
from .worker import execute_rollback_request

logger = logging.getLogger(__name__)


JsonHandler = Callable[[dict], Awaitable[None]]


@dataclass
class JsonKafkaConsumerTask:
    bootstrap_servers: str
    topic: str
    group_id: str
    handler: JsonHandler
    consumer: AIOKafkaConsumer | None = None
    task: asyncio.Task | None = None
    running: bool = False

    async def start(self) -> None:
        self.consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await self.consumer.start()
        self.running = True
        self.task = asyncio.create_task(self._run())
        logger.info("Agent guard Kafka consumer started: topic=%s group_id=%s", self.topic, self.group_id)

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.consumer:
            await self.consumer.stop()

    async def _run(self) -> None:
        while self.running:
            try:
                async for message in self.consumer:
                    payload = self._decode(message.value)
                    await self.handler(payload)
                    await self.consumer.commit()
                    if not self.running:
                        break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Agent guard Kafka consumer failed: topic=%s", self.topic)
                await asyncio.sleep(1)

    @staticmethod
    def _decode(value) -> dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise TypeError("agent guard Kafka message must be a JSON object")
        return decoded


@dataclass
class AgentGuardRuntime:
    bootstrap_servers: str
    config: AgentGuardConfig
    llm: OpenAICompletionLLM
    session_topic: str = "agent.session.finished"
    rollback_requested_topic: str = "agent.rollback.requested"
    rollback_completed_topic: str = "agent.rollback.completed"
    session_group_id: str = "agent-guard-session-group"
    rollback_group_id: str = "agent-guard-rollback-group"
    producer: AIOKafkaProducer | None = None
    consumers: list[JsonKafkaConsumerTask] = field(default_factory=list)

    async def start(self) -> None:
        if not self.config.enabled:
            logger.info("Agent guard disabled by config")
            return

        self.producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap_servers)
        await self.producer.start()
        completed_publisher = JsonKafkaPublisher(self.producer)

        self.consumers = [
            JsonKafkaConsumerTask(
                bootstrap_servers=self.bootstrap_servers,
                topic=self.session_topic,
                group_id=self.session_group_id,
                handler=self._handle_agent_session_finished,
            ),
            JsonKafkaConsumerTask(
                bootstrap_servers=self.bootstrap_servers,
                topic=self.rollback_requested_topic,
                group_id=self.rollback_group_id,
                handler=lambda event: self._handle_rollback_requested(event, completed_publisher),
            ),
        ]
        for consumer in self.consumers:
            await consumer.start()

    async def stop(self) -> None:
        for consumer in self.consumers:
            await consumer.stop()
        if self.producer:
            await self.producer.stop()

    def rollback_publisher(self) -> RollbackRequestPublisher:
        if self.producer is None:
            raise RuntimeError("Agent guard runtime has not started")
        return RollbackRequestPublisher(JsonKafkaPublisher(self.producer), self.rollback_requested_topic)

    async def _handle_agent_session_finished(self, event: dict) -> None:
        async with get_db() as db:
            repository = SqlAlchemyAgentSessionRepository(db)
            handler = AgentSessionEventHandler(
                repository=repository,
                config=self.config,
                llm=self.llm,
            )
            await handler.handle(event)

    async def _handle_rollback_requested(self, event: dict, completed_publisher: JsonKafkaPublisher) -> None:
        completed_event = await execute_rollback_request(
            event,
            runner=SubprocessCommandRunner(),
            publisher=completed_publisher,
            completed_topic=self.rollback_completed_topic,
        )
        async with get_db() as db:
            repository = SqlAlchemyAgentSessionRepository(db)
            await repository.store_rollback(
                {
                    **completed_event,
                    "id": completed_event.get("id") or event.get("id"),
                    "requested_by": event.get("requested_by", "worker"),
                }
            )
            await repository.update_session(
                event["run_id"],
                {
                    "rollback_status": completed_event["status"],
                    "decision": "rollback_completed" if completed_event["status"] == "completed" else "rollback_failed",
                },
            )
