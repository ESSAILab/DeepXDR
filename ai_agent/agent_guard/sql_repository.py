from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models import AgentAdjudication, AgentRollback, AgentSession


class SqlAlchemyAgentSessionRepository:
    """PostgreSQL-backed repository for agent session audit records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_session(self, session: dict[str, Any]) -> dict[str, Any]:
        run_id = session["run_id"]
        existing = await self.db.get(AgentSession, run_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        nono = session.get("nono") or {}
        values = {
            "run_id": run_id,
            "nono_session_id": nono.get("session_id") or session.get("nono_session_id") or "",
            "original_request": session.get("original_request", ""),
            "agent_command": session.get("agent_command"),
            "workspace": session.get("workspace", ""),
            "diff_ref": session.get("diff_ref") or {},
            "conversation": session.get("conversation"),
            "status": session.get("status", "received"),
            "rollback_status": session.get("rollback_status", "not_requested"),
            "raw_event": session,
            "updated_at": now,
        }
        if existing is None:
            existing = AgentSession(**values, created_at=now)
            self.db.add(existing)
        else:
            for key, value in values.items():
                setattr(existing, key, value)

        adjudication = session.get("adjudication")
        if adjudication:
            await self._store_adjudication(run_id, adjudication)

        await self.db.commit()
        return await self.get_session(run_id) or {}

    async def list_sessions(self, *, page: int = 1, size: int = 20) -> dict[str, Any]:
        offset = (page - 1) * size
        rows = (
            await self.db.execute(
                select(AgentSession)
                .order_by(desc(AgentSession.updated_at))
                .limit(size)
                .offset(offset)
            )
        ).scalars().all()
        total = await self.db.scalar(select(func.count()).select_from(AgentSession))
        return {
            "items": [self._session_to_dict(row) for row in rows],
            "total": total or 0,
            "page": page,
            "size": size,
        }

    async def get_session(self, run_id: str) -> dict[str, Any] | None:
        row = await self.db.get(AgentSession, run_id)
        if row is None:
            return None
        return self._session_to_dict(row)

    async def update_session(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        row = await self.db.get(AgentSession, run_id)
        if row is None:
            return None
        for key, value in updates.items():
            if hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.commit()
        return self._session_to_dict(row)

    async def store_rollback(self, rollback: dict[str, Any]) -> None:
        row = AgentRollback(
            id=rollback["id"],
            run_id=rollback["run_id"],
            nono_session_id=rollback["nono_session_id"],
            snapshot=rollback.get("snapshot", 0),
            requested_by=rollback["requested_by"],
            status=rollback["status"],
            command_results=rollback.get("command_results"),
            error_message=rollback.get("error"),
        )
        self.db.add(row)
        await self.db.commit()

    async def _store_adjudication(self, run_id: str, adjudication: dict[str, Any]) -> None:
        row = AgentAdjudication(
            id=f"{run_id}:latest",
            run_id=run_id,
            verdict=adjudication.get("verdict", "needs_human_review"),
            risk_level=adjudication.get("risk_level", "medium"),
            out_of_intent=adjudication.get("out_of_intent"),
            confidence=adjudication.get("confidence"),
            summary=adjudication.get("summary", ""),
            findings=adjudication.get("findings", []),
            recommended_action=adjudication.get("recommended_action", "ask_user"),
            rollback_recommended=bool(adjudication.get("rollback_recommended", False)),
            raw_result=adjudication,
        )
        await self.db.merge(row)

    @staticmethod
    def _session_to_dict(row: AgentSession) -> dict[str, Any]:
        return {
            "run_id": row.run_id,
            "nono": {"session_id": row.nono_session_id},
            "original_request": row.original_request,
            "agent_command": row.agent_command,
            "workspace": row.workspace,
            "diff_ref": row.diff_ref,
            "conversation": row.conversation,
            "status": row.status,
            "rollback_status": row.rollback_status,
            "raw_event": row.raw_event,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
