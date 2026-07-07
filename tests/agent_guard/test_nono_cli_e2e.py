from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import anyio
import pytest

from ai_agent.agent_guard.command_runner import SubprocessCommandRunner
from ai_agent.agent_guard.nono_wrapper import LocalDiffEvidenceWriter, run_nono_guarded_session
from ai_agent.agent_guard.worker import execute_rollback_request


class CapturePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, *args):
        self.events.append(args)


def _nono_binary(repo_root: Path) -> str | None:
    if path := shutil.which("nono"):
        return path
    candidate = repo_root / "third_party" / "nono" / "target" / "debug" / "nono"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def test_nono_guarded_session_and_rollback_restore_with_real_cli(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    nono = _nono_binary(repo_root)
    if nono is None:
        pytest.skip("real nono binary not found; install nono or build third_party/nono")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "README.md"
    target.write_text("old\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "nono").symlink_to(nono)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    state_home = Path.home() / ".cache" / "deepxdr-nono-e2e" / uuid.uuid4().hex
    evidence_dir = tmp_path / "evidence"
    publisher = CapturePublisher()
    runner = SubprocessCommandRunner()

    async def run_test():
        event = await run_nono_guarded_session(
            original_request="update README",
            agent_command=["/bin/sh", "-c", "printf 'new\\n' > README.md"],
            workspace=str(workspace),
            rollback_dest=str(state_home),
            run_id="run-real",
            runner=runner,
            diff_writer=LocalDiffEvidenceWriter(evidence_dir),
            publisher=publisher,
        )

        diff_text = Path(event["diff_ref"]["uri"]).read_text(encoding="utf-8")
        assert "README.md" in diff_text
        assert "+new" in diff_text
        assert target.read_text(encoding="utf-8") == "new\n"

        rollback_event = await execute_rollback_request(
            {
                "id": "rollback-real",
                "run_id": "run-real",
                "nono_session_id": event["nono"]["session_id"],
                "nono_state_home": event["nono"]["state_home"],
                "snapshot": 0,
                "requested_by": "test",
            },
            runner=runner,
            publisher=publisher,
        )

        assert rollback_event["status"] == "completed"
        assert target.read_text(encoding="utf-8") == "old\n"

    try:
        anyio.run(run_test)
    finally:
        shutil.rmtree(state_home, ignore_errors=True)
