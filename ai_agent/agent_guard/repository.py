from __future__ import annotations

import hashlib
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


ACTIVE_ROLLBACK_STATUSES = {"requested", "queued", "executing"}


class RollbackDeletionBlocked(RuntimeError):
    """Raised when deleting a session would orphan an active rollback ledger."""


@dataclass
class InMemoryAgentSessionRepository:
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    rollbacks: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def upsert_session(self, session: dict[str, Any]) -> dict[str, Any]:
        run_id = session["run_id"]
        now = datetime.now(timezone.utc).isoformat()
        existing = self.sessions.get(run_id, {})
        merged = {
            **existing,
            **deepcopy(session),
            "updated_at": now,
            "created_at": existing.get("created_at", session.get("created_at", now)),
        }
        if existing.get("status") == "deleted":
            merged["status"] = "deleted"
        self.sessions[run_id] = merged
        return deepcopy(merged)

    async def list_sessions(self, *, page: int = 1, size: int = 20) -> dict[str, Any]:
        visible_sessions = [
            session
            for session in self.sessions.values()
            if session.get("status") != "deleted"
        ]
        items = sorted(visible_sessions, key=lambda item: item.get("updated_at", ""), reverse=True)
        offset = (page - 1) * size
        return {
            "items": deepcopy(items[offset : offset + size]),
            "total": len(items),
            "page": page,
            "size": size,
        }

    async def get_session(self, run_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(run_id)
        if session and session.get("status") == "deleted":
            return None
        return deepcopy(session) if session else None

    async def update_session(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        session = self.sessions.get(run_id)
        if not session:
            return None
        session.update(deepcopy(updates))
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        return deepcopy(session)

    async def delete_session(self, run_id: str) -> bool:
        session = self.sessions.get(run_id)
        if session is None or session.get("status") == "deleted":
            return False
        if any(
            rollback.get("run_id") == run_id
            and str(rollback.get("status") or "") in ACTIVE_ROLLBACK_STATUSES
            for rollback in self.rollbacks.values()
        ):
            raise RollbackDeletionBlocked("Rollback execution ledger is active")
        if any(rollback.get("run_id") == run_id for rollback in self.rollbacks.values()):
            session["status"] = "deleted"
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            return True
        del self.sessions[run_id]
        return True

    async def request_rollback(self, rollback: dict[str, Any]) -> dict[str, Any]:
        normalized = _normalize_rollback_request(rollback)
        for existing in sorted(self.rollbacks.values(), key=_rollback_lookup_priority):
            if _rollback_identity_matches(existing, normalized):
                return {**deepcopy(existing), "_created": False}
        self.rollbacks[normalized["id"]] = deepcopy(normalized)
        return {**deepcopy(normalized), "_created": True}

    async def store_rollback(self, rollback: dict[str, Any]) -> None:
        normalized = _normalize_stored_rollback(rollback)
        rollback_id = normalized["id"]
        self.rollbacks[rollback_id] = {
            **self.rollbacks.get(rollback_id, {}),
            **deepcopy(normalized),
        }

    async def get_rollback(self, rollback_id: str) -> dict[str, Any] | None:
        rollback = self.rollbacks.get(rollback_id)
        return deepcopy(rollback) if rollback else None

    async def claim_rollback_execution(self, request: dict[str, Any]) -> str:
        rollback = self.rollbacks.get(request["id"])
        if rollback is None:
            return "missing"
        if not _rollback_identity_matches(rollback, request):
            return "mismatch"
        if not rollback.get("nono_state_home") and (request.get("nono_state_home") or request.get("state_home")):
            rollback["nono_state_home"] = _normalize_state_home(request.get("nono_state_home") or request.get("state_home"))
        status = str(rollback.get("status") or "")
        if status in {"requested", "queued"}:
            rollback["status"] = "executing"
            return "claimed"
        if status in {"executing", "completed", "failed"}:
            return status
        return "invalid"

    async def finish_rollback_publication(self, rollback_id: str, *, published: bool) -> str:
        rollback = self.rollbacks.get(rollback_id)
        if rollback is None:
            return "missing"
        if not published:
            return str(rollback.get("status") or "invalid")
        if rollback.get("status") == "requested":
            rollback["status"] = "queued"
        return str(rollback["status"])

    async def finish_rollback_execution(self, completed: dict[str, Any]) -> None:
        rollback = self.rollbacks.get(completed["id"])
        if rollback is None:
            raise RuntimeError("rollback execution ledger row is missing")
        if not _rollback_identity_matches(rollback, completed):
            raise RuntimeError("rollback execution identity does not match ledger row")
        status = str(completed.get("status") or "")
        if status not in {"completed", "failed"}:
            raise ValueError("rollback execution terminal status must be completed or failed")
        if rollback.get("status") in {"completed", "failed"}:
            return
        if rollback.get("status") != "executing":
            raise RuntimeError("rollback execution must be claimed before completion")
        rollback.update(
            {
                "status": status,
                "command_results": deepcopy(completed.get("command_results")),
                "error": completed.get("error"),
                "completed_at": completed.get("completed_at"),
            }
        )


def _rollback_identity_matches(stored: dict[str, Any], request: dict[str, Any]) -> bool:
    return (
        stored.get("run_id") == request.get("run_id")
        and stored.get("nono_session_id") == request.get("nono_session_id")
        and int(stored.get("snapshot", 0)) == int(request.get("snapshot", 0))
        and _rollback_state_home_matches(stored, request)
    )


def _rollback_state_home_matches(stored: dict[str, Any], request: dict[str, Any]) -> bool:
    stored_state_home = _normalize_state_home(stored.get("nono_state_home") or stored.get("state_home"))
    request_state_home = _normalize_state_home(request.get("nono_state_home") or request.get("state_home"))
    return not stored_state_home or stored_state_home == request_state_home


def _normalize_rollback_request(rollback: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_stored_rollback(rollback)
    normalized["id"] = build_rollback_operation_id(
        run_id=str(normalized["run_id"]),
        nono_session_id=str(normalized["nono_session_id"]),
        snapshot=normalized["snapshot"],
        nono_state_home=normalized["nono_state_home"],
    )
    return normalized


def _normalize_stored_rollback(rollback: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(rollback)
    normalized_state_home = _normalize_state_home(
        normalized.get("nono_state_home") or normalized.get("state_home")
    )
    normalized["nono_state_home"] = normalized_state_home
    normalized["snapshot"] = int(normalized.get("snapshot", 0))
    normalized.setdefault("status", "requested")
    return normalized


def _normalize_state_home(value: Any) -> str:
    if value is None or value == "":
        return ""
    return os.path.abspath(os.path.expanduser(str(value)))


def build_rollback_operation_id(
    *,
    run_id: str,
    nono_session_id: str,
    snapshot: int,
    nono_state_home: str,
) -> str:
    identity = "\0".join([run_id, nono_session_id, str(snapshot), nono_state_home])
    return f"rollback-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"


def _rollback_lookup_priority(rollback: dict[str, Any]) -> int:
    status = str(rollback.get("status") or "")
    if status in {"queued", "requested", "executing"}:
        return 0
    if status == "completed":
        return 1
    if status == "failed" and rollback.get("error") == "duplicate active rollback isolated during schema migration":
        return 3
    if status == "failed" and rollback.get("error_message") == "duplicate active rollback isolated during schema migration":
        return 3
    return 2
