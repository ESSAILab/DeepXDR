from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol


class CommandRunner(Protocol):
    async def run(
        self,
        command: list[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> dict:
        ...


class RollbackCompletedPublisher(Protocol):
    async def publish(self, topic: str, event: dict) -> None:
        ...


async def execute_rollback_request(
    request: dict,
    *,
    runner: CommandRunner,
    publisher: RollbackCompletedPublisher,
    completed_topic: str = "agent.rollback.completed",
) -> dict:
    run_id = request["run_id"]
    session_id = request["nono_session_id"]
    snapshot = str(request.get("snapshot", 0))
    command_env = {}
    if request.get("nono_state_home"):
        command_env["XDG_STATE_HOME"] = str(request["nono_state_home"])
    commands = [
        ["nono", "rollback", "verify", session_id],
        ["nono", "rollback", "restore", session_id, "--snapshot", snapshot, "--dry-run"],
        ["nono", "rollback", "restore", session_id, "--snapshot", snapshot],
    ]

    results = []
    status = "completed"
    error = None
    for command in commands:
        result = await runner.run(command, env=command_env or None)
        results.append({"command": command, **result})
        if result.get("exit_code") != 0:
            status = "failed"
            error = result.get("stderr") or "rollback command failed"
            break

    event = {
        "event_type": "agent.rollback.completed",
        "id": request.get("id"),
        "run_id": run_id,
        "nono_session_id": session_id,
        "nono_state_home": request.get("nono_state_home"),
        "snapshot": int(snapshot),
        "requested_by": request.get("requested_by", "worker"),
        "status": status,
        "error": error,
        "command_results": results,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    await publisher.publish(completed_topic, event)
    return event
