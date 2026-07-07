from __future__ import annotations

from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[2] / "web_ui" / "src" / "web" / "templates" / "dashboard.html"


def test_dashboard_exposes_agent_guard_review_workspace():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "智能体告警" in html
    assert "switchToAgentSessions()" in html
    assert "loadAgentSessions()" in html
    assert "/api/agent-sessions" in html
    assert "执行回退" in html
    assert "执行 nono 回退" not in html
    assert "回退请求中..." in html
    assert "接受变更" in html
    assert "agentSessionActionInFlight" in html
    assert "urlParams.get('type') === 'agent'" in html
    assert "待人工处理" in html
    assert "已完成回退" in html
    assert "本次变更" in html
    assert "运行证据" in html
    assert "getAgentActionableCount()" in html
    assert "getAgentCompletedCount()" in html
    assert "getAgentChangedFiles(session).length" in html


def test_agent_guard_action_buttons_hide_after_decision_or_rollback_request():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert 'x-show="canActOnAgentSession(session)"' in html
    assert ':aria-disabled="!canActOnAgentSession(session) || agentSessionActionInFlight[session.run_id]"' in html
    assert ':disabled="!canActOnAgentSession(session) || agentSessionActionInFlight[session.run_id]"' not in html
    assert 'x-show="!canActOnAgentSession(session)"' in html
    assert "getAgentSessionTerminalStatus(session)" in html


def test_agent_guard_fallback_does_not_intercept_alpine_clicks():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert 'onclick="return window.handleAgentSessionAction(event, this)"' in html
    assert ':disabled="!canActOnAgentSession(session) || agentSessionActionInFlight[session.run_id]"' not in html
    assert "window.handleAgentSessionAction = async function(event, button)" in html
    assert "await fetch(`/api/agent-sessions/${encodeURIComponent(runId)}/${action}`" in html
    assert "}, true);" in html
