from __future__ import annotations

from ai_agent.agent_guard.adjudicator import adjudicate_session
from ai_agent.agent_guard.context_planner import ContextPlan
from ai_agent.agent_guard.diff_parser import ChangedFile


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
