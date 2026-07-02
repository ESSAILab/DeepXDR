from __future__ import annotations

from ai_agent.agent_guard.config import AgentGuardConfig
from ai_agent.agent_guard.context_planner import plan_context
from ai_agent.agent_guard.diff_parser import ChangedFile
from ai_agent.agent_guard.rule_engine import RiskSignal


def test_context_planner_uses_file_level_strategy_for_small_diff():
    config = AgentGuardConfig(small_diff_token_limit=100, medium_diff_token_limit=500)
    files = [ChangedFile(path="README.md", change_type="modified", added_lines=1, deleted_lines=0, diff="+ hi")]

    plan = plan_context(total_tokens=20, files=files, risk_signals_by_file={}, config=config)

    assert plan.strategy == "file_level"
    assert plan.force_human_review is False


def test_context_planner_uses_hunk_summary_for_medium_diff():
    config = AgentGuardConfig(small_diff_token_limit=100, medium_diff_token_limit=500)

    plan = plan_context(total_tokens=250, files=[], risk_signals_by_file={}, config=config)

    assert plan.strategy == "hunk_summary"
    assert plan.force_human_review is False


def test_context_planner_forces_review_for_huge_diff_when_configured():
    config = AgentGuardConfig(
        small_diff_token_limit=100,
        medium_diff_token_limit=500,
        force_review_on_huge_diff=True,
        max_high_risk_snippets=1,
    )
    high_risk = ChangedFile(path=".env", change_type="modified", added_lines=1, deleted_lines=0, diff="+TOKEN=secret")

    plan = plan_context(
        total_tokens=800,
        files=[high_risk],
        risk_signals_by_file={
            ".env": [RiskSignal(type="sensitive_path", severity="high", reason="secret file", path=".env")]
        },
        config=config,
    )

    assert plan.strategy == "risk_only"
    assert plan.force_human_review is True
    assert plan.high_risk_files == [".env"]
