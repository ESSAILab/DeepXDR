from __future__ import annotations

import pytest

from ai_agent.agent_guard.config import AgentGuardConfig


def test_config_uses_safe_defaults_when_env_is_empty(monkeypatch):
    for name in (
        "AGENT_GUARD_ENABLED",
        "AGENT_GUARD_SMALL_DIFF_TOKEN_LIMIT",
        "AGENT_GUARD_MEDIUM_DIFF_TOKEN_LIMIT",
        "AGENT_GUARD_FILE_TOKEN_LIMIT",
        "AGENT_GUARD_HUNK_TOKEN_LIMIT",
        "AGENT_GUARD_MAX_FILE_SUMMARIES",
        "AGENT_GUARD_MAX_HIGH_RISK_SNIPPETS",
        "AGENT_GUARD_FORCE_REVIEW_ON_HUGE_DIFF",
    ):
        monkeypatch.delenv(name, raising=False)

    config = AgentGuardConfig.from_env()

    assert config.enabled is True
    assert config.small_diff_token_limit == 40_000
    assert config.medium_diff_token_limit == 300_000
    assert config.file_token_limit == 24_000
    assert config.hunk_token_limit == 6_000
    assert config.max_file_summaries == 80
    assert config.max_high_risk_snippets == 20
    assert config.force_review_on_huge_diff is True


def test_config_reads_thresholds_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_GUARD_ENABLED", "false")
    monkeypatch.setenv("AGENT_GUARD_SMALL_DIFF_TOKEN_LIMIT", "100")
    monkeypatch.setenv("AGENT_GUARD_MEDIUM_DIFF_TOKEN_LIMIT", "200")
    monkeypatch.setenv("AGENT_GUARD_FILE_TOKEN_LIMIT", "30")
    monkeypatch.setenv("AGENT_GUARD_HUNK_TOKEN_LIMIT", "10")
    monkeypatch.setenv("AGENT_GUARD_MAX_FILE_SUMMARIES", "7")
    monkeypatch.setenv("AGENT_GUARD_MAX_HIGH_RISK_SNIPPETS", "3")
    monkeypatch.setenv("AGENT_GUARD_FORCE_REVIEW_ON_HUGE_DIFF", "0")

    config = AgentGuardConfig.from_env()

    assert config.enabled is False
    assert config.small_diff_token_limit == 100
    assert config.medium_diff_token_limit == 200
    assert config.file_token_limit == 30
    assert config.hunk_token_limit == 10
    assert config.max_file_summaries == 7
    assert config.max_high_risk_snippets == 3
    assert config.force_review_on_huge_diff is False


def test_config_rejects_invalid_numeric_env(monkeypatch):
    monkeypatch.setenv("AGENT_GUARD_SMALL_DIFF_TOKEN_LIMIT", "not-a-number")

    with pytest.raises(ValueError, match="AGENT_GUARD_SMALL_DIFF_TOKEN_LIMIT"):
        AgentGuardConfig.from_env()
