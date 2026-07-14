from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_agent.agent_guard.repository import InMemoryAgentSessionRepository
from api_server.routes import router, set_agent_guard_components


class FakeRollbackPublisher:
    def __init__(self):
        self.events = []
        self.fail_next = False

    async def publish(self, event):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("kafka unavailable")
        self.events.append(event)


def _client(repo, publisher, *, raise_server_exceptions=True):
    os.environ["BACKEND_API_KEY"] = "test-key"
    set_agent_guard_components(repo, publisher)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_agent_session_routes_list_detail_accept_and_rollback():
    repo = InMemoryAgentSessionRepository()
    publisher = FakeRollbackPublisher()
    client = _client(repo, publisher)

    import anyio

    anyio.run(
        repo.upsert_session,
        {
            "run_id": "run-1",
            "nono": {"session_id": "nono-1"},
            "original_request": "修改 README",
            "rollback_status": "not_requested",
        },
    )

    headers = {"X-API-Key": "test-key"}
    assert client.get("/agent-sessions", headers=headers).json()["total"] == 1
    assert client.get("/agent-sessions/run-1", headers=headers).json()["run_id"] == "run-1"

    accepted = client.post("/agent-sessions/run-1/accept", headers=headers).json()
    rollback = client.post("/agent-sessions/run-1/rollback", headers=headers, json={"requested_by": "user-1"}).json()

    assert accepted["status"] == "accepted"
    assert rollback["status"] == "rollback_requested"
    assert publisher.events[0]["event_type"] == "agent.rollback.requested"
    assert publisher.events[0]["snapshot"] == 0


def test_agent_session_rollback_reuses_existing_operation_for_duplicate_request():
    repo = InMemoryAgentSessionRepository()
    publisher = FakeRollbackPublisher()
    client = _client(repo, publisher)

    import anyio

    anyio.run(
        repo.upsert_session,
        {
            "run_id": "run-1",
            "nono": {"session_id": "nono-1", "state_home": "/var/lib/nono/run-1"},
            "original_request": "修改 README",
            "rollback_status": "not_requested",
        },
    )

    headers = {"X-API-Key": "test-key"}
    first = client.post("/agent-sessions/run-1/rollback", headers=headers, json={"requested_by": "user-1"}).json()
    second = client.post("/agent-sessions/run-1/rollback", headers=headers, json={"requested_by": "user-2"}).json()

    assert first["rollback_id"] == second["rollback_id"]
    assert first["rollback_status"] == "queued"
    assert second["rollback_status"] == "queued"
    assert [event["id"] for event in publisher.events] == [first["rollback_id"]]
    assert publisher.events[0]["nono_state_home"] == "/var/lib/nono/run-1"
    assert len(repo.rollbacks) == 1


def test_agent_session_rollback_retries_publish_after_initial_failure():
    repo = InMemoryAgentSessionRepository()
    publisher = FakeRollbackPublisher()
    client = _client(repo, publisher, raise_server_exceptions=False)

    import anyio

    anyio.run(
        repo.upsert_session,
        {
            "run_id": "run-1",
            "nono": {"session_id": "nono-1", "state_home": "/var/lib/nono/run-1"},
            "original_request": "修改 README",
            "rollback_status": "not_requested",
        },
    )

    headers = {"X-API-Key": "test-key"}
    publisher.fail_next = True

    failed = client.post("/agent-sessions/run-1/rollback", headers=headers, json={"requested_by": "user-1"})
    retry = client.post("/agent-sessions/run-1/rollback", headers=headers, json={"requested_by": "user-1"}).json()

    assert failed.status_code == 500
    assert retry["rollback_status"] == "queued"
    assert [event["id"] for event in publisher.events] == [retry["rollback_id"]]
    assert anyio.run(repo.get_rollback, retry["rollback_id"])["status"] == "queued"


def test_agent_session_route_deletes_session():
    repo = InMemoryAgentSessionRepository()
    publisher = FakeRollbackPublisher()
    client = _client(repo, publisher)

    import anyio

    anyio.run(
        repo.upsert_session,
        {
            "run_id": "run-1",
            "nono": {"session_id": "nono-1"},
            "original_request": "修改 README",
            "rollback_status": "not_requested",
        },
    )

    headers = {"X-API-Key": "test-key"}
    deleted = client.delete("/agent-sessions/run-1", headers=headers)

    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "run_id": "run-1"}
    assert client.get("/agent-sessions/run-1", headers=headers).status_code == 404
    assert client.delete("/agent-sessions/run-1", headers=headers).status_code == 404


def test_agent_session_route_rejects_delete_with_requested_rollback_ledger():
    repo = InMemoryAgentSessionRepository()
    publisher = FakeRollbackPublisher()
    client = _client(repo, publisher)

    import anyio

    anyio.run(
        repo.upsert_session,
        {
            "run_id": "run-1",
            "nono": {"session_id": "nono-1"},
            "original_request": "修改 README",
            "rollback_status": "not_requested",
        },
    )
    anyio.run(
        repo.store_rollback,
        {
            "id": "rollback-requested",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "requested",
        },
    )

    headers = {"X-API-Key": "test-key"}
    deleted = client.delete("/agent-sessions/run-1", headers=headers)

    assert deleted.status_code == 409
    assert deleted.json()["detail"] == "Rollback execution ledger is active"
    assert client.get("/agent-sessions/run-1", headers=headers).status_code == 200
    assert anyio.run(repo.get_rollback, "rollback-requested") is not None
