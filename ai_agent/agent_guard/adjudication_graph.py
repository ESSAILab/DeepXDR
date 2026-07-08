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
    _normalize_intent_alignment,
    _normalize_out_of_intent,
    _normalize_recommended_action,
    _normalize_risk_level,
    _normalize_verdict,
    _apply_risk_floor,
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
        "字段: verdict, risk_level, out_of_intent, intent_alignment, intent_alignment_reason, summary, findings, recommended_action, rollback_recommended。\n"
        "verdict 只能是 allow、warn、deny、needs_human_review。\n"
        "risk_level 只能是 low、medium、high、critical。\n"
        "intent_alignment 只能是 aligned、partially_aligned、out_of_intent、unknown，用于判断最终变更与原始请求是否一致。\n"
        "recommended_action 只能是 accept、ask_user、rollback。\n"
        "摘要必须明确说明变更与原始请求的意图一致性；若有不一致，必须说明超出范围的文件和原因。\n"
        "风险等级约束: 与请求一致且无规则风险才允许 low；partially_aligned、out_of_intent、unknown 最低 medium；超出请求且触发敏感路径或危险模式最低 high；超出请求且同时触发敏感路径和危险模式为 critical。\n"
        "除上述枚举字段必须使用指定英文取值外，summary、findings[].summary 等所有面向用户展示的文本必须使用简体中文。\n"
        f"原始请求:\n{state['event'].get('original_request', '')}\n\n"
        f"上下文策略: {state['context_plan'].strategy}\n"
        f"文件变更摘要列表:\n{json.dumps(state.get('file_summaries', []), ensure_ascii=False)}\n"
    )
    try:
        payload = _load_json_response(state["llm"].complete(prompt))
        adjudication = _adjudication_from_payload(payload, state["risk_signals_by_file"])
    except Exception as exc:
        adjudication = AdjudicationResult(
            verdict="needs_human_review",
            risk_level="medium",
            out_of_intent=None,
            summary=f"增量裁决模型输出不可解析: {exc}",
            recommended_action="ask_user",
            rollback_recommended=False,
            intent_alignment="unknown",
            intent_alignment_reason="模型输出不可解析，无法判断变更与原始请求的一致性。",
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
        "字段: path, summary, risk_level, intent_alignment, intent_alignment_reason, findings。\n"
        "risk_level 只能是 low、medium、high、critical；intent_alignment 只能是 aligned、partially_aligned、out_of_intent、unknown。\n"
        "summary 和 intent_alignment_reason 必须说明该文件变更与原始请求的意图一致性；summary、findings[].summary 等所有面向用户展示的文本必须使用简体中文。\n"
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
        "intent_alignment": _normalize_intent_alignment(payload.get("intent_alignment")),
        "intent_alignment_reason": str(payload.get("intent_alignment_reason") or ""),
        "findings": _normalize_findings(payload.get("findings", [])),
    }


def _clip_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return f"{text[:head]}\n[diff clipped]\n{text[-tail:]}"


def _adjudication_from_payload(
    payload: dict[str, Any],
    risk_signals_by_file: dict[str, list[RiskSignal]],
) -> AdjudicationResult:
    intent_alignment = _normalize_intent_alignment(payload.get("intent_alignment"), payload.get("out_of_intent"))
    return AdjudicationResult(
        verdict=_normalize_verdict(payload["verdict"]),
        risk_level=_apply_risk_floor(
            _normalize_risk_level(payload["risk_level"]),
            intent_alignment=intent_alignment,
            risk_signals_by_file=risk_signals_by_file,
        ),
        out_of_intent=_normalize_out_of_intent(payload.get("out_of_intent"), intent_alignment),
        summary=payload.get("summary", ""),
        findings=_normalize_findings(payload.get("findings", [])),
        recommended_action=_normalize_recommended_action(payload.get("recommended_action", "ask_user")),
        rollback_recommended=bool(payload.get("rollback_recommended", False)),
        intent_alignment=intent_alignment,
        intent_alignment_reason=str(payload.get("intent_alignment_reason") or ""),
    )
