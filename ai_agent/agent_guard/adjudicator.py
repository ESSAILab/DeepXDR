from __future__ import annotations

import json
import re
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
    intent_alignment: str = "unknown"
    intent_alignment_reason: str = ""


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
        raw_response = llm.complete(prompt)
        payload = _load_json_response(raw_response)
        intent_alignment = _normalize_intent_alignment(payload.get("intent_alignment"), payload.get("out_of_intent"))
        risk_level = _apply_risk_floor(
            _normalize_risk_level(payload["risk_level"]),
            intent_alignment=intent_alignment,
            risk_signals_by_file=risk_signals_by_file,
        )
        return AdjudicationResult(
            verdict=_normalize_verdict(payload["verdict"]),
            risk_level=risk_level,
            out_of_intent=_normalize_out_of_intent(payload.get("out_of_intent"), intent_alignment),
            summary=payload.get("summary", ""),
            findings=_normalize_findings(payload.get("findings", [])),
            recommended_action=_normalize_recommended_action(payload.get("recommended_action", "ask_user")),
            rollback_recommended=bool(payload.get("rollback_recommended", False)),
            intent_alignment=intent_alignment,
            intent_alignment_reason=str(payload.get("intent_alignment_reason") or ""),
        )
    except Exception as exc:
        return AdjudicationResult(
            verdict="needs_human_review",
            risk_level="medium",
            out_of_intent=None,
            summary=f"增量裁决模型输出不可解析: {exc}",
            recommended_action="ask_user",
            rollback_recommended=False,
            intent_alignment="unknown",
            intent_alignment_reason="模型输出不可解析，无法判断变更与原始请求的一致性。",
        )


def _load_json_response(raw_response: str) -> dict[str, Any]:
    text = raw_response.strip()
    if not text:
        raise ValueError("empty model response")

    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise
        payload = json.loads(text[start : end + 1])

    if not isinstance(payload, dict):
        raise ValueError("model response JSON must be an object")
    return payload


def _normalize_verdict(value: Any) -> str:
    text = str(value).strip().lower()
    aliases = {
        "approved": "allow",
        "approve": "allow",
        "accept": "allow",
        "pass": "allow",
        "safe": "allow",
        "通过": "allow",
        "批准": "allow",
        "同意": "allow",
        "warning": "warn",
        "review": "warn",
        "needs_review": "warn",
        "需要审核": "warn",
        "reject": "deny",
        "rejected": "deny",
        "block": "deny",
        "blocked": "deny",
        "拒绝": "deny",
    }
    return aliases.get(text, text if text in {"allow", "warn", "deny", "needs_human_review"} else "needs_human_review")


def _normalize_risk_level(value: Any) -> str:
    text = str(value).strip().lower()
    aliases = {
        "低": "low",
        "低风险": "low",
        "中": "medium",
        "中风险": "medium",
        "高": "high",
        "高风险": "high",
        "严重": "critical",
        "严重风险": "critical",
    }
    return aliases.get(text, text if text in {"low", "medium", "high", "critical"} else "medium")


def _normalize_recommended_action(value: Any) -> str:
    text = str(value).strip().lower()
    aliases = {
        "approve": "accept",
        "approved": "accept",
        "allow": "accept",
        "pass": "accept",
        "无需额外操作。": "accept",
        "无需额外操作": "accept",
        "接受": "accept",
        "通过": "accept",
        "review": "ask_user",
        "needs_review": "ask_user",
        "human_review": "ask_user",
        "人工确认": "ask_user",
        "rollback": "rollback",
        "revert": "rollback",
        "回退": "rollback",
    }
    return aliases.get(text, text if text in {"accept", "ask_user", "rollback"} else "ask_user")


def _normalize_intent_alignment(value: Any, out_of_intent: Any = None) -> str:
    text = str(value).strip().lower()
    aliases = {
        "一致": "aligned",
        "意图一致": "aligned",
        "符合": "aligned",
        "部分一致": "partially_aligned",
        "部分超出": "partially_aligned",
        "部分符合": "partially_aligned",
        "超出": "out_of_intent",
        "超出意图": "out_of_intent",
        "不一致": "out_of_intent",
        "无法判断": "unknown",
        "未知": "unknown",
    }
    normalized = aliases.get(text, text if text in {"aligned", "partially_aligned", "out_of_intent", "unknown"} else "")
    if normalized:
        return normalized
    if out_of_intent is True:
        return "out_of_intent"
    if out_of_intent is False:
        return "aligned"
    return "unknown"


def _normalize_out_of_intent(value: Any, intent_alignment: str) -> bool | None:
    if intent_alignment == "out_of_intent":
        return True
    if value is True:
        return True
    if value is False:
        return False
    if intent_alignment == "aligned":
        return False
    return None


def _apply_risk_floor(
    risk_level: str,
    *,
    intent_alignment: str,
    risk_signals_by_file: dict[str, list[RiskSignal]],
) -> str:
    floor = "low"
    signal_types = {
        signal.type
        for signals in risk_signals_by_file.values()
        for signal in signals
        if signal.severity == "high"
    }
    has_sensitive_path = "sensitive_path" in signal_types
    has_dangerous_pattern = "dangerous_pattern" in signal_types
    has_rule_risk = bool(signal_types)

    if intent_alignment in {"partially_aligned", "out_of_intent", "unknown"}:
        floor = "medium"
    if has_rule_risk:
        floor = _max_risk(floor, "medium")
    if intent_alignment in {"partially_aligned", "out_of_intent"} and (has_sensitive_path or has_dangerous_pattern):
        floor = _max_risk(floor, "high")
    if intent_alignment == "out_of_intent" and has_sensitive_path and has_dangerous_pattern:
        floor = "critical"
    return _max_risk(risk_level, floor)


def _max_risk(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return left if order[left] >= order[right] else right


def _normalize_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [{"summary": str(value)}] if value else []

    findings = []
    for item in value:
        if isinstance(item, dict):
            findings.append(item)
        elif item:
            findings.append({"summary": str(item)})
    return findings


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
                **({"diff": changed.diff} if context_plan.strategy == "file_level" else {}),
            }
        )

    return (
        "你是代码变更增量裁决智能体，只输出 JSON。\n"
        "必须返回一个 JSON object，不要使用 Markdown 代码块，不要输出解释文字。\n"
        "字段: verdict, risk_level, out_of_intent, intent_alignment, intent_alignment_reason, summary, findings, recommended_action, rollback_recommended。\n"
        "verdict 只能是 allow、warn、deny、needs_human_review。\n"
        "risk_level 只能是 low、medium、high、critical。\n"
        "intent_alignment 只能是 aligned、partially_aligned、out_of_intent、unknown，用于判断最终变更与原始请求是否一致。\n"
        "recommended_action 只能是 accept、ask_user、rollback。\n"
        "findings 必须是对象数组，每个对象包含 summary 字段。\n"
        "摘要必须明确说明变更与原始请求的意图一致性；若有不一致，必须说明超出范围的文件和原因。\n"
        "风险等级约束: 与请求一致且无规则风险才允许 low；partially_aligned、out_of_intent、unknown 最低 medium；超出请求且触发敏感路径或危险模式最低 high；超出请求且同时触发敏感路径和危险模式为 critical。\n"
        "除上述枚举字段必须使用指定英文取值外，summary、findings[].summary 等所有面向用户展示的文本必须使用简体中文。\n"
        f"原始请求:\n{original_request}\n\n"
        f"上下文策略: {context_plan.strategy}\n"
        f"变更文件:\n{json.dumps(file_lines, ensure_ascii=False)}\n"
    )
