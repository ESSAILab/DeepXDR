from __future__ import annotations

import hashlib

import pytest

from ai_agent.agent_guard.adjudication_graph import AnalysisCancellationToken, AnalysisCancelled
from ai_agent.agent_guard.config import AgentGuardConfig
from ai_agent.agent_guard.service import process_finished_session_event


class QueueLLM:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("LLM called more times than expected")
        return self.responses.pop(0)


class CancellingLLM(QueueLLM):
    def __init__(self, responses: list[str], token: AnalysisCancellationToken):
        super().__init__(responses)
        self.token = token

    def complete(self, prompt: str) -> str:
        response = super().complete(prompt)
        self.token.cancel()
        return response


class CancelOnCallLLM(QueueLLM):
    def __init__(self, responses: list[str], token: AnalysisCancellationToken, call_number: int):
        super().__init__(responses)
        self.token = token
        self.call_number = call_number

    def complete(self, prompt: str) -> str:
        response = super().complete(prompt)
        if len(self.prompts) == self.call_number:
            self.token.cancel()
        return response


def _event_for_diff(tmp_path, diff_text: str):
    path = tmp_path / "run.diff"
    path.write_text(diff_text, encoding="utf-8")
    return {
        "type": "agent_session",
        "event_type": "finished",
        "run_id": "run-1",
        "original_request": "modify files",
        "workspace": "/repo/app",
        "diff_ref": {
            "storage": "local",
            "uri": str(path),
            "sha256": hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
            "size_bytes": len(diff_text.encode("utf-8")),
        },
        "nono": {"session_id": "nono-1"},
    }


def test_small_diff_uses_one_session_level_langgraph_adjudication_with_full_diff(tmp_path):
    diff_text = "diff --git a/README.md b/README.md\n+++ b/README.md\n@@\n-old\n+new\n"
    llm = QueueLLM([
        '{"verdict":"allow","risk_level":"low","out_of_intent":false,"summary":"readme","findings":[],"recommended_action":"accept","rollback_recommended":false}'
    ])

    result = process_finished_session_event(
        _event_for_diff(tmp_path, diff_text),
        config=AgentGuardConfig(small_diff_token_limit=1000, medium_diff_token_limit=2000),
        llm=llm,
    )

    assert result.context_plan.strategy == "file_level"
    assert result.adjudication.verdict == "allow"
    assert len(llm.prompts) == 1
    assert "+new" in llm.prompts[0]


def test_medium_diff_summarizes_each_file_then_adjudicates_merged_summaries(tmp_path):
    diff_text = (
        "diff --git a/a.py b/a.py\n+++ b/a.py\n@@\n+print('a')\n"
        "diff --git a/b.py b/b.py\n+++ b/b.py\n@@\n+print('b')\n"
    )
    llm = QueueLLM([
        '{"path":"a.py","summary":"a changed","risk_level":"low","findings":[]}',
        '{"path":"b.py","summary":"b changed","risk_level":"low","findings":[]}',
        '{"verdict":"allow","risk_level":"low","out_of_intent":false,"summary":"two safe files","findings":[],"recommended_action":"accept","rollback_recommended":false}',
    ])

    result = process_finished_session_event(
        _event_for_diff(tmp_path, diff_text),
        config=AgentGuardConfig(small_diff_token_limit=1, medium_diff_token_limit=1000),
        llm=llm,
    )

    assert result.context_plan.strategy == "hunk_summary"
    assert result.adjudication.summary == "two safe files"
    assert len(llm.prompts) == 3
    assert "单文件变更摘要" in llm.prompts[0]
    assert "单文件变更摘要" in llm.prompts[1]
    assert "文件变更摘要列表" in llm.prompts[2]
    assert "intent_alignment" in llm.prompts[0]
    assert "intent_alignment_reason" in llm.prompts[0]
    assert "摘要必须明确说明变更与原始请求的意图一致性" in llm.prompts[2]
    assert "所有面向用户展示的文本必须使用简体中文" in llm.prompts[0]
    assert "所有面向用户展示的文本必须使用简体中文" in llm.prompts[1]
    assert "所有面向用户展示的文本必须使用简体中文" in llm.prompts[2]


