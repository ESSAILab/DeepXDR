# Agent Guard Incremental Adjudication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested first slice of DeepXDR agent-session incremental adjudication and resilient rollback orchestration.

**Architecture:** `nono-wrapper` publishes agent session events through `baseline_adjudication`, which normalizes them into `agent.session.finished`. `ai_agent.agent_guard` consumes normalized events, loads diff evidence by `diff_ref`, applies rule signals, plans context to avoid LLM window overflow, and produces structured adjudication and rollback request payloads.

**Tech Stack:** Python 3.11, pytest, stdlib dataclasses, Kafka payload contracts mocked in tests.

---

### Task 1: Agent Guard Core

**Files:**
- Create: `ai_agent/agent_guard/config.py`
- Create: `ai_agent/agent_guard/diff_store.py`
- Create: `ai_agent/agent_guard/diff_parser.py`
- Create: `ai_agent/agent_guard/rule_engine.py`
- Create: `ai_agent/agent_guard/context_planner.py`
- Create: `ai_agent/agent_guard/adjudicator.py`
- Create: `ai_agent/agent_guard/rollback.py`
- Test: `tests/agent_guard/test_config.py`
- Test: `tests/agent_guard/test_diff_store.py`
- Test: `tests/agent_guard/test_rule_engine.py`
- Test: `tests/agent_guard/test_context_planner.py`
- Test: `tests/agent_guard/test_adjudicator.py`
- Test: `tests/agent_guard/test_rollback.py`

- [ ] Write failing tests for environment thresholds, diff SHA256 verification, sensitive-path rules, context strategy selection, invalid LLM JSON fallback, and rollback request construction.
- [ ] Run each focused test and confirm it fails because the module does not exist.
- [ ] Implement minimal modules and dataclasses to pass the tests.
- [ ] Re-run all `tests/agent_guard` tests.

### Task 2: baseline_adjudication Agent Session Routing

**Files:**
- Modify: `baseline_adjudication/anomaly_detector.py`
- Test: `tests/baseline_adjudication/test_agent_session_routing.py`

- [ ] Write failing tests showing `type=agent_session,event_type=finished` bypasses Redis baseline logic and publishes to `agent.session.finished`.
- [ ] Run focused test and confirm the agent-session API is missing.
- [ ] Add a small routing branch and normalized payload builder.
- [ ] Re-run baseline routing tests.

### Task 3: System-Level Flow Tests

**Files:**
- Test: `tests/system/test_agent_guard_flow.py`

- [ ] Write tests for allow, warn, huge-diff human-review, diff evidence mismatch, and rollback-completed state payloads using mocked LLM and local diff files.
- [ ] Run focused system tests and confirm missing integration functions fail.
- [ ] Add minimal orchestration helpers in `ai_agent/agent_guard/service.py`.
- [ ] Re-run system tests.
