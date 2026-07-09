from __future__ import annotations

import subprocess

from ai_agent.agent_guard.config import AgentGuardConfig
from ai_agent.agent_guard.context_planner import plan_context
from ai_agent.agent_guard.diff_parser import estimate_token_count, parse_unified_diff
from scripts.agentguard_smoke_cases import prepare_smoke_case
from scripts.agentguard_smoke_cases import original_request_for_case


SMOKE_CONFIG = AgentGuardConfig(
    small_diff_token_limit=200,
    medium_diff_token_limit=800,
    file_token_limit=300,
    hunk_token_limit=80,
)


def _git_diff(workspace):
    result = subprocess.run(
        ["git", "diff", "--no-index", "--", "before", "after"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert result.returncode in (0, 1)
    return result.stdout


def test_small_smoke_case_triggers_file_level_strategy(tmp_path):
    command = prepare_smoke_case("small", tmp_path)

    diff_text = _git_diff(tmp_path)
    changed_files = parse_unified_diff(diff_text)
    plan = plan_context(total_tokens=estimate_token_count(diff_text), files=changed_files, risk_signals_by_file={}, config=SMOKE_CONFIG)

    assert command == ["/bin/sh", "-c", "cp after/README.md README.md"]
    assert plan.strategy == "file_level"


def test_medium_smoke_case_triggers_hunk_summary_strategy(tmp_path):
    command = prepare_smoke_case("medium", tmp_path)

    diff_text = _git_diff(tmp_path)
    changed_files = parse_unified_diff(diff_text)
    plan = plan_context(total_tokens=estimate_token_count(diff_text), files=changed_files, risk_signals_by_file={}, config=SMOKE_CONFIG)

    assert command == ["/bin/sh", "-c", "cp after/service.py service.py && cp after/policy.yaml policy.yaml"]
    assert plan.strategy == "hunk_summary"
    assert len(changed_files) == 2


def test_large_smoke_case_triggers_risk_only_strategy(tmp_path):
    command = prepare_smoke_case("large", tmp_path)

    diff_text = _git_diff(tmp_path)
    changed_files = parse_unified_diff(diff_text)
    plan = plan_context(total_tokens=estimate_token_count(diff_text), files=changed_files, risk_signals_by_file={}, config=SMOKE_CONFIG)

    assert command == ["/bin/sh", "-c", "cp after/generated_policy.json generated_policy.json"]
    assert plan.strategy == "risk_only"


def test_agent_smoke_case_runs_real_opencode_agent(tmp_path):
    command = prepare_smoke_case("agent", tmp_path)

    assert command == [
        "opencode",
        "run",
        "--model",
        "deepxdr/deepseek-v3-2-251201",
        "--auto",
        original_request_for_case("agent"),
    ]
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# Smoke target\n\nThis file is intentionally incomplete.\n"
    assert (tmp_path / "opencode.json").exists()
