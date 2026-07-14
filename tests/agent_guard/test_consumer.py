from __future__ import annotations

import asyncio
import hashlib
import threading

import anyio

import ai_agent.agent_guard.consumer as consumer_module
from ai_agent.agent_guard.config import AgentGuardConfig
from ai_agent.agent_guard.consumer import AgentSessionEventHandler
from ai_agent.agent_guard.repository import InMemoryAgentSessionRepository
from ai_agent.agent_guard.service_types import AgentSessionProcessResult


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


def test_agent_session_event_handler_does_not_block_event_loop(monkeypatch):
    async def run_test():
        started = threading.Event()
        release = threading.Event()
        analysis_thread_id = None

        def slow_process(*_args, **_kwargs):
            nonlocal analysis_thread_id
            analysis_thread_id = threading.get_ident()
            started.set()
            release.wait(timeout=2)
            return AgentSessionProcessResult(status="adjudicated")

        monkeypatch.setattr(consumer_module, "process_finished_session_event", slow_process)
        handler = AgentSessionEventHandler(
            repository=InMemoryAgentSessionRepository(),
            config=AgentGuardConfig(),
            llm=FakeLLM(),
        )
        main_thread_id = threading.get_ident()
        task = asyncio.create_task(handler.handle({"run_id": "run-slow"}))

        await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=2)
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
        assert not task.done()
        assert analysis_thread_id != main_thread_id

        release.set()
        result = await task
        assert result.status == "adjudicated"

    anyio.run(run_test)
