from __future__ import annotations

import pytest

from ai_agent.agent_guard.rollback import build_rollback_requested_event


def test_build_rollback_requested_event_requires_user_approval():
    with pytest.raises(ValueError, match="approval"):
        build_rollback_requested_event(
            run_id="run-1",
            nono_session_id="session-1",
            requested_by="user-1",
            approved=False,
        )


def test_build_rollback_requested_event_targets_snapshot_zero():
    event = build_rollback_requested_event(
        run_id="run-1",
        nono_session_id="session-1",
        requested_by="user-1",
        approved=True,
    )

    assert event["event_type"] == "agent.rollback.requested"
    assert event["run_id"] == "run-1"
    assert event["nono_session_id"] == "session-1"
    assert event["snapshot"] == 0
