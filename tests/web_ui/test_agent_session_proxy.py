from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

WEB_UI_SRC = Path(__file__).resolve().parents[2] / "web_ui" / "src"
if str(WEB_UI_SRC) not in sys.path:
    sys.path.insert(0, str(WEB_UI_SRC))

import web.dashboard as dashboard


class ResponseStub:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_web_ui_proxies_agent_session_list_and_actions(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(("GET", url, None))
        return ResponseStub({"items": [{"run_id": "run-1"}], "total": 1})

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(("POST", url, json))
        return ResponseStub({"status": "ok"})

    monkeypatch.setattr(dashboard.requests, "get", fake_get)
    monkeypatch.setattr(dashboard.requests, "post", fake_post)

    client = TestClient(dashboard.app)

    assert client.get("/api/agent-sessions").json()["total"] == 1
    assert client.get("/api/agent-sessions/run-1").json()["items"][0]["run_id"] == "run-1"
    assert client.post("/api/agent-sessions/run-1/accept").json()["status"] == "ok"
    assert client.post("/api/agent-sessions/run-1/rollback", json={"requested_by": "user-1"}).json()["status"] == "ok"

    assert calls[0][1].endswith("/agent-sessions?page=1&size=20")
    assert calls[1][1].endswith("/agent-sessions/run-1")
    assert calls[2][1].endswith("/agent-sessions/run-1/accept")
    assert calls[3][1].endswith("/agent-sessions/run-1/rollback")
