from __future__ import annotations

from shared.database.models import AgentAdjudication, AgentRollback, AgentSession


def test_agent_guard_tables_are_registered_in_metadata():
    assert AgentSession.__tablename__ == "agent_sessions"
    assert AgentAdjudication.__tablename__ == "agent_adjudications"
    assert AgentRollback.__tablename__ == "agent_rollbacks"
    assert "run_id" in AgentSession.__table__.columns
    assert "diff_ref" in AgentSession.__table__.columns
