from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import anyio
import pytest

from ai_agent.agent_guard.sql_repository import (
    SqlAlchemyAgentSessionRepository,
    RollbackDeletionBlocked,
)


def test_sql_repository_exposes_expected_methods():
    assert hasattr(SqlAlchemyAgentSessionRepository, "upsert_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "list_sessions")
    assert hasattr(SqlAlchemyAgentSessionRepository, "get_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "update_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "delete_session")
    assert hasattr(SqlAlchemyAgentSessionRepository, "request_rollback")
    assert hasattr(SqlAlchemyAgentSessionRepository, "store_rollback")
    assert hasattr(SqlAlchemyAgentSessionRepository, "get_rollback")
    assert hasattr(SqlAlchemyAgentSessionRepository, "claim_rollback_execution")
    assert hasattr(SqlAlchemyAgentSessionRepository, "finish_rollback_publication")
    assert hasattr(SqlAlchemyAgentSessionRepository, "finish_rollback_execution")


def test_sql_repository_atomically_claims_requested_rollback_with_row_lock():
    async def run_test():
        row = SimpleNamespace(
            id="rollback-1",
            run_id="run-1",
            nono_session_id="nono-1",
            snapshot=0,
            requested_by="user-1",
            status="requested",
            command_results=None,
            error_message=None,
            requested_at=datetime(2026, 7, 13, 10, 0, 0),
            completed_at=None,
        )

        class DbStub:
            def __init__(self):
                self.get_calls = []
                self.commits = 0
                self.rollbacks = 0

            async def get(self, model, key, **kwargs):
                self.get_calls.append((model, key, kwargs))
                return row

            async def commit(self):
                self.commits += 1

            async def rollback(self):
                self.rollbacks += 1

        db = DbStub()
        repository = SqlAlchemyAgentSessionRepository(db)
        request = {
            "id": "rollback-1",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
        }

        claim = await repository.claim_rollback_execution(request)

        assert claim == "claimed"
        assert row.status == "executing"
        assert db.commits == 1
        assert db.get_calls[0][2] == {"with_for_update": True}

    anyio.run(run_test)


def test_sql_repository_refuses_delete_when_requested_rollback_exists():
    async def run_test():
        session_row = SimpleNamespace(run_id="run-1", status="adjudicated")
        active_rollback = SimpleNamespace(id="rollback-1", status="requested")

        class ResultStub:
            def scalars(self):
                return self

            def first(self):
                return active_rollback

        class DbStub:
            def __init__(self):
                self.executed = []
                self.commits = 0

            async def get(self, model, key, **kwargs):
                return session_row

            async def execute(self, statement):
                self.executed.append(statement)
                return ResultStub()

            async def commit(self):
                self.commits += 1

        repository = SqlAlchemyAgentSessionRepository(DbStub())

        with pytest.raises(RollbackDeletionBlocked):
            await repository.delete_session("run-1")

        assert session_row.status == "adjudicated"
        assert repository.db.commits == 0

    anyio.run(run_test)


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
        nono_state_home="/var/lib/nono/run-1",
        command_results=[{"command": ["nono", "rollback", "verify", "nono-1"], "exit_code": 1}],
        error_message="nono: Session not found: nono-1",
        requested_at=datetime(2026, 7, 2, 17, 2, 0),
        completed_at=datetime(2026, 7, 2, 17, 3, 0),
    )

    session = SqlAlchemyAgentSessionRepository._session_to_dict(row, rollback)

    assert session["rollback_error"] == "nono: Session not found: nono-1"
    assert session["rollback"]["status"] == "failed"
    assert session["rollback"]["nono_state_home"] == "/var/lib/nono/run-1"
    assert session["rollback"]["command_results"][0]["exit_code"] == 1


def test_session_to_dict_exposes_persisted_adjudication():
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
        raw_event={"nono": {"session_id": "nono-1"}},
        created_at=datetime(2026, 7, 2, 17, 0, 0),
        updated_at=datetime(2026, 7, 2, 17, 1, 0),
    )
    adjudication = SimpleNamespace(
        verdict="warn",
        risk_level="medium",
        out_of_intent=False,
        confidence=0.72,
        summary="变更与原始意图基本一致，但需要人工确认策略影响。",
        findings=[{"summary": "策略被启用"}],
        recommended_action="ask_user",
        rollback_recommended=False,
        raw_result={
            "intent_alignment": "partially_aligned",
            "intent_alignment_reason": "策略整体启用，可能超出隐含范围。",
        },
    )

    session = SqlAlchemyAgentSessionRepository._session_to_dict(row, adjudication=adjudication)

    assert session["adjudication"] == {
        "verdict": "warn",
        "risk_level": "medium",
        "out_of_intent": False,
        "confidence": 0.72,
        "summary": "变更与原始意图基本一致，但需要人工确认策略影响。",
        "findings": [{"summary": "策略被启用"}],
        "recommended_action": "ask_user",
        "rollback_recommended": False,
        "intent_alignment": "partially_aligned",
        "intent_alignment_reason": "策略整体启用，可能超出隐含范围。",
    }


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
