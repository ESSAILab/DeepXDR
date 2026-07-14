from __future__ import annotations

import json
from typing import Protocol


class ProducerLike(Protocol):
    async def send_and_wait(self, topic: str, value: bytes, key: bytes | None = None) -> object:
        ...


class JsonKafkaPublisher:
    """Small adapter around aiokafka-style producers."""

    def __init__(self, producer: ProducerLike):
        self.producer = producer

    async def publish(self, topic: str, event: dict) -> None:
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        key_value = event.get("id") or event.get("run_id")
        key = str(key_value).encode("utf-8") if key_value else None
        await self.producer.send_and_wait(topic, payload, key=key)


class RollbackRequestPublisher:
    """Publishes rollback request events to the configured Kafka topic."""

    def __init__(self, publisher: JsonKafkaPublisher, topic: str = "agent.rollback.requested"):
        self.publisher = publisher
        self.topic = topic

    async def publish(self, event: dict) -> None:
        await self.publisher.publish(self.topic, event)
