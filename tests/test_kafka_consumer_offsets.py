from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ai_agent.data_consumer.kafka_consumer import KafkaEventConsumer


class DummyConsumer:
    def __init__(self):
        self.commits = []
        self.seeks = []

    async def commit(self, offsets):
        self.commits.append(offsets)

    def seek(self, partition, offset):
        self.seeks.append((partition, offset))


class DummyProducer:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.messages = []

    async def send_and_wait(self, topic, payload):
        if self.fail:
            raise RuntimeError("dlq unavailable")
        self.messages.append((topic, payload))


def _record(value=None):
    return SimpleNamespace(
        topic="agent",
        partition=1,
        offset=42,
        timestamp=123456,
        value=value or {"event_id": "evt-1"},
    )


def _consumer(callback):
    consumer = KafkaEventConsumer(
        bootstrap_servers="localhost:9092",
        topic="agent",
        group_id="test-group",
        event_callback=callback,
        max_processing_retries=2,
        processing_retry_backoff=0.001,
        dlq_topic="agent.dlq",
    )
    consumer.consumer = DummyConsumer()
    consumer.producer = DummyProducer()
    return consumer


def test_process_success_commits_after_callback():
    calls = []

    async def callback(event):
        calls.append(event)

    async def run():
        consumer = _consumer(callback)

        async def parse_event(_value):
            return "event"

        consumer._parse_event = parse_event

        processed = await consumer._process_single_record(_record())
        if processed:
            await consumer._commit_record(_record())

        assert calls == ["event"]
        assert len(consumer.consumer.commits) == 1
        commit = consumer.consumer.commits[0]
        assert next(iter(commit.values())) == 43

    asyncio.run(run())


def test_process_failure_goes_to_dlq_then_commits():
    attempts = 0

    async def callback(_event):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("processing failed")

    async def run():
        consumer = _consumer(callback)

        async def parse_event(_value):
            return "event"

        consumer._parse_event = parse_event
        record = _record()

        processed = await consumer._process_single_record(record)
        if processed:
            await consumer._commit_record(record)

        assert attempts == 2
        assert len(consumer.producer.messages) == 1
        dlq_topic, payload = consumer.producer.messages[0]
        assert dlq_topic == "agent.dlq"
        assert payload["reason"] == "processing_failed"
        assert payload["source_offset"] == 42
        assert len(consumer.consumer.commits) == 1

    asyncio.run(run())


def test_dlq_failure_prevents_commit():
    async def callback(_event):
        raise RuntimeError("processing failed")

    async def run():
        consumer = _consumer(callback)
        consumer.producer = DummyProducer(fail=True)

        async def parse_event(_value):
            return "event"

        consumer._parse_event = parse_event

        with pytest.raises(RuntimeError, match="dlq unavailable"):
            await consumer._process_single_record(_record())

        assert consumer.consumer.commits == []

    asyncio.run(run())


def test_parse_failure_goes_to_dlq_then_commits():
    async def callback(_event):
        raise AssertionError("callback should not run")

    async def run():
        consumer = _consumer(callback)

        async def parse_event(_value):
            return None

        consumer._parse_event = parse_event
        record = _record({"invalid": True})

        processed = await consumer._process_single_record(record)
        if processed:
            await consumer._commit_record(record)

        assert len(consumer.producer.messages) == 1
        assert consumer.producer.messages[0][1]["reason"] == "parse_failed_or_unsupported"
        assert len(consumer.consumer.commits) == 1

    asyncio.run(run())


def test_decode_failure_goes_to_dlq_then_commits():
    async def callback(_event):
        raise AssertionError("callback should not run")

    async def run():
        consumer = _consumer(callback)
        record = _record(b"{not-json")

        processed = await consumer._process_single_record(record)
        if processed:
            await consumer._commit_record(record)

        assert len(consumer.producer.messages) == 1
        dlq_topic, payload = consumer.producer.messages[0]
        assert dlq_topic == "agent.dlq"
        assert payload["reason"] == "decode_failed"
        assert payload["value"] == "{not-json"
        assert len(consumer.consumer.commits) == 1

    asyncio.run(run())


def test_consume_loop_seeks_and_does_not_commit_when_dlq_fails():
    async def callback(_event):
        raise RuntimeError("processing failed")

    async def run():
        consumer = _consumer(callback)
        consumer.producer = DummyProducer(fail=True)
        consumer.running = True

        async def parse_event(_value):
            return "event"

        async def getmany(timeout_ms):
            consumer.running = False
            return {"partition": [_record()]}

        consumer._parse_event = parse_event
        consumer.consumer.getmany = getmany

        await consumer._consume_messages()

        assert consumer.consumer.commits == []
        assert len(consumer.consumer.seeks) == 1
        assert consumer.consumer.seeks[0][1] == 42

    asyncio.run(run())
