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


@dataclass(frozen=True)
class AgentGuardConfig:
    enabled: bool = True
    small_diff_token_limit: int = 40_000
    medium_diff_token_limit: int = 300_000
    file_token_limit: int = 24_000
    hunk_token_limit: int = 6_000
    max_file_summaries: int = 80
    max_high_risk_snippets: int = 20
    force_review_on_huge_diff: bool = True

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
            force_review_on_huge_diff=_read_bool("AGENT_GUARD_FORCE_REVIEW_ON_HUGE_DIFF", True),
        )
