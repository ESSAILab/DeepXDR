from __future__ import annotations

from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[2] / "web_ui" / "src" / "web" / "templates" / "dashboard.html"


def test_dashboard_exposes_agent_guard_review_workspace():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "<title>DeepXDR 安全运营平台</title>" in html
    assert '<div class="flex items-center">' in html
    assert '<h1 class="text-2xl font-bold text-gray-900">DeepXDR</h1>' in html
    assert '<span class="text-base leading-none text-gray-500">TTP分析</span>' not in html
    assert "TTP分析仪表盘" not in html
    assert "智能体告警" in html
    assert "智能体安全分析" in html
    assert "switchToAgentSessions()" in html
    assert "loadAgentSessions()" in html
    assert "getInitialAnalysisMode(type)" in html
    assert "persistAnalysisMode(mode)" in html
    assert "this.loadAgentSessions().then(() => this.startAgentSessionPolling())" in html
    assert "/api/agent-sessions" in html
    assert "执行回退" in html
    assert "执行 nono 回退" not in html
    assert "回退请求中..." in html
    assert "接受变更" in html
    assert "agentSessionActionInFlight" in html
    assert "type === 'agent'" in html
    assert "待人工处理" in html
    assert "已完成回退" in html
    assert "总告警数" in html
    assert "当前页总数" not in html
    assert "当前页可接受或回退" not in html
    assert "当前页 nono restore 完成" not in html
    assert "agentSessionPagination.total || 0" in html
    assert 'x-show="agentSessionPagination.pages > 1"' in html
    assert "agent-tab-active" in html
    assert "linear-gradient(135deg, #14b8a6 0%, #0ea5e9 100%)" in html
    assert 'x-show="analysisMode === \'network\'"' in html
    assert 'x-show="analysisMode === \'agent\'"' in html
    assert "本次变更" in html
    assert "运行证据" in html
    assert "getAgentActionableCount()" in html
    assert "getAgentCompletedCount()" in html
    assert "getAgentDispositionStatus(session)" in html
    assert "已回退" in html
    assert "xl:grid-cols-[1fr_150px]" in html
    assert "xl:flex-row" in html
    assert "getAgentSessionStatusLabel(session.status)" not in html
    assert "getAgentRollbackStatusLabel(session.rollback_status)" not in html
    assert "getAgentChangedFiles(session).length" in html


def test_dashboard_separates_network_and_agent_analysis_modes():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "网络安全分析" in html
    assert "智能体安全分析" in html
    assert "模式切换" in html
    assert "mode-switch" in html
    assert "mode-switch-menu" in html
    assert "analysisMode: 'network'" in html
    assert 'x-show="analysisMode === \'network\'"' in html
    assert 'x-show="analysisMode === \'agent\'"' in html
    assert '@click="switchToNetworkMode()"' in html
    assert '@click="switchToAgentMode()"' in html
    assert "getAnalysisModeLabel()" in html
    assert "async switchToNetworkMode()" in html
    assert "async switchToAgentMode()" in html
    assert "this.analysisMode = 'network'" in html
    assert "this.analysisMode = 'agent'" in html


def test_agent_guard_action_buttons_hide_after_decision_or_rollback_request():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert 'x-show="canActOnAgentSession(session)"' in html
    assert ':aria-disabled="!canActOnAgentSession(session) || agentSessionActionInFlight[session.run_id]"' in html
    assert ':disabled="!canActOnAgentSession(session) || agentSessionActionInFlight[session.run_id]"' not in html
    assert "getAgentDispositionStatus(session)" in html
    assert "待人工确认" in html
    assert "getAgentSessionTerminalStatus(session)" in html


def test_agent_guard_fallback_does_not_intercept_alpine_clicks():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert 'onclick="return window.handleAgentSessionAction(event, this)"' in html
    assert ':disabled="!canActOnAgentSession(session) || agentSessionActionInFlight[session.run_id]"' not in html
    assert "window.handleAgentSessionAction = async function(event, button)" in html
    assert "await fetch(`/api/agent-sessions/${encodeURIComponent(runId)}/${action}`" in html
    assert "}, true);" in html
