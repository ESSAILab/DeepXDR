from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .adjudicator import (
    AdjudicationResult,
    LLMClient,
    _load_json_response,
    _normalize_findings,
    _normalize_recommended_action,
    _normalize_risk_level,
    _normalize_verdict,
    adjudicate_session,
)
from .config import AgentGuardConfig
from .context_planner import ContextPlan, plan_context
from .diff_parser import ChangedFile, estimate_token_count, parse_unified_diff
from .rule_engine import RiskSignal, detect_risk_signals
from .service_types import AgentSessionProcessResult


class AgentAdjudicationState(TypedDict, total=False):
    event: dict[str, Any]
    diff_text: str
    config: AgentGuardConfig
    llm: LLMClient
    changed_files: list[ChangedFile]
    risk_signals_by_file: dict[str, list[RiskSignal]]
    context_plan: ContextPlan
    file_summaries: list[dict[str, Any]]
    adjudication: AdjudicationResult


def run_adjudication_graph(
    *,
    event: dict[str, Any],
    diff_text: str,
    config: AgentGuardConfig,
    llm: LLMClient,
) -> AgentSessionProcessResult:
    graph = create_adjudication_graph()
    state = graph.invoke({"event": event, "diff_text": diff_text, "config": config, "llm": llm})
    return AgentSessionProcessResult(
        status="adjudicated",
        changed_files=state["changed_files"],
        risk_signals_by_file=state["risk_signals_by_file"],
        context_plan=state["context_plan"],
        adjudication=state["adjudication"],
    )


def create_adjudication_graph():
    workflow = StateGraph(AgentAdjudicationState)
    workflow.add_node("prepare_context", _prepare_context)
    workflow.add_node("session_adjudication", _session_adjudication)
    workflow.add_node("summarize_files", _file_summaries)
    workflow.add_node("summary_adjudication", _summary_adjudication)

    workflow.add_edge(START, "prepare_context")
    workflow.add_conditional_edges(
        "prepare_context",
        _route_by_context_strategy,
        {
            "session_adjudication": "session_adjudication",
            "file_summaries": "summarize_files",
        },
    )
    workflow.add_edge("summarize_files", "summary_adjudication")
    workflow.add_edge("session_adjudication", END)
    workflow.add_edge("summary_adjudication", END)
    return workflow.compile()


def _prepare_context(state: AgentAdjudicationState) -> dict[str, Any]:
    diff_text = state["diff_text"]
    changed_files = parse_unified_diff(diff_text)
    risk_signals_by_file = {
        changed.path: detect_risk_signals(changed)
        for changed in changed_files
    }
    context_plan = plan_context(
        total_tokens=estimate_token_count(diff_text),
        files=changed_files,
        risk_signals_by_file=risk_signals_by_file,
        config=state["config"],
    )
    return {
        "changed_files": changed_files,
        "risk_signals_by_file": risk_signals_by_file,
        "context_plan": context_plan,
    }


def _route_by_context_strategy(state: AgentAdjudicationState) -> str:
    if state["context_plan"].strategy == "file_level":
        return "session_adjudication"
    return "file_summaries"


def _session_adjudication(state: AgentAdjudicationState) -> dict[str, Any]:
    adjudication = adjudicate_session(
        original_request=state["event"].get("original_request", ""),
        changed_files=state["changed_files"],
        context_plan=state["context_plan"],
        risk_signals_by_file=state["risk_signals_by_file"],
        llm=state["llm"],
    )
    return {"adjudication": adjudication}


def _file_summaries(state: AgentAdjudicationState) -> dict[str, Any]:
    config = state["config"]
    context_plan = state["context_plan"]
    if context_plan.strategy == "risk_only":
        max_chars = config.hunk_token_limit * 4
    else:
        max_chars = config.file_token_limit * 4

    summaries = [
        _summarize_changed_file(
            llm=state["llm"],
            original_request=state["event"].get("original_request", ""),
            changed=changed,
            risk_signals=state["risk_signals_by_file"].get(changed.path, []),
            max_chars=max_chars,
        )
        for changed in state["changed_files"][: config.max_file_summaries]
    ]
    return {"file_summaries": summaries}


def _summary_adjudication(state: AgentAdjudicationState) -> dict[str, Any]:
    prompt = (
        "你是代码变更增量裁决智能体，只输出 JSON。\n"
        "必须返回一个 JSON object，不要使用 Markdown 代码块，不要输出解释文字。\n"
        "字段: verdict, risk_level, out_of_intent, summary, findings, recommended_action, rollback_recommended。\n"
        "verdict 只能是 allow、warn、deny、needs_human_review。\n"
        "risk_level 只能是 low、medium、high、critical。\n"
        "recommended_action 只能是 accept、ask_user、rollback。\n"
        f"原始请求:\n{state['event'].get('original_request', '')}\n\n"
        f"上下文策略: {state['context_plan'].strategy}\n"
        f"文件变更摘要列表:\n{json.dumps(state.get('file_summaries', []), ensure_ascii=False)}\n"
    )
    try:
        payload = _load_json_response(state["llm"].complete(prompt))
        adjudication = _adjudication_from_payload(payload)
    except Exception as exc:
        adjudication = AdjudicationResult(
            verdict="needs_human_review",
            risk_level="medium",
            out_of_intent=None,
            summary=f"增量裁决模型输出不可解析: {exc}",
            recommended_action="ask_user",
            rollback_recommended=False,
        )
    return {"adjudication": adjudication}


def _summarize_changed_file(
    *,
    llm: LLMClient,
    original_request: str,
    changed: ChangedFile,
    risk_signals: list[RiskSignal],
    max_chars: int,
) -> dict[str, Any]:
    clipped_diff = _clip_text(changed.diff, max_chars)
    prompt = (
        "你是代码变更单文件分析智能体，只输出 JSON。\n"
        "任务: 生成单文件变更摘要。\n"
        "字段: path, summary, risk_level, findings。\n"
        f"原始请求:\n{original_request}\n\n"
        f"文件: {changed.path}\n"
        f"变更类型: {changed.change_type}\n"
        f"增删行: +{changed.added_lines} -{changed.deleted_lines}\n"
        f"规则风险:\n{json.dumps([signal.__dict__ for signal in risk_signals], ensure_ascii=False)}\n"
        f"diff:\n{clipped_diff}\n"
    )
    try:
        payload = _load_json_response(llm.complete(prompt))
    except Exception as exc:
        payload = {
            "path": changed.path,
            "summary": f"单文件摘要模型输出不可解析: {exc}",
            "risk_level": "medium",
            "findings": [],
        }
    return {
        "path": str(payload.get("path") or changed.path),
        "summary": str(payload.get("summary") or ""),
        "risk_level": _normalize_risk_level(payload.get("risk_level", "medium")),
        "findings": _normalize_findings(payload.get("findings", [])),
    }


def _clip_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return f"{text[:head]}\n[diff clipped]\n{text[-tail:]}"


def _adjudication_from_payload(payload: dict[str, Any]) -> AdjudicationResult:
    return AdjudicationResult(
        verdict=_normalize_verdict(payload["verdict"]),
        risk_level=_normalize_risk_level(payload["risk_level"]),
        out_of_intent=payload.get("out_of_intent"),
        summary=payload.get("summary", ""),
        findings=_normalize_findings(payload.get("findings", [])),
        recommended_action=_normalize_recommended_action(payload.get("recommended_action", "ask_user")),
        rollback_recommended=bool(payload.get("rollback_recommended", False)),
    )
