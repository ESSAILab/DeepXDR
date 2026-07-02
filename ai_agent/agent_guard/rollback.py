from __future__ import annotations

from datetime import datetime, timezone


def build_rollback_requested_event(
    *,
    run_id: str,
    nono_session_id: str,
    requested_by: str,
    approved: bool,
    reason: str = "user approved resilient restore",
) -> dict:
    if not approved:
        raise ValueError("user approval is required before rollback")
    return {
        "event_type": "agent.rollback.requested",
        "run_id": run_id,
        "nono_session_id": nono_session_id,
        "snapshot": 0,
        "requested_by": requested_by,
        "reason": reason,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
