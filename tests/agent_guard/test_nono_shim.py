from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_nono_shim_runs_real_nono_and_writes_agent_session_event(tmp_path):
    real_nono = tmp_path / "nono.real"
    calls_file = tmp_path / "calls.jsonl"
    real_nono.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

calls = Path(os.environ["CALLS_FILE"])
with calls.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "xdg": os.environ.get("XDG_STATE_HOME")}) + "\\n")

if sys.argv[1:4] == ["rollback", "show", "session-1"]:
    if "--json" in sys.argv:
        print(json.dumps({"session_id": "session-1", "tracked_paths": [os.getcwd()]}))
        sys.exit(0)
    if "--diff" in sys.argv:
        print("diff --git a/README.md b/README.md")
        print("+new")
        sys.exit(0)

print(json.dumps({"session_id": "session-1"}))
sys.exit(0)
""",
        encoding="utf-8",
    )
    real_nono.chmod(0o755)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_home = tmp_path / "state"
    evidence_dir = tmp_path / "evidence"
    events_file = tmp_path / "agent-events.jsonl"

    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[2]
    pythonpath = os.pathsep.join([str(repo_root), str(repo_root / "ai_agent"), env.get("PYTHONPATH", "")])
    env.update(
        {
            "PYTHONPATH": pythonpath,
            "CALLS_FILE": str(calls_file),
            "DEEPXDR_REAL_NONO": str(real_nono),
            "DEEPXDR_NONO_STATE_HOME": str(state_home),
            "DEEPXDR_AGENT_EVIDENCE_DIR": str(evidence_dir),
            "DEEPXDR_AGENT_EVENTS_FILE": str(events_file),
            "DEEPXDR_AGENT_ORIGINAL_REQUEST": "update README",
            "DEEPXDR_AGENT_RUN_ID": "run-shim-1",
        }
    )

    result = subprocess.run(
        [str(repo_root / "scripts" / "nono"), "run", "--rollback", "--allow", str(workspace), "--", "codex", "run"],
        cwd=str(workspace),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    calls = [json.loads(line) for line in calls_file.read_text(encoding="utf-8").splitlines()]
    assert calls[0]["argv"] == ["run", "--rollback", "--allow", str(workspace), "--", "codex", "run"]
    assert calls[0]["xdg"] == str(state_home)
    assert ["rollback", "show", "session-1", "--json"] in [call["argv"] for call in calls]
    assert ["rollback", "show", "session-1", "--diff"] in [call["argv"] for call in calls]

    event = json.loads(events_file.read_text(encoding="utf-8").splitlines()[0])
    assert event["type"] == "agent_session"
    assert event["event_type"] == "finished"
    assert event["source"] == "nono-path-shim"
    assert event["run_id"] == "run-shim-1"
    assert event["original_request"] == "update README"
    assert event["workspace"] == str(workspace)
    assert event["agent_command"] == ["codex", "run"]
    assert event["nono"]["session_id"] == "session-1"
    assert event["nono"]["state_home"] == str(state_home)

    diff_text = Path(event["diff_ref"]["uri"]).read_text(encoding="utf-8")
    assert "+new" in diff_text
    assert event["diff_ref"]["sha256"]
