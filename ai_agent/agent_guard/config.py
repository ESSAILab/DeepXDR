from __future__ import annotations

import os
from dataclasses import dataclass


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _read_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip()


@dataclass(frozen=True)
class AgentGuardConfig:
    enabled: bool = True
    small_diff_token_limit: int = 40_000
    medium_diff_token_limit: int = 300_000
    file_token_limit: int = 24_000
    hunk_token_limit: int = 6_000
    max_file_summaries: int = 80
    max_high_risk_snippets: int = 20
    force_review_on_huge_diff: bool = False
    diff_storage: str = "local"
    diff_bucket: str = ""
    diff_prefix: str = "agent-diff-evidence"
    diff_endpoint_url: str = ""
    diff_access_key_id: str = ""
    diff_secret_access_key: str = ""
    diff_region: str = ""
    max_diff_read_bytes: int = 8 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "AgentGuardConfig":
        return cls(
            enabled=_read_bool("AGENT_GUARD_ENABLED", True),
            small_diff_token_limit=_read_int("AGENT_GUARD_SMALL_DIFF_TOKEN_LIMIT", 40_000),
            medium_diff_token_limit=_read_int("AGENT_GUARD_MEDIUM_DIFF_TOKEN_LIMIT", 300_000),
            file_token_limit=_read_int("AGENT_GUARD_FILE_TOKEN_LIMIT", 24_000),
            hunk_token_limit=_read_int("AGENT_GUARD_HUNK_TOKEN_LIMIT", 6_000),
            max_file_summaries=_read_int("AGENT_GUARD_MAX_FILE_SUMMARIES", 80),
            max_high_risk_snippets=_read_int("AGENT_GUARD_MAX_HIGH_RISK_SNIPPETS", 20),
            force_review_on_huge_diff=_read_bool("AGENT_GUARD_FORCE_REVIEW_ON_HUGE_DIFF", False),
            diff_storage=_read_str("AGENT_GUARD_DIFF_STORAGE", "local").lower(),
            diff_bucket=_read_str("AGENT_GUARD_DIFF_BUCKET"),
            diff_prefix=_read_str("AGENT_GUARD_DIFF_PREFIX", "agent-diff-evidence"),
            diff_endpoint_url=_read_str("AGENT_GUARD_DIFF_ENDPOINT_URL"),
            diff_access_key_id=_read_str("AGENT_GUARD_DIFF_ACCESS_KEY_ID"),
            diff_secret_access_key=_read_str("AGENT_GUARD_DIFF_SECRET_ACCESS_KEY"),
            diff_region=_read_str("AGENT_GUARD_DIFF_REGION"),
            max_diff_read_bytes=_read_int("AGENT_GUARD_MAX_DIFF_READ_BYTES", 8 * 1024 * 1024),
        )
