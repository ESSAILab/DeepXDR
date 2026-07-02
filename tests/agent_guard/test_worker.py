from __future__ import annotations

import anyio

from ai_agent.agent_guard.worker import execute_rollback_request


class FakeRunner:
    def __init__(self, fail_on=None):
        self.commands = []
        self.fail_on = fail_on

    async def run(self, command):
        self.commands.append(command)
        if self.fail_on and self.fail_on in command:
            return {"exit_code": 1, "stdout": "", "stderr": "failed"}
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, topic, event):
        self.events.append((topic, event))


def test_worker_verifies_dry_runs_restores_and_publishes_completed():
    async def run_test():
        runner = FakeRunner()
        publisher = FakePublisher()

        result = await execute_rollback_request(
            {
                "run_id": "run-1",
                "nono_session_id": "nono-1",
                "snapshot": 0,
                "requested_by": "user-1",
            },
            runner=runner,
            publisher=publisher,
        )

        assert result["status"] == "completed"
        assert runner.commands == [
            ["nono", "rollback", "verify", "nono-1"],
            ["nono", "rollback", "restore", "nono-1", "--snapshot", "0", "--dry-run"],
            ["nono", "rollback", "restore", "nono-1", "--snapshot", "0"],
        ]
        assert publisher.events[0][0] == "agent.rollback.completed"
        assert publisher.events[0][1]["status"] == "completed"

    anyio.run(run_test)


def test_worker_stops_and_publishes_failed_when_dry_run_fails():
    async def run_test():
        runner = FakeRunner(fail_on="--dry-run")
        publisher = FakePublisher()

        result = await execute_rollback_request(
            {
                "run_id": "run-1",
                "nono_session_id": "nono-1",
                "snapshot": 0,
                "requested_by": "user-1",
            },
            runner=runner,
            publisher=publisher,
        )

        assert result["status"] == "failed"
        assert len(runner.commands) == 2
        assert publisher.events[0][1]["status"] == "failed"

    anyio.run(run_test)
