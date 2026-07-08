from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, desc, func, nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models import AgentAdjudication, AgentRollback, AgentSession
from shared.database.connection import get_db


MAX_WEB_UI_DIFF_CHARS_PER_FILE = 8_000


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
            "decision": session.get("decision"),
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
        rollback_by_run_id = await self._latest_rollbacks_for_runs([row.run_id for row in rows])
        total = await self.db.scalar(select(func.count()).select_from(AgentSession))
        return {
            "items": [self._session_to_dict(row, rollback_by_run_id.get(row.run_id)) for row in rows],
            "total": total or 0,
            "page": page,
            "size": size,
        }

    async def get_session(self, run_id: str) -> dict[str, Any] | None:
        row = await self.db.get(AgentSession, run_id)
        if row is None:
            return None
        return self._session_to_dict(row, await self._latest_rollback_for_run(run_id))

    async def update_session(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        row = await self.db.get(AgentSession, run_id)
        if row is None:
            return None
        for key, value in updates.items():
            if hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.commit()
        return self._session_to_dict(row, await self._latest_rollback_for_run(run_id))

    async def delete_session(self, run_id: str) -> bool:
        row = await self.db.get(AgentSession, run_id)
        if row is None:
            return False
        await self.db.execute(delete(AgentRollback).where(AgentRollback.run_id == run_id))
        await self.db.execute(delete(AgentAdjudication).where(AgentAdjudication.run_id == run_id))
        await self.db.delete(row)
        await self.db.commit()
        return True

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
            completed_at=_parse_datetime(rollback.get("completed_at")),
        )
        await self.db.merge(row)
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

    async def _latest_rollback_for_run(self, run_id: str) -> AgentRollback | None:
        return (
            await self.db.execute(
                select(AgentRollback)
                .where(AgentRollback.run_id == run_id)
                .order_by(nullslast(desc(AgentRollback.completed_at)), desc(AgentRollback.requested_at))
                .limit(1)
            )
        ).scalars().first()

    async def _latest_rollbacks_for_runs(self, run_ids: list[str]) -> dict[str, AgentRollback]:
        if not run_ids:
            return {}
        rows = (
            await self.db.execute(
                select(AgentRollback)
                .where(AgentRollback.run_id.in_(run_ids))
                .order_by(
                    AgentRollback.run_id,
                    nullslast(desc(AgentRollback.completed_at)),
                    desc(AgentRollback.requested_at),
                )
            )
        ).scalars().all()
        rollback_by_run_id: dict[str, AgentRollback] = {}
        for row in rows:
            rollback_by_run_id.setdefault(row.run_id, row)
        return rollback_by_run_id

    @staticmethod
    def _session_to_dict(row: AgentSession, rollback: AgentRollback | None = None) -> dict[str, Any]:
        raw_event = row.raw_event if isinstance(row.raw_event, dict) else {}
        safe_raw_event, changed_files_preview = _build_web_ui_raw_event(raw_event)
        raw_nono = raw_event.get("nono") if isinstance(raw_event.get("nono"), dict) else {}
        nono = {"session_id": row.nono_session_id}
        for key in ("state_home", "rollback_root"):
            if raw_nono.get(key):
                nono[key] = raw_nono[key]
        rollback_info = _rollback_to_dict(rollback) if rollback else None
        return {
            "run_id": row.run_id,
            "nono": nono,
            "original_request": row.original_request,
            "agent_command": row.agent_command,
            "workspace": row.workspace,
            "diff_ref": row.diff_ref,
            "conversation": row.conversation,
            "status": row.status,
            "decision": row.decision,
            "rollback_status": row.rollback_status,
            "rollback_error": rollback_info.get("error_message") if rollback_info else None,
            "rollback": rollback_info,
            "changed_files_preview": changed_files_preview,
            "raw_event": safe_raw_event,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


class SqlAlchemyAgentSessionRepositoryProvider:
    """Request-scoped repository facade for FastAPI route globals."""

    async def upsert_session(self, session: dict[str, Any]) -> dict[str, Any]:
        async with get_db() as db:
            return await SqlAlchemyAgentSessionRepository(db).upsert_session(session)

    async def list_sessions(self, *, page: int = 1, size: int = 20) -> dict[str, Any]:
        async with get_db() as db:
            return await SqlAlchemyAgentSessionRepository(db).list_sessions(page=page, size=size)

    async def get_session(self, run_id: str) -> dict[str, Any] | None:
        async with get_db() as db:
            return await SqlAlchemyAgentSessionRepository(db).get_session(run_id)

    async def update_session(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        async with get_db() as db:
            return await SqlAlchemyAgentSessionRepository(db).update_session(run_id, updates)

    async def delete_session(self, run_id: str) -> bool:
        async with get_db() as db:
            return await SqlAlchemyAgentSessionRepository(db).delete_session(run_id)

    async def store_rollback(self, rollback: dict[str, Any]) -> None:
        async with get_db() as db:
            await SqlAlchemyAgentSessionRepository(db).store_rollback(rollback)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _rollback_to_dict(row: AgentRollback) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "nono_session_id": row.nono_session_id,
        "snapshot": row.snapshot,
        "requested_by": row.requested_by,
        "status": row.status,
        "command_results": row.command_results,
        "error_message": row.error_message,
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _build_web_ui_raw_event(raw_event: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    safe_raw_event = deepcopy(raw_event)
    changed_files = raw_event.get("changed_files") if isinstance(raw_event.get("changed_files"), list) else []
    changed_files_preview = [_changed_file_preview(changed) for changed in changed_files if isinstance(changed, dict)]
    if changed_files_preview:
        safe_raw_event["changed_files"] = deepcopy(changed_files_preview)
    return safe_raw_event, changed_files_preview


def _changed_file_preview(changed_file: dict[str, Any]) -> dict[str, Any]:
    preview = deepcopy(changed_file)
    diff = preview.get("diff")
    if not isinstance(diff, str):
        preview["diff_truncated"] = False
        preview["diff_original_chars"] = 0
        return preview
    preview["diff_original_chars"] = len(diff)
    if len(diff) <= MAX_WEB_UI_DIFF_CHARS_PER_FILE:
        preview["diff_truncated"] = False
        return preview
    preview["diff"] = diff[:MAX_WEB_UI_DIFF_CHARS_PER_FILE]
    preview["diff_truncated"] = True
    return preview
