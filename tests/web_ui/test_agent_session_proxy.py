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

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        if method == "GET":
            return ResponseStub({"items": [{"run_id": "run-1"}], "total": 1})
        return ResponseStub({"status": "ok"})

    monkeypatch.setattr(dashboard, "request_backend", fake_request)

    client = TestClient(dashboard.app)

    assert client.get("/api/agent-sessions").json()["total"] == 1
    assert client.get("/api/agent-sessions/run-1").json()["items"][0]["run_id"] == "run-1"
    assert client.post("/api/agent-sessions/run-1/accept").json()["status"] == "ok"
    assert client.post("/api/agent-sessions/run-1/rollback", json={"requested_by": "user-1"}).json()["status"] == "ok"

    assert calls[0][1].endswith("/agent-sessions?page=1&size=20")
    assert calls[1][1].endswith("/agent-sessions/run-1")
    assert calls[2][1].endswith("/agent-sessions/run-1/accept")
    assert calls[3][1].endswith("/agent-sessions/run-1/rollback")


def test_backend_request_ignores_environment_proxy(monkeypatch):
    captured = {}

    class SessionStub:
        def __init__(self):
            self.trust_env = True

        def request(self, method, url, **kwargs):
            captured["trust_env"] = self.trust_env
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            return ResponseStub({"ok": True})

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(dashboard.requests, "Session", SessionStub)

    response = dashboard.request_backend("GET", "http://127.0.0.1:8000/agent-sessions", timeout=3)

    assert response.json() == {"ok": True}
    assert captured["trust_env"] is False
    assert captured["closed"] is True
