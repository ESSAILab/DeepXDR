from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from ai_agent.agent_guard.sql_repository import SqlAlchemyAgentSessionRepository


def test_sql_repository_exposes_expected_methods():
    assert hasattr(SqlAlchemyAgentSessionRepository, "upsert_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "list_sessions")
    assert hasattr(SqlAlchemyAgentSessionRepository, "get_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "update_session")
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
