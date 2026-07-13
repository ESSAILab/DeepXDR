from __future__ import annotations

import subprocess
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[2] / "web_ui" / "src" / "web" / "templates" / "dashboard.html"
TAILWIND_CSS = Path(__file__).resolve().parents[2] / "web_ui" / "src" / "web" / "static" / "css" / "full-tailwind.css"


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
    assert ">删除告警<" not in html
    assert 'aria-label="删除告警"' in html
    assert 'title="删除告警"' in html
    assert "w-8 h-8" not in html
    assert "w-6 h-6" in html
    assert 'class="mt-1 flex items-center gap-2"' in html
    assert "flex-1 min-w-0 text-sm text-gray-700 truncate" in html
    assert "formatDate(session.updated_at || session.created_at)" in html
    assert "确认删除该智能体告警" in html
    assert "此操作只删除平台告警记录，不会回滚代码变更" in html
    assert "deleteAgentSession(session)" in html
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
    assert "变更风险分析" in html
    assert "大模型裁决" not in html
    assert "changed files" not in html
    assert "getAgentActionableCount()" in html
    assert "getAgentCompletedCount()" in html
    assert "getAgentDispositionStatus(session)" in html
    assert "已回退" in html
    assert "bg-yellow-100 text-yellow-800" in html
    assert "bg-gray-100 text-gray-700" in html
    assert "bg-sky-100 text-sky-800" not in html
    assert "getAgentVerdictLabel(getAgentAdjudication(session).verdict)" in html
    assert "getAgentRecommendedActionLabel(getAgentAdjudication(session).recommended_action)" in html
    assert "getAgentIntentAlignmentLabel(getAgentAdjudication(session).intent_alignment)" in html
    assert "getAgentIntentAlignmentClass(getAgentAdjudication(session).intent_alignment)" in html
    assert 'class="px-2 py-0.5 rounded-full text-xs font-medium border"' in html
    assert "bg-blue-50 text-blue-700 border-blue-200" in html
    assert "bg-purple-50 text-purple-700 border-purple-200" in html
    assert "bg-red-50 text-red-700 border-red-200" in html
    assert "bg-gray-50 text-gray-600 border-gray-200" in html
    assert "bg-orange-100 text-orange-800 border-orange-200" not in html
    assert "意图一致性" not in html
    assert "暂无意图一致性说明" not in html
    assert "getAgentChangeTypeLabel(file.change_type)" in html
    assert "getAgentRollbackError(session)" in html
    assert "回退失败原因" in html
    assert "changed_files_preview" in html
    assert "diff 预览已截断" in html
    assert "getAgentSessionSafeRecord(session)" in html
    assert "JSON.stringify(session, null, 2)" not in html
    assert "getAgentAdjudication(session).verdict || 'unknown'" not in html
    assert "getAgentAdjudication(session).recommended_action || 'ask_user'" not in html
    assert "xl:grid-cols-[1fr_150px]" in html
    assert "flex-nowrap" in html
    assert 'x-show="canActOnAgentSession(session)" class="flex items-center justify-end gap-1.5 flex-nowrap"' in html
    assert "getAgentSessionStatusLabel(session.status)" not in html
    assert "getAgentRollbackStatusLabel(session.rollback_status)" not in html
    assert "getAgentChangedFiles(session).length" in html
    assert "data-agent-action=\"delete\"" in html


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


def test_agent_intent_alignment_classes_exist_in_static_css():
    html = TEMPLATE.read_text(encoding="utf-8")
    css = TAILWIND_CSS.read_text(encoding="utf-8")

    expected_classes = [
        "bg-blue-50",
        "text-blue-700",
        "border-blue-200",
        "bg-purple-50",
        "text-purple-700",
        "border-purple-200",
        "bg-red-50",
        "text-red-700",
        "border-red-200",
        "bg-gray-50",
        "text-gray-600",
        "border-gray-200",
    ]
    for class_name in expected_classes:
        assert class_name in html
        assert f".{class_name}" in css


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
    assert "action === 'delete' ? 'DELETE' : 'POST'" in html
    assert "action === 'delete' ? `/api/agent-sessions/${encodeURIComponent(runId)}` : `/api/agent-sessions/${encodeURIComponent(runId)}/${action}`" in html
    assert "}, true);" in html


def test_agent_session_refresh_failure_preserves_last_successful_data():
    html = TEMPLATE.read_text(encoding="utf-8")
    method = html.split("async loadAgentSessions(", 1)[1].split("async changeAgentSessionPage", 1)[0]
    catch_block = method.split("} catch (error) {", 1)[1].split("} finally {", 1)[0]

    assert "this.agentSessions =" not in catch_block
    assert "this.agentSessionPagination =" not in catch_block
    for field in ("page", "size", "total", "pages"):
        assert f"this.agentSessionPagination.{field} =" not in catch_block


def test_agent_session_loader_uses_requested_page_before_successful_update():
    html = TEMPLATE.read_text(encoding="utf-8")
    method = html.split("async loadAgentSessions(", 1)[1].split("async changeAgentSessionPage", 1)[0]

    assert "page = this.agentSessionPagination.page) {" in method
    assert "params.append('page', page);" in method
    assert "params.append('page', this.agentSessionPagination.page);" not in method


