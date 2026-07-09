from __future__ import annotations

from baseline_adjudication.anomaly_detector import AnomalyDetector


class ProducerStub:
    def __init__(self):
        self.sent = []

    def send(self, topic, value):
        self.sent.append((topic, value))

    def flush(self):
        pass


class RedisMustNotBeUsed:
    def exists(self, _key):
        raise AssertionError("agent_session events must bypass Redis baseline lookup")


def test_agent_session_finished_is_published_to_dedicated_topic(monkeypatch):
    monkeypatch.setenv("KAFKA_AGENT_SESSION_TOPIC", "agent.session.finished")
    detector = AnomalyDetector()
    detector.producer = ProducerStub()
    detector.redis_client = RedisMustNotBeUsed()

    detector.process_event(
        {
            "type": "agent_session",
            "event_type": "finished",
            "run_id": "run-1",
            "original_request": "修改 README 标题",
            "workspace": "/repo/app",
            "diff_ref": {
                "storage": "local",
                "uri": "/evidence/run-1.diff",
                "sha256": "a" * 64,
                "size_bytes": 120,
            },
            "nono": {
                "session_id": "nono-1",
                "rollback_dest": "/rollback/run-1",
                "exit_code": 0,
                "verified": True,
            },
        }
    )

    assert len(detector.producer.sent) == 1
    topic, payload = detector.producer.sent[0]
    assert topic == "agent.session.finished"
    assert payload["type"] == "agent_session"
    assert payload["event_type"] == "finished"
    assert payload["source"] == "nono-wrapper"
    assert payload["category"] == "agent_runtime_change"
    assert payload["baseline_action"] == "pass_through"
    assert payload["run_id"] == "run-1"
    assert payload["diff_ref"]["sha256"] == "a" * 64


def test_agent_session_missing_required_fields_is_not_published(monkeypatch):
    monkeypatch.setenv("KAFKA_AGENT_SESSION_TOPIC", "agent.session.finished")
    detector = AnomalyDetector()
    detector.producer = ProducerStub()
    detector.redis_client = RedisMustNotBeUsed()

    detector.process_event({"type": "agent_session", "event_type": "finished"})

    assert detector.producer.sent == []
