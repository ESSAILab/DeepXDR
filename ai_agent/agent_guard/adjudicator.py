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
        return AdjudicationResult(
            verdict=_normalize_verdict(payload["verdict"]),
            risk_level=_normalize_risk_level(payload["risk_level"]),
            out_of_intent=payload.get("out_of_intent"),
            summary=payload.get("summary", ""),
            findings=_normalize_findings(payload.get("findings", [])),
            recommended_action=_normalize_recommended_action(payload.get("recommended_action", "ask_user")),
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
        "字段: verdict, risk_level, out_of_intent, summary, findings, recommended_action, rollback_recommended。\n"
        "verdict 只能是 allow、warn、deny、needs_human_review。\n"
        "risk_level 只能是 low、medium、high、critical。\n"
        "recommended_action 只能是 accept、ask_user、rollback。\n"
        "findings 必须是对象数组，每个对象包含 summary 字段。\n"
        f"原始请求:\n{original_request}\n\n"
        f"上下文策略: {context_plan.strategy}\n"
        f"变更文件:\n{json.dumps(file_lines, ensure_ascii=False)}\n"
    )
