from __future__ import annotations

import anyio

from ai_agent.agent_guard.repository import InMemoryAgentSessionRepository


def test_repository_stores_lists_and_updates_agent_session():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        await repo.upsert_session(
            {
                "run_id": "run-1",
                "original_request": "修改 README",
                "adjudication": {"verdict": "warn", "risk_level": "high"},
                "rollback_status": "not_requested",
            }
        )

        sessions = await repo.list_sessions()
        detail = await repo.get_session("run-1")
        await repo.update_session("run-1", {"rollback_status": "requested"})

        assert sessions["total"] == 1
        assert sessions["items"][0]["run_id"] == "run-1"
        assert detail["adjudication"]["verdict"] == "warn"
        assert (await repo.get_session("run-1"))["rollback_status"] == "requested"

    anyio.run(run_test)


def test_repository_returns_none_for_missing_session():
    async def run_test():
        repo = InMemoryAgentSessionRepository()

        assert await repo.get_session("missing") is None

    anyio.run(run_test)
