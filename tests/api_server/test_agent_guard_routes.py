from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_agent.agent_guard.repository import InMemoryAgentSessionRepository
from api_server.routes import router, set_agent_guard_components


class FakeRollbackPublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _client(repo, publisher):
    os.environ["BACKEND_API_KEY"] = "test-key"
    set_agent_guard_components(repo, publisher)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


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
