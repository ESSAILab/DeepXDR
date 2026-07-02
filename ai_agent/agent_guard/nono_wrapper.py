from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class AsyncCommandRunner(Protocol):
    async def run(self, command: list[str]) -> dict:
        ...


class AsyncTopicPublisher(Protocol):
    async def publish(self, topic: str, event: dict) -> None:
        ...


class DiffEvidenceWriter(Protocol):
    def write(self, *, run_id: str, diff_text: str) -> dict:
        ...


@dataclass(frozen=True)
class LocalDiffEvidenceWriter:
    root: Path

    def write(self, *, run_id: str, diff_text: str) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{run_id}.diff"
        path.write_text(diff_text, encoding="utf-8")
        return {
            "storage": "local",
            "uri": str(path),
            "sha256": hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
            "size_bytes": len(diff_text.encode("utf-8")),
        }


async def run_nono_guarded_session(
    *,
    original_request: str,
    agent_command: list[str],
    workspace: str,
    rollback_dest: str,
    run_id: str,
    runner: AsyncCommandRunner,
    diff_writer: DiffEvidenceWriter,
    publisher: AsyncTopicPublisher,
    events_topic: str = "events",
) -> dict:
    run_command = [
        "nono",
        "run",
        "--rollback",
        "--no-rollback-prompt",
        "--rollback-dest",
        rollback_dest,
        "--allow",
        workspace,
        "--",
        *agent_command,
    ]
    run_result = await runner.run(run_command)

    session_id = _extract_session_id(run_result.get("stdout", ""), fallback=run_id)
    metadata = await runner.run(["nono", "rollback", "show", session_id, "--json"])
    diff_result = await runner.run(["nono", "rollback", "show", session_id, "--diff"])
    diff_ref = diff_writer.write(run_id=run_id, diff_text=diff_result.get("stdout", ""))

    event = {
        "type": "agent_session",
        "event_type": "finished",
        "schema_version": "1.0",
        "run_id": run_id,
        "original_request": original_request,
        "agent_command": agent_command,
        "workspace": workspace,
        "diff_ref": diff_ref,
        "nono": {
            "session_id": session_id,
            "rollback_dest": rollback_dest,
            "exit_code": run_result.get("exit_code"),
            "metadata": _parse_json(metadata.get("stdout", "")),
        },
    }
    await publisher.publish(events_topic, event)
    return event


def _extract_session_id(stdout: str, *, fallback: str) -> str:
    parsed = _parse_json(stdout)
    if isinstance(parsed, dict):
        return parsed.get("session_id") or parsed.get("id") or fallback
    return fallback


def _parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None
