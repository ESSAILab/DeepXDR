from __future__ import annotations

from dataclasses import dataclass, field

from .adjudicator import AdjudicationResult, LLMClient, adjudicate_session
from .config import AgentGuardConfig
from .context_planner import ContextPlan, plan_context
from .diff_parser import ChangedFile, estimate_token_count, parse_unified_diff
from .diff_store import DiffEvidenceError, DiffRef, load_diff_text
from .rule_engine import RiskSignal, detect_risk_signals


@dataclass(frozen=True)
class AgentSessionProcessResult:
    status: str
    changed_files: list[ChangedFile] = field(default_factory=list)
    risk_signals_by_file: dict[str, list[RiskSignal]] = field(default_factory=dict)
    context_plan: ContextPlan | None = None
    adjudication: AdjudicationResult | None = None
    error: str | None = None


def process_finished_session_event(
    event: dict,
    *,
    config: AgentGuardConfig,
    llm: LLMClient,
) -> AgentSessionProcessResult:
    try:
        raw_ref = event["diff_ref"]
        diff_ref = DiffRef(
            storage=raw_ref["storage"],
            uri=raw_ref["uri"],
            sha256=raw_ref["sha256"],
        )
        diff_text = load_diff_text(diff_ref)
    except (KeyError, DiffEvidenceError, OSError) as exc:
        return AgentSessionProcessResult(status="evidence_invalid", error=str(exc))

    changed_files = parse_unified_diff(diff_text)
    risk_signals_by_file = {
        changed.path: detect_risk_signals(changed)
        for changed in changed_files
    }
    context_plan = plan_context(
        total_tokens=estimate_token_count(diff_text),
        files=changed_files,
        risk_signals_by_file=risk_signals_by_file,
        config=config,
    )

    if context_plan.force_human_review:
        adjudication = AdjudicationResult(
            verdict="needs_human_review",
            risk_level="medium",
            out_of_intent=None,
            summary="Diff exceeds configured threshold; human review is required.",
            recommended_action="ask_user",
        )
    else:
        adjudication = adjudicate_session(
            original_request=event.get("original_request", ""),
            changed_files=changed_files,
            context_plan=context_plan,
            risk_signals_by_file=risk_signals_by_file,
            llm=llm,
        )

    return AgentSessionProcessResult(
        status="adjudicated",
        changed_files=changed_files,
        risk_signals_by_file=risk_signals_by_file,
        context_plan=context_plan,
        adjudication=adjudication,
    )
