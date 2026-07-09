from __future__ import annotations

import hashlib

import anyio

from ai_agent.agent_guard.config import AgentGuardConfig
from ai_agent.agent_guard.consumer import AgentSessionEventHandler
from ai_agent.agent_guard.repository import InMemoryAgentSessionRepository


class FakeLLM:
    def complete(self, _prompt):
        return '{"verdict":"allow","risk_level":"low","out_of_intent":false,"summary":"ok","findings":[],"recommended_action":"accept","rollback_recommended":false}'


def test_agent_session_event_handler_processes_and_stores_finished_event(tmp_path):
    async def run_test():
        diff = "diff --git a/README.md b/README.md\n+++ b/README.md\n@@\n+hello\n"
        path = tmp_path / "run.diff"
        path.write_text(diff, encoding="utf-8")
        repo = InMemoryAgentSessionRepository()
        handler = AgentSessionEventHandler(repository=repo, config=AgentGuardConfig(), llm=FakeLLM())

        result = await handler.handle(
            {
                "run_id": "run-1",
                "original_request": "修改 README",
                "diff_ref": {
                    "storage": "local",
                    "uri": str(path),
                    "sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
                },
                "nono": {"session_id": "nono-1"},
            }
        )

        stored = await repo.get_session("run-1")
        assert result.status == "adjudicated"
        assert stored["run_id"] == "run-1"
        assert stored["adjudication"]["verdict"] == "allow"

    anyio.run(run_test)
