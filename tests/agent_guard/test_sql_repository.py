from __future__ import annotations

from ai_agent.agent_guard.sql_repository import SqlAlchemyAgentSessionRepository


def test_sql_repository_exposes_expected_methods():
    assert hasattr(SqlAlchemyAgentSessionRepository, "upsert_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "list_sessions")
    assert hasattr(SqlAlchemyAgentSessionRepository, "get_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "update_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "store_rollback")
