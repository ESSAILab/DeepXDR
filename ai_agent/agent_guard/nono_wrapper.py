from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from .config import AgentGuardConfig
from .diff_store import create_boto3_diff_store


class AsyncCommandRunner(Protocol):
    async def run(
        self,
        command: list[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> dict:
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


def create_diff_evidence_writer_from_env(*, local_root: str | Path | None = None) -> DiffEvidenceWriter:
    config = AgentGuardConfig.from_env()
    if config.diff_storage in {"s3", "minio"}:
        if not config.diff_bucket:
            raise ValueError("AGENT_GUARD_DIFF_BUCKET is required when AGENT_GUARD_DIFF_STORAGE is s3 or minio")
        return create_boto3_diff_store(
            bucket=config.diff_bucket,
            prefix=config.diff_prefix,
            endpoint_url=config.diff_endpoint_url or None,
            access_key_id=config.diff_access_key_id or None,
            secret_access_key=config.diff_secret_access_key or None,
            region_name=config.diff_region or None,
            storage=config.diff_storage,
        )

    root = Path(local_root or Path.home() / ".cache" / "deepxdr-agent" / "diff-evidence")
    return LocalDiffEvidenceWriter(root)


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
    state_home = str(Path(rollback_dest))
    run_env = {"XDG_STATE_HOME": state_home}
    run_command = [
        "nono",
        "run",
        "--rollback",
        "--no-rollback-prompt",
        "--allow",
        workspace,
        "--",
        *agent_command,
    ]
    run_result = await runner.run(run_command, env=run_env, cwd=workspace)
    if run_result.get("exit_code") != 0:
        raise RuntimeError(run_result.get("stderr") or "nono guarded session failed")

    session_id = _resolve_session_id(
        run_result=run_result,
        rollback_state_home=Path(state_home),
        workspace=workspace,
        fallback=run_id,
    )
    metadata = await runner.run(["nono", "rollback", "show", session_id, "--json"], env=run_env)
    if metadata.get("exit_code") != 0:
        raise RuntimeError(metadata.get("stderr") or "nono rollback metadata lookup failed")
    diff_result = await runner.run(["nono", "rollback", "show", session_id, "--diff"], env=run_env)
    if diff_result.get("exit_code") != 0:
        raise RuntimeError(diff_result.get("stderr") or "nono rollback diff lookup failed")
    diff_text = _combined_output(diff_result)
    diff_ref = diff_writer.write(run_id=run_id, diff_text=diff_text)

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
            "state_home": state_home,
            "rollback_root": str(Path(state_home) / "nono" / "rollbacks"),
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


def _resolve_session_id(
    *,
    run_result: dict,
    rollback_state_home: Path,
    workspace: str,
    fallback: str,
) -> str:
    for text in (run_result.get("stdout", ""), run_result.get("stderr", "")):
        parsed = _parse_json(text)
        if isinstance(parsed, dict):
            session_id = parsed.get("rollback_session") or parsed.get("session_id") or parsed.get("id")
            if session_id:
                return str(session_id)

    discovered = _discover_latest_rollback_session(rollback_state_home, workspace)
    return discovered or fallback


def _discover_latest_rollback_session(state_home: Path, workspace: str) -> str | None:
    rollback_root = state_home / "nono" / "rollbacks"
    if not rollback_root.exists():
        return None

    workspace_real = os.path.realpath(workspace)
    candidates: list[tuple[float, str]] = []
    for session_dir in rollback_root.iterdir():
        if not session_dir.is_dir():
            continue
        manifest = session_dir / "session.json"
        if not manifest.exists():
            manifest = session_dir / "manifest.json"
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue

        tracked_paths = payload.get("tracked_paths") or []
        if tracked_paths and not any(os.path.realpath(str(path)).startswith(workspace_real) for path in tracked_paths):
            continue

        session_id = payload.get("session_id") or session_dir.name
        candidates.append((manifest.stat().st_mtime, str(session_id)))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _combined_output(result: dict) -> str:
    stdout = result.get("stdout", "") or ""
    stderr = result.get("stderr", "") or ""
    if stdout and stderr:
        return f"{stdout.rstrip()}\n{stderr}"
    return stdout or stderr


def _parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None
