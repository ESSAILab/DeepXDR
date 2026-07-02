from __future__ import annotations

import anyio

from ai_agent.agent_guard.nono_wrapper import LocalDiffEvidenceWriter, run_nono_guarded_session


class FakeRunner:
    def __init__(self):
        self.commands = []

    async def run(self, command):
        self.commands.append(command)
        if command[:3] == ["nono", "rollback", "show"] and "--json" in command:
            return {"exit_code": 0, "stdout": '{"session_id":"nono-1"}', "stderr": ""}
        if command[:3] == ["nono", "rollback", "show"] and "--diff" in command:
            return {"exit_code": 0, "stdout": "diff --git a/README.md b/README.md\n+hello\n", "stderr": ""}
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, topic, event):
        self.events.append((topic, event))


def test_run_nono_guarded_session_builds_diff_ref_and_publishes_event(tmp_path):
    async def run_test():
        runner = FakeRunner()
        publisher = FakePublisher()
        writer = LocalDiffEvidenceWriter(tmp_path)

        event = await run_nono_guarded_session(
            original_request="修改 README",
            agent_command=["codex", "run"],
            workspace="/repo/app",
            rollback_dest="/rollback/run-1",
            run_id="run-1",
            runner=runner,
            diff_writer=writer,
            publisher=publisher,
        )

        assert runner.commands[0] == [
            "nono",
            "run",
            "--rollback",
            "--no-rollback-prompt",
            "--rollback-dest",
            "/rollback/run-1",
            "--allow",
            "/repo/app",
            "--",
            "codex",
            "run",
        ]
        assert event["type"] == "agent_session"
        assert event["event_type"] == "finished"
        assert event["diff_ref"]["storage"] == "local"
        assert event["diff_ref"]["sha256"]
        assert publisher.events[0][0] == "events"

    anyio.run(run_test)
