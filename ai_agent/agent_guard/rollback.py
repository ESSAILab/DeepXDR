from __future__ import annotations

import uuid
from datetime import datetime, timezone


def build_rollback_requested_event(
    *,
    run_id: str,
    nono_session_id: str,
    requested_by: str,
    approved: bool,
    nono_state_home: str | None = None,
    snapshot: int = 0,
    reason: str = "user approved resilient restore",
) -> dict:
    if not approved:
        raise ValueError("user approval is required before rollback")
    return {
        "id": f"rollback-{uuid.uuid4().hex}",
        "event_type": "agent.rollback.requested",
        "run_id": run_id,
        "nono_session_id": nono_session_id,
        "nono_state_home": nono_state_home,
        "snapshot": snapshot,
        "requested_by": requested_by,
        "reason": reason,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
