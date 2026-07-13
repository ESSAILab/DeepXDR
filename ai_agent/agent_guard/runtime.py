from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from shared.database.connection import get_db

from .adjudication_graph import AnalysisCancellationToken
from .command_runner import SubprocessCommandRunner
from .config import AgentGuardConfig
from .consumer import AgentSessionEventHandler
from .llm import OpenAICompletionLLM
from .publisher import JsonKafkaPublisher, RollbackRequestPublisher
from .sql_repository import SqlAlchemyAgentSessionRepository
from .worker import execute_rollback_request

logger = logging.getLogger(__name__)


JsonHandler = Callable[[dict, AnalysisCancellationToken], Awaitable[None]]


@dataclass
class JsonKafkaConsumerTask:
    bootstrap_servers: str
    topic: str
    group_id: str
    handler: JsonHandler
    max_poll_interval_ms: int = 3 * 60 * 60 * 1000
    max_handler_attempts: int = 1
    retry_backoff_seconds: int = 1
    handler_timeout_seconds: float | None = None
    drain_timeout_seconds: float = 15 * 60 + 30
    consumer: AIOKafkaConsumer | None = None
    task: asyncio.Task | None = None
    running: bool = False
    _message_active: bool = field(default=False, init=False, repr=False)
    _active_cancellation_token: AnalysisCancellationToken | None = field(
        default=None,
        init=False,
        repr=False,
    )

    async def start(self) -> None:
        self.consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_poll_interval_ms=self.max_poll_interval_ms,
        )
        await self.consumer.start()
        self.running = True
        self.task = asyncio.create_task(self._run())
        logger.info("Agent guard Kafka consumer started: topic=%s group_id=%s", self.topic, self.group_id)

    async def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            if self._message_active:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self.task),
                        timeout=self.drain_timeout_seconds,
                    )
                except TimeoutError:
                    if self._active_cancellation_token is not None:
                        self._active_cancellation_token.cancel()
                    logger.error(
                        "Agent guard Kafka consumer drain timed out; cancelling awaiter, "
                        "underlying worker thread may continue: topic=%s timeout_seconds=%s",
                        self.topic,
                        self.drain_timeout_seconds,
                    )
                    self.task.cancel()
                    try:
                        await self.task
                    except asyncio.CancelledError:
                        pass
            else:
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
                    if not self.running:
                        break
                    self._message_active = True
                    try:
                        if not await self._handle_message(message.value):
                            break
                        await self.consumer.commit()
                    finally:
                        self._message_active = False
                    if not self.running:
                        break
                if not self.running:
                    break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Agent guard Kafka consumer failed: topic=%s", self.topic)
                await asyncio.sleep(1)

    async def _handle_message(self, value) -> bool:
        try:
            payload = self._decode(value)
        except Exception:
            logger.critical(
                "Agent guard Kafka consumer stopped on invalid message: topic=%s",
                self.topic,
                exc_info=True,
            )
            self.running = False
            return False

        for attempt in range(1, self.max_handler_attempts + 1):
            if not self.running:
                logger.error(
                    "Agent guard Kafka consumer stopped before handler attempt: topic=%s",
                    self.topic,
                )
                return False
            cancellation_token = AnalysisCancellationToken()
            self._active_cancellation_token = cancellation_token
            try:
                if self.handler_timeout_seconds is None:
                    await self.handler(payload, cancellation_token)
                else:
                    async with asyncio.timeout(self.handler_timeout_seconds):
                        await self.handler(payload, cancellation_token)
                return True
            except asyncio.CancelledError:
                cancellation_token.cancel()
                raise
            except TimeoutError:
                cancellation_token.cancel()
                logger.critical(
                    "Agent guard Kafka session handler deadline exceeded and consumer stopped: "
                    "topic=%s timeout_seconds=%s",
                    self.topic,
                    self.handler_timeout_seconds,
                    exc_info=True,
                )
                self.running = False
                return False
            except Exception:
                if not self.running:
                    logger.error(
                        "Agent guard Kafka handler failed during shutdown; not retrying: topic=%s",
                        self.topic,
                        exc_info=True,
                    )
                    return False
                if attempt >= self.max_handler_attempts:
                    logger.critical(
                        "Agent guard Kafka consumer exhausted handler attempts and stopped: "
                        "topic=%s attempts=%s",
                        self.topic,
                        self.max_handler_attempts,
                        exc_info=True,
                    )
                    self.running = False
                    return False
                logger.error(
                    "Agent guard Kafka handler failed; retrying current message: "
                    "topic=%s attempt=%s max_attempts=%s",
                    self.topic,
                    attempt,
                    self.max_handler_attempts,
                    exc_info=True,
                )
                await asyncio.sleep(self.retry_backoff_seconds)
                if not self.running:
                    logger.error(
                        "Agent guard Kafka consumer stopped during handler retry backoff: topic=%s",
                        self.topic,
                    )
                    return False
            finally:
                if self._active_cancellation_token is cancellation_token:
                    self._active_cancellation_token = None

        raise AssertionError("handler attempt loop exited unexpectedly")

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
        self.llm.request_timeout_seconds = self.config.llm_request_timeout_seconds

        self.consumers = [
            JsonKafkaConsumerTask(
                bootstrap_servers=self.bootstrap_servers,
                topic=self.session_topic,
                group_id=self.session_group_id,
                handler=self._handle_agent_session_finished,
                max_poll_interval_ms=self.config.kafka_max_poll_interval_ms,
                max_handler_attempts=self.config.session_handler_max_attempts,
                retry_backoff_seconds=self.config.session_retry_backoff_seconds,
                handler_timeout_seconds=self.config.session_handler_timeout_seconds,
                drain_timeout_seconds=self.config.consumer_drain_timeout_seconds,
            ),
            JsonKafkaConsumerTask(
                bootstrap_servers=self.bootstrap_servers,
                topic=self.rollback_requested_topic,
                group_id=self.rollback_group_id,
                handler=lambda event, _cancellation_token: self._handle_rollback_requested(
                    event,
                    completed_publisher,
                ),
                max_poll_interval_ms=self.config.kafka_max_poll_interval_ms,
                max_handler_attempts=1,
                drain_timeout_seconds=self.config.consumer_drain_timeout_seconds,
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

    async def _handle_agent_session_finished(
        self,
        event: dict,
        cancellation_token: AnalysisCancellationToken,
    ) -> None:
        async with get_db() as db:
            repository = SqlAlchemyAgentSessionRepository(db)
            handler = AgentSessionEventHandler(
                repository=repository,
                config=self.config,
                llm=self.llm,
            )
            await handler.handle(event, cancellation_token=cancellation_token)

    async def _handle_rollback_requested(self, event: dict, completed_publisher: JsonKafkaPublisher) -> None:
        if not event.get("id"):
            raise ValueError("rollback request id is required for durable execution claim")
        async with get_db() as db:
            repository = SqlAlchemyAgentSessionRepository(db)
            claim = await repository.claim_rollback_execution(event)
            if claim in {"completed", "failed"}:
                await repository.update_session(
                    event["run_id"],
                    {
                        "rollback_status": claim,
                        "decision": "rollback_completed" if claim == "completed" else "rollback_failed",
                    },
                )
                logger.info(
                    "Skipping terminal rollback redelivery: request_id=%s status=%s",
                    event["id"],
                    claim,
                )
                return
            if claim == "executing":
                raise RuntimeError(
                    "rollback request is already executing; nono restore has no explicit "
                    "request-level idempotency guarantee, so redelivery is fail-closed"
                )
            if claim != "claimed":
                raise RuntimeError(
                    "rollback request could not claim durable execution ledger: "
                    f"request_id={event['id']} state={claim}"
                )

        completed_event = await execute_rollback_request(
            event,
            runner=SubprocessCommandRunner(),
            publisher=completed_publisher,
            completed_topic=self.rollback_completed_topic,
        )
        async with get_db() as db:
            repository = SqlAlchemyAgentSessionRepository(db)
            await repository.finish_rollback_execution(
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
