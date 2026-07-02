from __future__ import annotations

from dataclasses import dataclass, field

from .config import AgentGuardConfig
from .diff_parser import ChangedFile
from .rule_engine import RiskSignal


@dataclass(frozen=True)
class ContextPlan:
    strategy: str
    force_human_review: bool = False
    high_risk_files: list[str] = field(default_factory=list)


def plan_context(
    *,
    total_tokens: int,
    files: list[ChangedFile],
    risk_signals_by_file: dict[str, list[RiskSignal]],
    config: AgentGuardConfig,
) -> ContextPlan:
    if total_tokens <= config.small_diff_token_limit:
        return ContextPlan(strategy="file_level")

    if total_tokens <= config.medium_diff_token_limit:
        return ContextPlan(strategy="hunk_summary")

    high_risk_files = [
        changed.path
        for changed in files
        if any(signal.severity == "high" for signal in risk_signals_by_file.get(changed.path, []))
    ][: config.max_high_risk_snippets]
    return ContextPlan(
        strategy="risk_only",
        force_human_review=config.force_review_on_huge_diff,
        high_risk_files=high_risk_files,
    )