def test_file_summary_cancellation_stops_before_next_llm_call(tmp_path):
    diff_text = (
        "diff --git a/a.py b/a.py\n+++ b/a.py\n@@\n+print('a')\n"
        "diff --git a/b.py b/b.py\n+++ b/b.py\n@@\n+print('b')\n"
    )
    token = AnalysisCancellationToken()
    llm = CancellingLLM(
        ['{"path":"a.py","summary":"a changed","risk_level":"low","findings":[]}'],
        token,
    )

    with pytest.raises(AnalysisCancelled):
        process_finished_session_event(
            _event_for_diff(tmp_path, diff_text),
            config=AgentGuardConfig(small_diff_token_limit=1, medium_diff_token_limit=1000),
            llm=llm,
            cancellation_token=token,
        )

    assert len(llm.prompts) == 1


def test_final_summary_cancellation_is_not_converted_to_fallback_result(tmp_path):
    diff_text = "diff --git a/a.py b/a.py\n+++ b/a.py\n@@\n+print('a')\n"
    token = AnalysisCancellationToken()
    llm = CancelOnCallLLM(
        [
            '{"path":"a.py","summary":"a changed","risk_level":"low","findings":[]}',
            '{"verdict":"allow","risk_level":"low","out_of_intent":false,'
            '"summary":"safe","findings":[],"recommended_action":"accept",'
            '"rollback_recommended":false}',
        ],
        token,
        call_number=2,
    )

    with pytest.raises(AnalysisCancelled):
        process_finished_session_event(
            _event_for_diff(tmp_path, diff_text),
            config=AgentGuardConfig(small_diff_token_limit=1, medium_diff_token_limit=1000),
            llm=llm,
            cancellation_token=token,
        )

    assert len(llm.prompts) == 2


def test_huge_diff_clips_file_diff_and_still_uses_llm_adjudication(tmp_path):
    long_payload = "A" * 5000
    diff_text = f"diff --git a/big.py b/big.py\n+++ b/big.py\n@@\n+{long_payload}\n"
    llm = QueueLLM([
        '{"path":"big.py","summary":"big file clipped","risk_level":"medium","findings":[]}',
        '{"verdict":"warn","risk_level":"medium","out_of_intent":false,"summary":"review big file","findings":[],"recommended_action":"ask_user","rollback_recommended":false}',
    ])

    result = process_finished_session_event(
        _event_for_diff(tmp_path, diff_text),
        config=AgentGuardConfig(
            small_diff_token_limit=1,
            medium_diff_token_limit=2,
            hunk_token_limit=20,
            force_review_on_huge_diff=False,
        ),
        llm=llm,
    )

    assert result.context_plan.strategy == "risk_only"
    assert result.context_plan.force_human_review is False
    assert result.adjudication.verdict == "warn"
    assert len(llm.prompts) == 2
    assert "[diff clipped]" in llm.prompts[0]
    assert long_payload not in llm.prompts[0]
    assert "所有面向用户展示的文本必须使用简体中文" in llm.prompts[0]
    assert "所有面向用户展示的文本必须使用简体中文" in llm.prompts[1]


def test_summary_adjudication_applies_intent_alignment_risk_floor(tmp_path):
    diff_text = "diff --git a/src/auth/token.py b/src/auth/token.py\n+++ b/src/auth/token.py\n@@\n+verify=false\n"
    llm = QueueLLM([
        '{"path":"src/auth/token.py","summary":"修改认证校验","risk_level":"low",'
        '"intent_alignment":"out_of_intent","intent_alignment_reason":"请求只要求改 README，但修改了认证校验。","findings":[]}',
        '{"verdict":"allow","risk_level":"low","out_of_intent":true,'
        '"intent_alignment":"out_of_intent","intent_alignment_reason":"请求只要求改 README，但修改了认证校验。",'
        '"summary":"本次变更超出原始请求。","findings":[],"recommended_action":"accept","rollback_recommended":false}',
    ])

    result = process_finished_session_event(
        {
            **_event_for_diff(tmp_path, diff_text),
            "original_request": "修改 README 标题",
        },
        config=AgentGuardConfig(small_diff_token_limit=1, medium_diff_token_limit=1000),
        llm=llm,
    )

    assert result.context_plan.strategy == "hunk_summary"
    assert result.adjudication.intent_alignment == "out_of_intent"
    assert result.adjudication.risk_level == "critical"
