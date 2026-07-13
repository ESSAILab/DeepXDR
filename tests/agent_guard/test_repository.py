from __future__ import annotations

import anyio
import pytest

from ai_agent.agent_guard.repository import (
    InMemoryAgentSessionRepository,
    RollbackDeletionBlocked,
)


def test_repository_stores_lists_and_updates_agent_session():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        await repo.upsert_session(
            {
                "run_id": "run-1",
                "original_request": "修改 README",
                "adjudication": {"verdict": "warn", "risk_level": "high"},
                "rollback_status": "not_requested",
            }
        )

        sessions = await repo.list_sessions()
        detail = await repo.get_session("run-1")
        await repo.update_session("run-1", {"rollback_status": "requested"})

        assert sessions["total"] == 1
        assert sessions["items"][0]["run_id"] == "run-1"
        assert detail["adjudication"]["verdict"] == "warn"
        assert (await repo.get_session("run-1"))["rollback_status"] == "requested"

    anyio.run(run_test)


def test_repository_deletes_agent_session():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        await repo.upsert_session(
            {
                "run_id": "run-1",
                "original_request": "修改 README",
                "rollback_status": "not_requested",
            }
        )

        assert await repo.delete_session("run-1") is True
        assert await repo.get_session("run-1") is None
        assert await repo.delete_session("run-1") is False

    anyio.run(run_test)


def test_repository_keeps_deleted_session_hidden_on_replayed_upsert():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        await repo.upsert_session(
            {
                "run_id": "run-1",
                "original_request": "修改 README",
                "rollback_status": "not_requested",
            }
        )
        await repo.store_rollback(
            {
                "id": "rollback-completed",
                "run_id": "run-1",
                "nono_session_id": "nono-1",
                "snapshot": 0,
                "requested_by": "user-1",
                "status": "completed",
            }
        )
        assert await repo.delete_session("run-1") is True

        await repo.upsert_session(
            {
                "run_id": "run-1",
                "original_request": "重放消息",
                "status": "adjudicated",
                "rollback_status": "not_requested",
            }
        )

        assert await repo.get_session("run-1") is None
        assert (await repo.list_sessions())["total"] == 0

    anyio.run(run_test)


def test_repository_returns_none_for_missing_session():
    async def run_test():
        repo = InMemoryAgentSessionRepository()

        assert await repo.get_session("missing") is None

    anyio.run(run_test)


def test_repository_claims_and_finishes_rollback_execution_once():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        request = {
            "id": "rollback-1",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "requested",
        }
        await repo.store_rollback(request)

        assert await repo.claim_rollback_execution(request) == "claimed"
        assert (await repo.get_rollback("rollback-1"))["status"] == "executing"
        assert await repo.claim_rollback_execution(request) == "executing"

        await repo.finish_rollback_execution(
            {
                **request,
                "status": "completed",
                "command_results": [{"exit_code": 0}],
                "error": None,
            }
        )

        assert await repo.claim_rollback_execution(request) == "completed"
        assert (await repo.get_rollback("rollback-1"))["command_results"] == [{"exit_code": 0}]

    anyio.run(run_test)


def test_repository_claims_queued_rollback_execution_and_publication_retry():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        request = {
            "id": "rollback-1",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "requested",
        }
        await repo.store_rollback(request)

        assert await repo.finish_rollback_publication("rollback-1", published=False) == "requested"
        assert await repo.finish_rollback_publication("rollback-1", published=True) == "queued"
        assert await repo.claim_rollback_execution({**request, "status": "queued"}) == "claimed"

    anyio.run(run_test)


def test_repository_reuses_rollback_operation_for_same_identity_and_splits_state_home():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        request = {
            "id": "rollback-client-1",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "requested",
            "nono_state_home": "/var/lib/nono/run-1",
        }

        first = await repo.request_rollback(request)
        duplicate = await repo.request_rollback({**request, "id": "rollback-client-2", "requested_by": "user-2"})
        different_state = await repo.request_rollback(
            {
                **request,
                "id": "rollback-client-3",
                "nono_state_home": "/var/lib/nono/run-1-other",
            }
        )

        assert first["_created"] is True
        assert duplicate["_created"] is False
        assert duplicate["id"] == first["id"]
        assert duplicate["requested_by"] == "user-1"
        assert different_state["_created"] is True
        assert different_state["id"] != first["id"]
        assert len(repo.rollbacks) == 2

    anyio.run(run_test)


def test_repository_reuses_active_rollback_before_isolated_duplicate():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        base = {
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "nono_state_home": "/var/lib/nono/run-1",
        }
        await repo.store_rollback(
            {
                **base,
                "id": "rollback-isolated",
                "status": "failed",
                "error": "duplicate active rollback isolated during schema migration",
            }
        )
        await repo.store_rollback({**base, "id": "rollback-active", "status": "queued"})

        duplicate = await repo.request_rollback({**base, "id": "rollback-client", "status": "requested"})

        assert duplicate["id"] == "rollback-active"
        assert duplicate["_created"] is False

    anyio.run(run_test)


def test_repository_rollbacks_include_state_home_in_execution_identity():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        request = {
            "id": "rollback-state-home",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "requested",
            "nono_state_home": "/var/lib/nono/run-1",
        }
        await repo.store_rollback(request)

        assert await repo.claim_rollback_execution({**request, "nono_state_home": "/var/lib/nono/other"}) == "mismatch"
        assert await repo.claim_rollback_execution(request) == "claimed"

    anyio.run(run_test)


def test_repository_backfills_legacy_empty_state_home_on_execution_claim():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        request = {
            "id": "rollback-state-home",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "queued",
            "nono_state_home": "",
        }
        await repo.store_rollback(request)

        assert await repo.claim_rollback_execution({**request, "nono_state_home": "/var/lib/nono/run-1"}) == "claimed"
        assert (await repo.get_rollback("rollback-state-home"))["nono_state_home"] == "/var/lib/nono/run-1"

    anyio.run(run_test)


def test_repository_refuses_to_delete_session_with_requested_rollback_ledger():
    async def run_test():
        repo = InMemoryAgentSessionRepository()
        await repo.upsert_session(
            {
                "run_id": "run-1",
                "nono": {"session_id": "nono-1"},
                "original_request": "修改 README",
                "rollback_status": "requested",
            }
        )
        request = {
            "id": "rollback-requested",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "requested",
        }
        await repo.store_rollback(request)

        with pytest.raises(RollbackDeletionBlocked):
            await repo.delete_session("run-1")

        assert await repo.get_session("run-1") is not None
        assert await repo.get_rollback("rollback-requested") is not None

    anyio.run(run_test)
