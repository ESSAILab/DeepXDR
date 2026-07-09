from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from ai_agent.agent_guard.sql_repository import SqlAlchemyAgentSessionRepository


def test_sql_repository_exposes_expected_methods():
    assert hasattr(SqlAlchemyAgentSessionRepository, "upsert_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "list_sessions")
    assert hasattr(SqlAlchemyAgentSessionRepository, "get_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "update_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "delete_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "store_rollback")


def test_session_to_dict_preserves_nono_state_home_from_raw_event():
    row = SimpleNamespace(
        run_id="run-1",
        nono_session_id="nono-1",
        original_request="change file",
        agent_command=["agent"],
        workspace="/repo",
        diff_ref={},
        conversation=None,
        status="adjudicated",
        decision=None,
        rollback_status="not_requested",
        raw_event={
            "nono": {
                "session_id": "nono-1",
                "state_home": "/root/.cache/deepxdr-nono/run-1",
                "rollback_root": "/root/.cache/deepxdr-nono/run-1/nono/rollbacks",
            }
        },
        created_at=datetime(2026, 7, 2, 17, 0, 0),
        updated_at=datetime(2026, 7, 2, 17, 1, 0),
    )

    session = SqlAlchemyAgentSessionRepository._session_to_dict(row)

    assert session["nono"] == {
        "session_id": "nono-1",
        "state_home": "/root/.cache/deepxdr-nono/run-1",
        "rollback_root": "/root/.cache/deepxdr-nono/run-1/nono/rollbacks",
    }


def test_session_to_dict_exposes_latest_rollback_failure_reason():
    row = SimpleNamespace(
        run_id="run-1",
        nono_session_id="nono-1",
        original_request="change file",
        agent_command=["agent"],
        workspace="/repo",
        diff_ref={},
        conversation=None,
        status="adjudicated",
        decision="rollback_failed",
        rollback_status="failed",
        raw_event={"nono": {"session_id": "nono-1"}},
        created_at=datetime(2026, 7, 2, 17, 0, 0),
        updated_at=datetime(2026, 7, 2, 17, 1, 0),
    )
    rollback = SimpleNamespace(
        id="rollback-1",
        run_id="run-1",
        nono_session_id="nono-1",
        snapshot=0,
        requested_by="web_ui",
        status="failed",
        command_results=[{"command": ["nono", "rollback", "verify", "nono-1"], "exit_code": 1}],
        error_message="nono: Session not found: nono-1",
        requested_at=datetime(2026, 7, 2, 17, 2, 0),
        completed_at=datetime(2026, 7, 2, 17, 3, 0),
    )

    session = SqlAlchemyAgentSessionRepository._session_to_dict(row, rollback)

    assert session["rollback_error"] == "nono: Session not found: nono-1"
    assert session["rollback"]["status"] == "failed"
    assert session["rollback"]["command_results"][0]["exit_code"] == 1


def test_session_to_dict_returns_truncated_multi_file_change_preview():
    large_diff = "+secret\n" + ("x" * 12_000)
    raw_event = {
        "nono": {"session_id": "nono-1"},
        "changed_files": [
            {
                "path": "src/service.py",
                "change_type": "modified",
                "added_lines": 100,
                "deleted_lines": 20,
                "diff": large_diff,
            },
            {
                "path": "README.md",
                "change_type": "modified",
                "added_lines": 1,
                "deleted_lines": 1,
                "diff": "-old\n+new\n",
            },
        ],
        "adjudication": {"summary": "multi file change"},
    }
    row = SimpleNamespace(
        run_id="run-1",
        nono_session_id="nono-1",
        original_request="change multiple files",
        agent_command=["agent"],
        workspace="/repo",
        diff_ref={},
        conversation=None,
        status="adjudicated",
        decision=None,
        rollback_status="not_requested",
        raw_event=raw_event,
        created_at=datetime(2026, 7, 2, 17, 0, 0),
        updated_at=datetime(2026, 7, 2, 17, 1, 0),
    )

    session = SqlAlchemyAgentSessionRepository._session_to_dict(row)

    assert len(session["changed_files_preview"]) == 2
    assert session["changed_files_preview"][0]["path"] == "src/service.py"
    assert session["changed_files_preview"][0]["diff_truncated"] is True
    assert len(session["changed_files_preview"][0]["diff"]) < len(large_diff)
    assert session["changed_files_preview"][1]["diff_truncated"] is False
    assert session["raw_event"]["changed_files"][0]["diff"] != large_diff
    assert session["raw_event"]["changed_files"][0]["diff_truncated"] is True
