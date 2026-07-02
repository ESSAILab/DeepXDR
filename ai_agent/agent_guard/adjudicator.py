from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from .context_planner import ContextPlan
from .diff_parser import ChangedFile
from .rule_engine import RiskSignal


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class AdjudicationResult:
    verdict: str
    risk_level: str
    out_of_intent: bool | None
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    recommended_action: str = "ask_user"
    rollback_recommended: bool = False


def adjudicate_session(
    *,
    original_request: str,
    changed_files: list[ChangedFile],
    context_plan: ContextPlan,
    risk_signals_by_file: dict[str, list[RiskSignal]],
    llm: LLMClient,
) -> AdjudicationResult:
    prompt = _build_prompt(original_request, changed_files, context_plan, risk_signals_by_file)
    try:
        payload = json.loads(llm.complete(prompt))
        return AdjudicationResult(
            verdict=payload["verdict"],
            risk_level=payload["risk_level"],
            out_of_intent=payload.get("out_of_intent"),
            summary=payload.get("summary", ""),
            findings=payload.get("findings", []),
            recommended_action=payload.get("recommended_action", "ask_user"),
            rollback_recommended=bool(payload.get("rollback_recommended", False)),
        )
    except Exception as exc:
        return AdjudicationResult(
            verdict="needs_human_review",
            risk_level="medium",
            out_of_intent=None,
            summary=f"增量裁决模型输出不可解析: {exc}",
            recommended_action="ask_user",
            rollback_recommended=False,
        )


def _build_prompt(
    original_request: str,
    changed_files: list[ChangedFile],
    context_plan: ContextPlan,
    risk_signals_by_file: dict[str, list[RiskSignal]],
) -> str:
    file_lines = []
    for changed in changed_files:
        signals = risk_signals_by_file.get(changed.path, [])
        signal_types = [signal.type for signal in signals]
        file_lines.append(
            {
                "path": changed.path,
                "change_type": changed.change_type,
                "added_lines": changed.added_lines,
                "deleted_lines": changed.deleted_lines,
                "risk_signals": signal_types,
            }
        )

    return (
        "你是代码变更增量裁决智能体，只输出 JSON。\n"
        f"原始请求:\n{original_request}\n\n"
        f"上下文策略: {context_plan.strategy}\n"
        f"变更文件:\n{json.dumps(file_lines, ensure_ascii=False)}\n"
    )