def test_agent_session_page_change_passes_target_page_without_preassigning_it():
    html = TEMPLATE.read_text(encoding="utf-8")
    method = html.split("async changeAgentSessionPage(page) {", 1)[1].split("canActOnAgentSession", 1)[0]

    assert "this.agentSessionPagination.page = page;" not in method
    assert "await this.loadAgentSessions(page);" in method


def test_agent_session_loader_ignores_stale_success_and_failure():
    html = TEMPLATE.read_text(encoding="utf-8")
    method_start = html.index("async loadAgentSessions(")
    method_end = html.index("async changeAgentSessionPage", method_start)
    load_method = html[method_start:method_end]

    script = (
        """
const assert = (condition, message) => {
    if (!condition) throw new Error(message);
};
const requests = [];
global.fetch = (url) => new Promise((resolve, reject) => {
    requests.push({url, resolve, reject});
});
console.error = () => {};
const response = (body) => ({ok: true, json: async () => body});

(async () => {
    const component = {
        agentSessions: [{run_id: 'last-success'}],
        agentSessionsLoading: false,
        agentSessionRequestSequence: 0,
        agentSessionPagination: {page: 1, size: 20, total: 1, pages: 4},
"""
        + load_method
        + """
        noop() {}
    };

    const staleSuccess = component.loadAgentSessions(1);
    const latestSuccess = component.loadAgentSessions(2);
    requests[1].resolve(response({
        items: [{run_id: 'latest'}], page: 2, size: 20, total: 2, pages: 4
    }));
    await latestSuccess;
    requests[0].resolve(response({
        items: [{run_id: 'stale'}], page: 1, size: 20, total: 1, pages: 4
    }));
    await staleSuccess;

    assert(component.agentSessions[0].run_id === 'latest', 'stale success overwrote latest data');
    assert(component.agentSessionPagination.page === 2, 'stale success overwrote pagination');
    assert(component.agentSessionsLoading === false, 'latest success did not clear loading');

    const staleFailure = component.loadAgentSessions(3);
    const latestPending = component.loadAgentSessions(4);
    requests[2].reject(new Error('stale request failed'));
    await staleFailure;

    assert(component.agentSessions[0].run_id === 'latest', 'stale failure changed last success');
    assert(component.agentSessionPagination.page === 2, 'stale failure changed pagination');
    assert(component.agentSessionsLoading === true, 'stale failure cleared latest loading state');

    requests[3].resolve(response({
        items: [{run_id: 'newest'}], page: 4, size: 20, total: 3, pages: 4
    }));
    await latestPending;
    assert(component.agentSessions[0].run_id === 'newest', 'latest response was not applied');
    assert(component.agentSessionPagination.page === 4, 'latest pagination was not applied');
    assert(component.agentSessionsLoading === false, 'latest completion did not clear loading');
})().catch((error) => {
    console.log(error.stack || error.message);
    process.exitCode = 1;
});
"""
    )

    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "agentSessionRequestSequence: 0" in html


def test_agent_session_polling_does_not_supersede_manual_page_change():
    html = TEMPLATE.read_text(encoding="utf-8")
    polling_start = html.index("startAgentSessionPolling() {")
    polling_end = html.index("stopAgentSessionPolling() {", polling_start)
    polling_method = html[polling_start:polling_end]
    load_start = html.index("async loadAgentSessions(")
    load_end = html.index("async changeAgentSessionPage", load_start)
    load_method = html[load_start:load_end]

    script = (
        """
const assert = (condition, message) => {
    if (!condition) throw new Error(message);
};
const requests = [];
let poll = null;
global.setInterval = (callback) => {
    poll = callback;
    return 1;
};
global.fetch = (url) => new Promise((resolve, reject) => {
    requests.push({url, resolve, reject});
});
console.error = () => {};
const response = (body) => ({ok: true, json: async () => body});

(async () => {
    const component = {
        searchType: 'agent',
        agentSessionTimer: null,
        agentSessions: [{run_id: 'page-1'}],
        agentSessionsLoading: false,
        agentSessionRequestSequence: 0,
        agentSessionPagination: {page: 1, size: 20, total: 40, pages: 2},
        stopAgentSessionPolling() {},
"""
        + polling_method
        + load_method
        + """
        noop() {}
    };

    component.startAgentSessionPolling();
    const manualPage = component.loadAgentSessions(2);
    poll();

    assert(requests.length === 1, 'poll started a competing request during manual navigation');
    requests[0].resolve(response({
        items: [{run_id: 'page-2'}], page: 2, size: 20, total: 40, pages: 2
    }));
    await manualPage;

    assert(component.agentSessions[0].run_id === 'page-2', 'manual page data was not retained');
    assert(component.agentSessionPagination.page === 2, 'poll superseded manual page navigation');
})().catch((error) => {
    console.log(error.stack || error.message);
    process.exitCode = 1;
});
"""
    )

    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stdout + result.stderr
