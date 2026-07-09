from __future__ import annotations

from ai_agent.agent_guard.adjudicator import adjudicate_session
from ai_agent.agent_guard.context_planner import ContextPlan
from ai_agent.agent_guard.diff_parser import ChangedFile
from ai_agent.agent_guard.rule_engine import RiskSignal


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def test_adjudicator_returns_needs_human_review_when_llm_returns_invalid_json():
    llm = FakeLLM("not json")

    result = adjudicate_session(
        original_request="修改 README 标题",
        changed_files=[ChangedFile(path="README.md", change_type="modified", added_lines=1, deleted_lines=0, diff="+ title")],
        context_plan=ContextPlan(strategy="file_level"),
        risk_signals_by_file={},
        llm=llm,
    )

    assert result.verdict == "needs_human_review"
    assert result.risk_level == "medium"
    assert result.out_of_intent is None


def test_adjudicator_accepts_markdown_fenced_json_response():
    llm = FakeLLM(
        '```json\n'
        '{"verdict":"allow","risk_level":"low","out_of_intent":false,'
        '"summary":"ok","findings":[],"recommended_action":"accept",'
        '"rollback_recommended":false}\n'
        '```'
    )

    result = adjudicate_session(
        original_request="修改 README 标题",
        changed_files=[ChangedFile(path="README.md", change_type="modified", added_lines=1, deleted_lines=0, diff="+ title")],
        context_plan=ContextPlan(strategy="file_level"),
        risk_signals_by_file={},
        llm=llm,
    )

    assert result.verdict == "allow"
    assert result.recommended_action == "accept"


def test_adjudicator_normalizes_common_model_synonyms_and_findings():
    llm = FakeLLM(
        '{"verdict":"approved","risk_level":"低","out_of_intent":false,'
        '"summary":"ok","findings":["仅修改 README"],'
        '"recommended_action":"无需额外操作。","rollback_recommended":false}'
    )

    result = adjudicate_session(
        original_request="修改 README 标题",
        changed_files=[ChangedFile(path="README.md", change_type="modified", added_lines=1, deleted_lines=0, diff="+ title")],
        context_plan=ContextPlan(strategy="file_level"),
        risk_signals_by_file={},
        llm=llm,
    )

    assert result.verdict == "allow"
    assert result.risk_level == "low"
    assert result.recommended_action == "accept"
    assert result.findings == [{"summary": "仅修改 README"}]


def test_adjudicator_includes_request_files_and_strategy_in_prompt():
    llm = FakeLLM('{"verdict":"allow","risk_level":"low","out_of_intent":false,"summary":"ok","findings":[],"recommended_action":"accept","rollback_recommended":false}')

    adjudicate_session(
        original_request="修复 token 过期问题",
        changed_files=[ChangedFile(path="src/auth/token.py", change_type="modified", added_lines=2, deleted_lines=1, diff="+ fix")],
        context_plan=ContextPlan(strategy="file_level"),
        risk_signals_by_file={},
        llm=llm,
    )

    prompt = llm.prompts[0]
    assert "修复 token 过期问题" in prompt
    assert "src/auth/token.py" in prompt
    assert "file_level" in prompt
    assert "所有面向用户展示的文本必须使用简体中文" in prompt
    assert "intent_alignment" in prompt
    assert "摘要必须明确说明变更与原始请求的意图一致性" in prompt


def test_adjudicator_returns_intent_alignment_fields():
    llm = FakeLLM(
        '{"verdict":"allow","risk_level":"low","out_of_intent":false,'
        '"intent_alignment":"aligned","intent_alignment_reason":"仅修改 README 标题，与原始请求一致。",'
        '"summary":"本次变更与原始请求一致。","findings":[],"recommended_action":"accept","rollback_recommended":false}'
    )

    result = adjudicate_session(
        original_request="修改 README 标题",
        changed_files=[ChangedFile(path="README.md", change_type="modified", added_lines=1, deleted_lines=0, diff="+ title")],
        context_plan=ContextPlan(strategy="file_level"),
        risk_signals_by_file={},
        llm=llm,
    )

    assert result.intent_alignment == "aligned"
    assert result.intent_alignment_reason == "仅修改 README 标题，与原始请求一致。"
    assert result.risk_level == "low"


def test_adjudicator_raises_out_of_intent_low_risk_to_medium():
    llm = FakeLLM(
        '{"verdict":"allow","risk_level":"low","out_of_intent":true,'
        '"intent_alignment":"out_of_intent","intent_alignment_reason":"请求只要求改 README，但变更修改了部署脚本。",'
        '"summary":"本次变更超出原始请求。","findings":[],"recommended_action":"accept","rollback_recommended":false}'
    )

    result = adjudicate_session(
        original_request="修改 README 标题",
        changed_files=[ChangedFile(path="deploy/start.sh", change_type="modified", added_lines=1, deleted_lines=0, diff="+ echo ok")],
        context_plan=ContextPlan(strategy="file_level"),
        risk_signals_by_file={},
        llm=llm,
    )

    assert result.intent_alignment == "out_of_intent"
    assert result.out_of_intent is True
    assert result.risk_level == "medium"


def test_adjudicator_raises_out_of_intent_sensitive_change_to_high():
    llm = FakeLLM(
        '{"verdict":"allow","risk_level":"low","out_of_intent":true,'
        '"intent_alignment":"out_of_intent","intent_alignment_reason":"请求只要求改 README，但变更修改了认证代码。",'
        '"summary":"本次变更超出原始请求并修改敏感路径。","findings":[],"recommended_action":"accept","rollback_recommended":false}'
    )
    changed = ChangedFile(path="src/auth/token.py", change_type="modified", added_lines=1, deleted_lines=0, diff="+ bypass")

    result = adjudicate_session(
        original_request="修改 README 标题",
        changed_files=[changed],
        context_plan=ContextPlan(strategy="file_level"),
        risk_signals_by_file={
            changed.path: [RiskSignal(type="sensitive_path", severity="high", reason="sensitive path", path=changed.path)]
        },
        llm=llm,
    )

    assert result.risk_level == "high"


def test_adjudicator_raises_out_of_intent_sensitive_and_dangerous_change_to_critical():
    llm = FakeLLM(
        '{"verdict":"warn","risk_level":"medium","out_of_intent":true,'
        '"intent_alignment":"out_of_intent","intent_alignment_reason":"请求只要求改 README，但变更关闭认证校验。",'
        '"summary":"本次变更超出原始请求并包含危险模式。","findings":[],"recommended_action":"ask_user","rollback_recommended":false}'
    )
    changed = ChangedFile(path="src/auth/token.py", change_type="modified", added_lines=1, deleted_lines=0, diff="+ verify=false")

    result = adjudicate_session(
        original_request="修改 README 标题",
        changed_files=[changed],
        context_plan=ContextPlan(strategy="file_level"),
        risk_signals_by_file={
            changed.path: [
                RiskSignal(type="sensitive_path", severity="high", reason="sensitive path", path=changed.path),
                RiskSignal(type="dangerous_pattern", severity="high", reason="dangerous pattern", path=changed.path),
            ]
        },
        llm=llm,
    )

    assert result.risk_level == "critical"
