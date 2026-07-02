from __future__ import annotations

import hashlib

from ai_agent.agent_guard.config import AgentGuardConfig
from ai_agent.agent_guard.service import process_finished_session_event


class FakeLLM:
    def __init__(self, response: str):
        self.response = response

    def complete(self, _prompt: str) -> str:
        return self.response


def _write_diff(tmp_path, text):
    path = tmp_path / "run.diff"
    path.write_text(text, encoding="utf-8")
    return {
        "storage": "local",
        "uri": str(path),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "size_bytes": len(text.encode("utf-8")),
    }


def _event(diff_ref):
    return {
        "type": "agent_session",
        "event_type": "finished",
        "run_id": "run-1",
        "original_request": "修改 README 标题",
        "workspace": "/repo/app",
        "diff_ref": diff_ref,
        "nono": {"session_id": "nono-1", "verified": True},
    }


def test_process_finished_session_event_allows_low_risk_readme_change(tmp_path):
    diff_ref = _write_diff(
        tmp_path,
        "diff --git a/README.md b/README.md\n+++ b/README.md\n@@\n-Old\n+New\n",
    )
    llm = FakeLLM('{"verdict":"allow","risk_level":"low","out_of_intent":false,"summary":"README only","findings":[],"recommended_action":"accept","rollback_recommended":false}')

    result = process_finished_session_event(_event(diff_ref), config=AgentGuardConfig(), llm=llm)

    assert result.status == "adjudicated"
    assert result.adjudication.verdict == "allow"
    assert result.changed_files[0].path == "README.md"


def test_process_finished_session_event_warns_on_sensitive_workflow_change(tmp_path):
    diff_ref = _write_diff(
        tmp_path,
        "diff --git a/.github/workflows/deploy.yml b/.github/workflows/deploy.yml\n+++ b/.github/workflows/deploy.yml\n@@\n+ chmod 777 /tmp/build\n",
    )
    llm = FakeLLM('{"verdict":"warn","risk_level":"high","out_of_intent":true,"summary":"workflow changed","findings":[{"file":".github/workflows/deploy.yml"}],"recommended_action":"ask_user","rollback_recommended":true}')

    result = process_finished_session_event(_event(diff_ref), config=AgentGuardConfig(), llm=llm)

    assert result.status == "adjudicated"
    assert result.adjudication.verdict == "warn"
    assert result.risk_signals_by_file[".github/workflows/deploy.yml"][0].severity == "high"


def test_process_finished_session_event_marks_invalid_evidence_on_sha256_mismatch(tmp_path):
    path = tmp_path / "run.diff"
    path.write_text("diff --git a/.env b/.env\n+TOKEN=x\n", encoding="utf-8")
    bad_ref = {"storage": "local", "uri": str(path), "sha256": "0" * 64}

    result = process_finished_session_event(_event(bad_ref), config=AgentGuardConfig(), llm=FakeLLM("{}"))

    assert result.status == "evidence_invalid"
    assert result.adjudication is None


def test_process_finished_session_event_forces_review_for_huge_diff(tmp_path):
    diff_ref = _write_diff(
        tmp_path,
        "diff --git a/.env b/.env\n+++ b/.env\n@@\n+TOKEN=x\n",
    )
    config = AgentGuardConfig(small_diff_token_limit=1, medium_diff_token_limit=2, force_review_on_huge_diff=True)

    result = process_finished_session_event(_event(diff_ref), config=config, llm=FakeLLM("{}"))

    assert result.context_plan.strategy == "risk_only"
    assert result.context_plan.force_human_review is True
    assert result.adjudication.verdict == "needs_human_review"
