from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class InMemoryAgentSessionRepository:
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)

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
        self.sessions[run_id] = merged
        return deepcopy(merged)

    async def list_sessions(self, *, page: int = 1, size: int = 20) -> dict[str, Any]:
        items = sorted(self.sessions.values(), key=lambda item: item.get("updated_at", ""), reverse=True)
        offset = (page - 1) * size
        return {
            "items": deepcopy(items[offset : offset + size]),
            "total": len(items),
            "page": page,
            "size": size,
        }

    async def get_session(self, run_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(run_id)
        return deepcopy(session) if session else None

    async def update_session(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        session = self.sessions.get(run_id)
        if not session:
            return None
        session.update(deepcopy(updates))
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        return deepcopy(session)
