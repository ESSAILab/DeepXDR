from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from .adjudication_graph import AnalysisCancellationToken
from .adjudicator import LLMClient
from .config import AgentGuardConfig
from .repository import InMemoryAgentSessionRepository
from .service import process_finished_session_event


class AgentSessionEventHandler:
    def __init__(
        self,
        *,
        repository: InMemoryAgentSessionRepository,
        config: AgentGuardConfig,
        llm: LLMClient,
    ):
        self.repository = repository
        self.config = config
        self.llm = llm

    async def handle(
        self,
        event: dict[str, Any],
        *,
        cancellation_token: AnalysisCancellationToken | None = None,
    ):
        cancellation_token = cancellation_token or AnalysisCancellationToken()
        try:
            result = await asyncio.to_thread(
                process_finished_session_event,
                event,
                config=self.config,
                llm=self.llm,
                cancellation_token=cancellation_token,
            )
        except asyncio.CancelledError:
            cancellation_token.cancel()
            raise
        adjudication = asdict(result.adjudication) if result.adjudication else None
        await self.repository.upsert_session(
            {
                **event,
                "status": result.status,
                "changed_files": [asdict(changed) for changed in result.changed_files],
                "risk_signals_by_file": {
                    path: [asdict(signal) for signal in signals]
                    for path, signals in result.risk_signals_by_file.items()
                },
                "context_plan": asdict(result.context_plan) if result.context_plan else None,
                "adjudication": adjudication,
                "rollback_status": event.get("rollback_status", "not_requested"),
                "error": result.error,
            }
        )
        return result
