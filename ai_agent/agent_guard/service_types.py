from __future__ import annotations

from dataclasses import dataclass, field

from .adjudicator import AdjudicationResult
from .context_planner import ContextPlan
from .diff_parser import ChangedFile
from .rule_engine import RiskSignal


@dataclass(frozen=True)
class AgentSessionProcessResult:
    status: str
    changed_files: list[ChangedFile] = field(default_factory=list)
    risk_signals_by_file: dict[str, list[RiskSignal]] = field(default_factory=dict)
    context_plan: ContextPlan | None = None
    adjudication: AdjudicationResult | None = None
    error: str | None = None
