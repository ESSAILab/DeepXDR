from __future__ import annotations

import json

import anyio

from ai_agent.agent_guard.publisher import JsonKafkaPublisher, RollbackRequestPublisher


class ProducerStub:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, topic, value):
        self.sent.append((topic, value))


def test_json_kafka_publisher_serializes_utf8_payload():
    async def run_test():
        producer = ProducerStub()
        publisher = JsonKafkaPublisher(producer)

        await publisher.publish("agent.session.finished", {"summary": "增量裁决"})

        topic, payload = producer.sent[0]
        assert topic == "agent.session.finished"
        assert json.loads(payload.decode("utf-8")) == {"summary": "增量裁决"}

    anyio.run(run_test)


def test_rollback_request_publisher_uses_default_topic():
    async def run_test():
        producer = ProducerStub()
        publisher = RollbackRequestPublisher(JsonKafkaPublisher(producer))

        await publisher.publish({"event_type": "agent.rollback.requested"})

        assert producer.sent[0][0] == "agent.rollback.requested"

    anyio.run(run_test)
