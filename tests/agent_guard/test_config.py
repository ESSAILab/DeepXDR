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
        "AGENT_GUARD_DIFF_STORAGE",
        "AGENT_GUARD_DIFF_BUCKET",
        "AGENT_GUARD_DIFF_PREFIX",
        "AGENT_GUARD_DIFF_ENDPOINT_URL",
        "AGENT_GUARD_DIFF_ACCESS_KEY_ID",
        "AGENT_GUARD_DIFF_SECRET_ACCESS_KEY",
        "AGENT_GUARD_DIFF_REGION",
        "AGENT_GUARD_MAX_DIFF_READ_BYTES",
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
    assert config.force_review_on_huge_diff is False
    assert config.diff_storage == "local"
    assert config.diff_bucket == ""
    assert config.diff_prefix == "agent-diff-evidence"
    assert config.max_diff_read_bytes == 8 * 1024 * 1024


def test_config_reads_thresholds_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_GUARD_ENABLED", "false")
    monkeypatch.setenv("AGENT_GUARD_SMALL_DIFF_TOKEN_LIMIT", "100")
    monkeypatch.setenv("AGENT_GUARD_MEDIUM_DIFF_TOKEN_LIMIT", "200")
    monkeypatch.setenv("AGENT_GUARD_FILE_TOKEN_LIMIT", "30")
    monkeypatch.setenv("AGENT_GUARD_HUNK_TOKEN_LIMIT", "10")
    monkeypatch.setenv("AGENT_GUARD_MAX_FILE_SUMMARIES", "7")
    monkeypatch.setenv("AGENT_GUARD_MAX_HIGH_RISK_SNIPPETS", "3")
    monkeypatch.setenv("AGENT_GUARD_FORCE_REVIEW_ON_HUGE_DIFF", "0")
    monkeypatch.setenv("AGENT_GUARD_DIFF_STORAGE", "minio")
    monkeypatch.setenv("AGENT_GUARD_DIFF_BUCKET", "agent-diffs")
    monkeypatch.setenv("AGENT_GUARD_DIFF_PREFIX", "prod")
    monkeypatch.setenv("AGENT_GUARD_DIFF_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("AGENT_GUARD_DIFF_ACCESS_KEY_ID", "minio")
    monkeypatch.setenv("AGENT_GUARD_DIFF_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AGENT_GUARD_DIFF_REGION", "us-east-1")
    monkeypatch.setenv("AGENT_GUARD_MAX_DIFF_READ_BYTES", "4096")

    config = AgentGuardConfig.from_env()

    assert config.enabled is False
    assert config.small_diff_token_limit == 100
    assert config.medium_diff_token_limit == 200
    assert config.file_token_limit == 30
    assert config.hunk_token_limit == 10
    assert config.max_file_summaries == 7
    assert config.max_high_risk_snippets == 3
    assert config.force_review_on_huge_diff is False
    assert config.diff_storage == "minio"
    assert config.diff_bucket == "agent-diffs"
    assert config.diff_prefix == "prod"
    assert config.diff_endpoint_url == "http://minio:9000"
    assert config.diff_access_key_id == "minio"
    assert config.diff_secret_access_key == "secret"
    assert config.diff_region == "us-east-1"
    assert config.max_diff_read_bytes == 4096


def test_config_rejects_invalid_numeric_env(monkeypatch):
    monkeypatch.setenv("AGENT_GUARD_SMALL_DIFF_TOKEN_LIMIT", "not-a-number")

    with pytest.raises(ValueError, match="AGENT_GUARD_SMALL_DIFF_TOKEN_LIMIT"):
        AgentGuardConfig.from_env()
