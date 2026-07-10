# AI Agent Core Rewrite Route B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the high-risk `ai_agent` Short TTP pipeline and MITRE investigation core behind feature flags while reusing existing event models, repositories, API surface, defense integration, and Long TTP consumers, then complete the transition so `mitre_attck_agent/` is no longer needed.

**Architecture:** Build a new parallel implementation under clear package boundaries, then switch traffic through configuration after behavior parity is proven. The old implementation remains available until the new windowing, Short TTP pipeline, MITRE converter, and investigation graph have tests and production-safe rollback. After parity is proven, move the remaining MITRE RAG, reporting, schemas, and workflow compatibility code into `ttp_investigation/` and remove the legacy `mitre_attck_agent/` package.

**Tech Stack:** Python 3.11+, asyncio, LangGraph 0.5.4, Pydantic, pytest, pytest-asyncio, existing Elasticsearch repositories, existing Kafka consumer parsing.

---

## Scope

This plan intentionally does not rewrite the whole `ai_agent` project. It rewrites the core path:

```text
Kafka SecurityEvent -> windowing -> Short TTP generation -> MITRE investigation -> TTP conversion
```

The following remain reused initially:

- `ai_agent/shared/models/events.py`
- `ai_agent/shared/models/ttp.py`
- `ai_agent/shared/database/*`
- `ai_agent/data_consumer/kafka_consumer.py` parsing and DLQ behavior
- `ai_agent/api_server/*` response models and route shape
- `ai_agent/defense/*`
- `ai_agent/ttp_generator/dx_analyzer_api.py` Long TTP trigger APIs
- `ai_agent/mitre_attck_agent/*` MITRE RAG, reporting, schemas, and workflow code only during the compatibility phase

Long TTP code moves to explicit package boundaries while old imports remain as compatibility wrappers:

- `ai_agent/ttp_generator/dx_analyzer*` analyzer internals -> `ai_agent/long_ttp/analyzer/`
- `ai_agent/ttp_generator/dx_analyzer_api.py` trigger API -> `ai_agent/long_ttp/api.py`
- `ai_agent/ttp_generator/dx_analyzer*` feedback/session behavior -> `ai_agent/long_ttp/feedback/session.py`

## Target File Structure

Create these new packages:

```text
ai_agent/short_ttp/
  __init__.py
  config.py
  windowing/
    __init__.py
    models.py
    policy.py
    manager.py
  pipeline/
    __init__.py
    filters.py
    grouping.py
    processor.py
  workflow/
    __init__.py
    analyzer.py

ai_agent/ttp_investigation/
  __init__.py
  attack_rag.py
  converters.py
  schemas.py
  investigation/
    __init__.py
    config.py
    graph.py
    nodes.py
    run_workflow.py
    state.py
    services.py
  reporting/
    __init__.py
    report_agent.py

ai_agent/long_ttp/
  __init__.py
  api.py
  analyzer/
    __init__.py
    deep_researcher.py
  feedback/
    __init__.py
    session.py
    templates.py
```

Add tests under:

```text
ai_agent/tests/short_ttp/
ai_agent/tests/ttp_investigation/
ai_agent/tests/long_ttp/
ai_agent/tests/integration/
```

Final top-level package direction after the transition:

```text
ai_agent/
  api_server/
  data/
  data_consumer/
  defense/
  long_ttp/
  ttp_investigation/
  shared/
  short_ttp/
  tests/
  ttp_generator/
```

`mitre_attck_agent/` is a migration source, not a final package. `ttp_generator/` remains only as a legacy compatibility surface during rollout.

## Feature Flags

Add these environment variables in `shared/utils/config.py`:

- `USE_NEW_SHORT_TTP_PIPELINE=false`
- `USE_NEW_MITRE_INVESTIGATION=false`
- `SHORT_TTP_EVENT_GAP_SECONDS=1.0`
- `SHORT_TTP_IDLE_CLOSE_SECONDS=2.0`
- `SHORT_TTP_MAX_EVENTS_PER_WINDOW=1000`
- `SHORT_TTP_MAX_WINDOW_AGE_SECONDS=30.0`
- `SHORT_TTP_MAX_WINDOW_DURATION_SECONDS=5.0`
- `SHORT_TTP_ALLOWED_LATENESS_SECONDS=3.0`

The old env var `SHORT_TTP_WINDOW_INTERVAL` remains temporarily as a backward-compatible fallback. New code must prefer the new variables.

Windowing semantics must be explicit in the new pipeline:

- [ ] Treat Falco `time`, Suricata `timestamp`, and OpenRASP `event_time` as the canonical event occurrence time for Short TTP windowing.
- [ ] Treat ingestion/index times such as `@timestamp` only as delivery latency evidence, not as the primary behavior timestamp.
- [ ] Use `SHORT_TTP_MAX_WINDOW_DURATION_SECONDS` as the maximum event-time span of a single Short TTP window.
- [ ] Use `SHORT_TTP_ALLOWED_LATENESS_SECONDS` to delay closing windows so slightly late Falco/Suricata events can still join the correct event-time window.
- [ ] Use a watermark-based close rule (`max_seen_event_time - allowed_lateness`) instead of closing windows solely from wall-clock `now - last_event_time`.
- [ ] Make `SHORT_TTP_MAX_EVENTS_PER_WINDOW` a hard window acceptance limit.
- [ ] Keep `SHORT_TTP_WINDOW_INTERVAL` only as a legacy fallback; do not let it obscure the new duration/gap/lateness semantics.

---

## Task 1: Add Package Skeleton and Runtime Flags

**Files:**
- Create: `ai_agent/short_ttp/__init__.py`
- Create: `ai_agent/short_ttp/config.py`
- Create: `ai_agent/short_ttp/windowing/__init__.py`
- Create: `ai_agent/short_ttp/pipeline/__init__.py`
- Create: `ai_agent/short_ttp/workflow/__init__.py`
- Create: `ai_agent/ttp_investigation/__init__.py`
- Create: `ai_agent/ttp_investigation/investigation/__init__.py`
- Modify: `ai_agent/shared/utils/config.py`
- Test: `ai_agent/tests/short_ttp/test_config.py`

- [ ] Step 1: Create empty package files for `short_ttp` and `ttp_investigation`.

- [ ] Step 2: Add `ShortTTPRuntimeConfig` to `ai_agent/short_ttp/config.py`.

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ShortTTPRuntimeConfig:
    use_new_pipeline: bool
    event_gap_seconds: float
    idle_close_seconds: float
    max_events_per_window: int
    max_window_age_seconds: float
    max_window_duration_seconds: float
    allowed_lateness_seconds: float


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_env(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _int_env(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def load_short_ttp_runtime_config() -> ShortTTPRuntimeConfig:
    legacy_interval = _float_env("SHORT_TTP_WINDOW_INTERVAL", 1.0, 0.1)
    return ShortTTPRuntimeConfig(
        use_new_pipeline=_bool_env("USE_NEW_SHORT_TTP_PIPELINE", False),
        event_gap_seconds=_float_env("SHORT_TTP_EVENT_GAP_SECONDS", legacy_interval, 0.1),
        idle_close_seconds=_float_env("SHORT_TTP_IDLE_CLOSE_SECONDS", max(legacy_interval, 2.0), 0.1),
        max_events_per_window=_int_env("SHORT_TTP_MAX_EVENTS_PER_WINDOW", 1000, 1),
        max_window_age_seconds=_float_env("SHORT_TTP_MAX_WINDOW_AGE_SECONDS", 30.0, 0.1),
        max_window_duration_seconds=_float_env("SHORT_TTP_MAX_WINDOW_DURATION_SECONDS", 5.0, 0.1),
        allowed_lateness_seconds=_float_env("SHORT_TTP_ALLOWED_LATENESS_SECONDS", 3.0, 0.0),
    )
```

- [ ] Step 3: Add tests for defaults, legacy fallback, invalid values, and new env precedence.

- [ ] Step 4: Run `cd ai_agent && pytest tests/short_ttp/test_config.py -v`.

- [ ] Step 5: Commit with `git commit -m "chore: add route b package skeleton and short ttp config"`.

## Task 2: Build New Windowing Policy and Window Model

**Files:**
- Create: `ai_agent/short_ttp/windowing/policy.py`
- Create: `ai_agent/short_ttp/windowing/models.py`
- Test: `ai_agent/tests/short_ttp/test_window_policy.py`

- [ ] Step 1: Implement `WindowPolicy`.

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowPolicy:
    event_gap_seconds: float
    idle_close_seconds: float
    max_events_per_window: int
    max_window_age_seconds: float
    max_window_duration_seconds: float
    allowed_lateness_seconds: float

    def __post_init__(self) -> None:
        if self.event_gap_seconds <= 0:
            raise ValueError("event_gap_seconds must be positive")
        if self.idle_close_seconds <= 0:
            raise ValueError("idle_close_seconds must be positive")
        if self.max_events_per_window < 1:
            raise ValueError("max_events_per_window must be at least 1")
        if self.max_window_age_seconds <= 0:
            raise ValueError("max_window_age_seconds must be positive")
        if self.max_window_duration_seconds <= 0:
            raise ValueError("max_window_duration_seconds must be positive")
        if self.allowed_lateness_seconds < 0:
            raise ValueError("allowed_lateness_seconds must be non-negative")
```

- [ ] Step 2: Implement `ShortTTPWindow` with explicit states: `active`, `ready`, `processing`, `processed`, `failed`.

- [ ] Step 3: Add tests for accepting events inside the gap, rejecting events outside the gap, closing by idle timeout, closing by event count, closing by max age, and rejecting events that would exceed `max_window_duration_seconds`.

- [ ] Step 3a: Add tests proving the observed example behavior: Suricata `01:06:42.969` and Falco `time=01:06:43.015` share one window even if Falco delivery `@timestamp` is later; Falco command events from `01:06:50.200` through `01:06:53.302` share one 5-second window.

- [ ] Step 4: Run `cd ai_agent && pytest tests/short_ttp/test_window_policy.py -v`.

- [ ] Step 5: Commit with `git commit -m "feat: add short ttp window policy model"`.

## Task 3: Replace Shared List Buffer With Queue-Based Window Manager

**Files:**
- Create: `ai_agent/short_ttp/windowing/manager.py`
- Test: `ai_agent/tests/short_ttp/test_window_manager.py`

- [ ] Step 1: Implement `ShortTTPWindowManager` using `asyncio.Queue[SecurityEvent]` for ingestion.

- [ ] Step 2: Add a `drain_once()` method that processes a bounded number of queued events without clearing events added during processing.

- [ ] Step 3: Add `get_ready_windows(limit: int)` and `mark_processed(window_id: str)` methods.

- [ ] Step 4: Track `max_seen_event_time` and close windows by watermark: `max_seen_event_time - policy.allowed_lateness_seconds`.

- [ ] Step 5: Add tests proving no event is lost when a new event is added while `drain_once()` is running.

- [ ] Step 6: Add tests proving late events inside the allowed lateness period can join their event-time window, while events older than the watermark are rejected or routed to an explicit late-event path.

- [ ] Step 7: Add tests for backlog limits and ready window ordering.

- [ ] Step 8: Run `cd ai_agent && pytest tests/short_ttp/test_window_manager.py -v`.

- [ ] Step 9: Commit with `git commit -m "feat: add queue based short ttp window manager"`.

## Task 4: Extract Event Filtering and Attacker IP Grouping

**Files:**
- Create: `ai_agent/short_ttp/pipeline/filters.py`
- Create: `ai_agent/short_ttp/pipeline/grouping.py`
- Test: `ai_agent/tests/short_ttp/test_event_filtering.py`
- Test: `ai_agent/tests/short_ttp/test_attacker_grouping.py`

- [ ] Step 1: Move priority filtering behavior from `ttp_generator/short_ttp_generator.py` into `filters.py`.

- [ ] Step 2: Move attacker IP normalization and grouping behavior into `grouping.py`.

- [ ] Step 3: Preserve existing behavior: OpenRASP and Suricata events outrank Falco events inside one window.

- [ ] Step 4: Preserve existing safety behavior: too many attacker IP groups falls back to a single `unknown` group.

- [ ] Step 5: Run `cd ai_agent && pytest tests/short_ttp/test_event_filtering.py tests/short_ttp/test_attacker_grouping.py -v`.

- [ ] Step 6: Commit with `git commit -m "feat: extract short ttp filtering and grouping"`.

## Task 5: Add New Short TTP Processor Behind Interface

**Files:**
- Create: `ai_agent/short_ttp/pipeline/processor.py`
- Create: `ai_agent/short_ttp/workflow/analyzer.py`
- Test: `ai_agent/tests/short_ttp/test_processor.py`

- [ ] Step 1: Define `ShortTTPAnalyzer` protocol with `analyze_events(events, attacker_ip=None)`.

- [ ] Step 2: Add an adapter that wraps existing `ttp_generator.short_ttp_workflow.ShortTTPWorkflowFinal`.

- [ ] Step 3: Implement `ShortTTPProcessor` that consumes ready windows, filters events, groups by attacker IP, calls the analyzer, stores accepted Short TTPs, and records failed windows.

- [ ] Step 4: Add tests with a fake analyzer and fake repository to verify success, low-confidence skip, analyzer failure, and multi-IP grouping.

- [ ] Step 5: Run `cd ai_agent && pytest tests/short_ttp/test_processor.py -v`.

- [ ] Step 6: Commit with `git commit -m "feat: add new short ttp processor"`.

## Task 6: Wire New Pipeline Behind Feature Flag

**Files:**
- Modify: `ai_agent/main.py`
- Modify: `ai_agent/api_server/routes.py`
- Test: `ai_agent/tests/integration/test_short_ttp_pipeline_selection.py`

- [ ] Step 1: Keep old pipeline as default when `USE_NEW_SHORT_TTP_PIPELINE=false`.

- [ ] Step 2: Instantiate new `ShortTTPWindowManager` and `ShortTTPProcessor` when `USE_NEW_SHORT_TTP_PIPELINE=true`.

- [ ] Step 3: Expose pipeline mode in health/status output as `legacy` or `route_b`.

- [ ] Step 4: Add integration tests for both selection modes.

- [ ] Step 5: Run `cd ai_agent && pytest tests/integration/test_short_ttp_pipeline_selection.py -v`.

- [ ] Step 6: Commit with `git commit -m "feat: gate new short ttp pipeline by feature flag"`.

## Task 7: Add MITRE Converter Shared by Short and Long TTP

**Files:**
- Create: `ai_agent/ttp_investigation/converters.py`
- Test: `ai_agent/tests/ttp_investigation/test_converters.py`

- [ ] Step 1: Move technique-to-TTP conversion into `ttp_investigation/converters.py`.

- [ ] Step 2: Preserve output compatibility with `shared.models.ttp.TTP` and `shared.models.ttp.Technique`.

- [ ] Step 3: Add tests for tactic grouping, procedure extraction, event ID propagation, duplicate event removal, and malformed event list fallback.

- [ ] Step 4: Run `cd ai_agent && pytest tests/ttp_investigation/test_converters.py -v`.

- [ ] Step 5: Commit with `git commit -m "feat: add shared ttp investigation converter"`.

## Task 8: Create Explicit Long TTP Package and Compatibility Wrappers

**Files:**
- Create: `ai_agent/long_ttp/__init__.py`
- Create: `ai_agent/long_ttp/api.py`
- Create: `ai_agent/long_ttp/analyzer/__init__.py`
- Create: `ai_agent/long_ttp/analyzer/deep_researcher.py`
- Create: `ai_agent/long_ttp/feedback/__init__.py`
- Create: `ai_agent/long_ttp/feedback/session.py`
- Create: `ai_agent/long_ttp/feedback/templates.py`
- Modify: `ai_agent/ttp_generator/dx_analyzer_api.py`
- Modify: `ai_agent/ttp_generator/dx_analyzer/deep_researcher.py`
- Test: `ai_agent/tests/long_ttp/test_compatibility_wrappers.py`
- Test: `ai_agent/tests/long_ttp/test_feedback_templates.py`

- [ ] Step 1: Create the `long_ttp` package skeleton for analyzer code, trigger API code, and feedback session code.

- [ ] Step 2: Move Long TTP trigger API behavior from `ttp_generator/dx_analyzer_api.py` into `long_ttp/api.py`.

- [ ] Step 3: Move Long TTP deep researcher behavior from `ttp_generator/dx_analyzer/deep_researcher.py` into `long_ttp/analyzer/deep_researcher.py`.

- [ ] Step 4: Move Long TTP feedback/session behavior from the `ttp_generator/dx_analyzer*` area into `long_ttp/feedback/session.py`.

- [ ] Step 5: Move human feedback display templates, including the `feedback_request` text currently built inside `human_feedback_node`, into `long_ttp/feedback/templates.py` as builder functions such as `build_human_feedback_request(display_original_request, thoughts_summary)`. Treat these as human-facing UI copy, not LLM prompts.

- [ ] Step 6: Replace old `ttp_generator/dx_analyzer*` modules with compatibility wrappers that re-export or delegate to the new `long_ttp` modules without changing public call sites.

- [ ] Step 7: Add wrapper tests proving old import paths and new import paths resolve to behavior-compatible objects.

- [ ] Step 8: Add feedback template tests proving the human-facing request includes the Short TTP summary, investigation thoughts, and no model-only instruction text.

- [ ] Step 9: Run `cd ai_agent && pytest tests/long_ttp/test_compatibility_wrappers.py tests/long_ttp/test_feedback_templates.py -v`.

- [ ] Step 10: Commit with `git commit -m "refactor: add explicit long ttp package wrappers"`.

## Task 9: Make Long TTP Graph Construction Explicit

**Files:**
- Modify: `ai_agent/long_ttp/analyzer/deep_researcher.py`
- Modify: `ai_agent/ttp_generator/dx_analyzer/deep_researcher.py`
- Test: `ai_agent/tests/long_ttp/test_graph_factories.py`
- Test: `ai_agent/tests/long_ttp/test_compatibility_wrappers.py`

- [ ] Step 1: Replace import-time compiled globals such as `supervisor_subgraph`, `network_researcher_subgraph`, `endpoints_researcher_subgraph`, and `application_researcher_subgraph` with explicit factory functions.

- [ ] Step 2: Add `create_supervisor_subgraph()`, `create_network_researcher_subgraph()`, `create_endpoints_researcher_subgraph()`, and `create_application_researcher_subgraph()` functions that build and compile each subgraph without reading request-specific state at import time.

- [ ] Step 3: Update `create_shorttp_triger_longttp_builder(enable_human_feedback=False)` so it obtains the supervisor subgraph through the factory instead of closing over a module-level compiled instance.

- [ ] Step 4: Update the full deep researcher graph construction to use the same factory path, preserving existing public exports such as `deep_researcher` and `shorttp_triger_longttp_builder` only as compatibility surfaces if still needed.

- [ ] Step 5: Make the final report path explicit in the graph factories. Register only the final node required by the selected mode instead of always adding unused report nodes.

- [ ] Step 6: Rename or wrap final report nodes so their roles are unambiguous: general research report, threat-hunting report, and MITRE investigation report. Preserve old public names through compatibility exports only when needed.

- [ ] Step 7: If compile cost is a concern, add explicit cached accessors such as `get_supervisor_subgraph()` using bounded `lru_cache`; do not compile subgraphs implicitly during module import unless required by a compatibility export.

- [ ] Step 8: Add tests proving the short-trigger-long builder and the full deep researcher builder each request their supervisor subgraph through the factory, preserve graph routing, register only the selected final report path, and still pass runtime `Configuration` through `RunnableConfig`.

- [ ] Step 9: Add a compatibility-wrapper test proving old imports from `ttp_generator/dx_analyzer/deep_researcher.py` still resolve after the implementation moves to `long_ttp/analyzer/deep_researcher.py`.

- [ ] Step 10: Run `cd ai_agent && pytest tests/long_ttp/test_graph_factories.py tests/long_ttp/test_compatibility_wrappers.py -v`.

- [ ] Step 11: Commit with `git commit -m "refactor: make long ttp graph construction explicit"`.

## Task 10: Rebuild MITRE Investigation Graph as Services Plus Thin Nodes

**Files:**
- Create: `ai_agent/ttp_investigation/investigation/config.py`
- Create: `ai_agent/ttp_investigation/investigation/state.py`
- Create: `ai_agent/ttp_investigation/investigation/services.py`
- Create: `ai_agent/ttp_investigation/investigation/nodes.py`
- Create: `ai_agent/ttp_investigation/investigation/graph.py`
- Test: `ai_agent/tests/ttp_investigation/test_investigation_graph.py`

- [ ] Step 1: Define `MitreInvestigationConfig` with model, domain, checkpoint, and report-writing options.

- [ ] Step 2: Define typed state fields without broad `Dict[str, Any]` for core outputs.

- [ ] Step 3: Implement services for triage, mapping, enrichment, detection fallback, and report generation. Services may initially delegate to existing `mitre_attck_agent.attack_rag` and `report_agent`, but only until the later legacy MITRE package removal task moves those modules into `ttp_investigation/`.

- [ ] Step 4: Implement nodes as thin wrappers that only read state, call a service, and return state updates.

- [ ] Step 5: Implement graph factory that receives config explicitly and does not read `USE_MITRE_INVESTIGATION_SUBGRAPH` during import.

- [ ] Step 6: Add tests with fake services for full success, triage failure, enrichment partial failure, and detection fallback route.

- [ ] Step 7: Run `cd ai_agent && pytest tests/ttp_investigation/test_investigation_graph.py -v`.

- [ ] Step 8: Commit with `git commit -m "feat: rebuild ttp investigation graph core"`.

## Task 11: Wire New MITRE Graph Behind Feature Flag

**Files:**
- Modify: `ai_agent/ttp_generator/short_ttp_workflow.py`
- Modify: `ai_agent/long_ttp/analyzer/deep_researcher.py`
- Modify: `ai_agent/ttp_generator/dx_analyzer/deep_researcher.py`
- Test: `ai_agent/tests/integration/test_mitre_graph_selection.py`

- [ ] Step 1: Keep existing MITRE graph as default when `USE_NEW_MITRE_INVESTIGATION=false`.

- [ ] Step 2: Route Short TTP analysis to the new MITRE graph when `USE_NEW_MITRE_INVESTIGATION=true`.

- [ ] Step 3: Route Long TTP MITRE investigation to the new graph through `long_ttp/analyzer/deep_researcher.py` when `USE_NEW_MITRE_INVESTIGATION=true`.

- [ ] Step 4: Update the old `ttp_generator/dx_analyzer/deep_researcher.py` compatibility wrapper so legacy imports use the same Long TTP graph selection behavior.

- [ ] Step 5: Use the shared `ttp_investigation.converters` module in both Short TTP and Long TTP paths.

- [ ] Step 6: Run `cd ai_agent && pytest tests/integration/test_mitre_graph_selection.py -v`.

- [ ] Step 7: Commit with `git commit -m "feat: gate new ttp investigation graph by feature flag"`.

## Task 12: Collapse Short TTP to a Single LangGraph Boundary

**Files:**
- Modify: `ai_agent/ttp_generator/short_ttp_workflow.py`
- Test: `ai_agent/tests/short_ttp/test_short_ttp_workflow.py`
- Test: `ai_agent/tests/integration/test_mitre_graph_selection.py`

- [ ] Step 1: Remove the outer `ShortTTPWorkflowFinal._build_workflow()` LangGraph wrapper so Short TTP orchestration uses normal Python control flow for event collection, sorting, MITRE investigation invocation, and result conversion.

- [ ] Step 2: Keep `mitre_attck_agent.workflows.graph.create_short_ttp_graph_no_checkpointing()` as the only LangGraph boundary for legacy Short TTP MITRE analysis while the legacy MITRE package still exists.

- [ ] Step 3: Preserve public behavior of `ShortTTPWorkflowFinal.analyze_events(events, attacker_ip=None)` so existing callers and the Route B adapter from Task 5 do not change.

- [ ] Step 4: Convert `EventCollectorNode` and the no-op `validate_result` step into private helper methods or remove them if their behavior is covered directly in `analyze_events()`.

- [ ] Step 5: Add regression tests proving `analyze_events()` still sorts events by canonical event time, propagates `attacker_ip`, invokes the Short TTP MITRE graph once, and returns the same `ShortTTP` shape.

- [ ] Step 6: Keep the feature-flag behavior from Task 11 intact: legacy mode still calls the legacy short MITRE graph, and `USE_NEW_MITRE_INVESTIGATION=true` still routes to the new investigation graph.

- [ ] Step 7: Run `cd ai_agent && pytest tests/short_ttp/test_short_ttp_workflow.py tests/integration/test_mitre_graph_selection.py -v`.

- [ ] Step 8: Commit with `git commit -m "refactor: collapse short ttp orchestration graph"`.

## Task 13: Add End-to-End Regression Fixtures

**Files:**
- Create: `ai_agent/tests/fixtures/events/openrasp_attack.json`
- Create: `ai_agent/tests/fixtures/events/suricata_alert.json`
- Create: `ai_agent/tests/fixtures/events/falco_raw.json`
- Create: `ai_agent/tests/integration/test_short_ttp_e2e.py`

- [ ] Step 1: Add minimal representative fixture events for OpenRASP, Suricata, and Falco.

- [ ] Step 2: Add an end-to-end test that parses fixtures into `SecurityEvent`, windows them, processes them with fake analyzer, and verifies generated `ShortTTP`.

- [ ] Step 3: Add a high-frequency event test proving max window size splits or closes windows before LLM analysis.

- [ ] Step 4: Add a regression fixture for the July 7 windowing example:
  - Suricata `01:06:42.969` plus delayed Falco `/java/bin/java` at `time=01:06:43.015` must produce one Short TTP window.
  - Falco `ls`, `/usr/bin/ls`, `pwd`, and `date` events from `01:06:50.200` to `01:06:53.302` must produce one 5-second Short TTP window.

- [ ] Step 5: Run `cd ai_agent && pytest tests/integration/test_short_ttp_e2e.py -v`.

- [ ] Step 6: Commit with `git commit -m "test: add route b short ttp e2e regression"`.

## Task 14: Absorb Legacy MITRE Agent Package Into ttp_investigation

**Files:**
- Create: `ai_agent/ttp_investigation/attack_rag.py`
- Create: `ai_agent/ttp_investigation/schemas.py`
- Create: `ai_agent/ttp_investigation/reporting/__init__.py`
- Create: `ai_agent/ttp_investigation/reporting/report_agent.py`
- Create: `ai_agent/ttp_investigation/investigation/run_workflow.py`
- Modify: `ai_agent/ttp_investigation/investigation/services.py`
- Modify: `ai_agent/ttp_investigation/investigation/graph.py`
- Modify: `ai_agent/ttp_investigation/investigation/nodes.py`
- Modify: `ai_agent/ttp_investigation/investigation/state.py`
- Modify: `ai_agent/ttp_generator/short_ttp_workflow.py`
- Modify: `ai_agent/long_ttp/analyzer/deep_researcher.py`
- Delete: `ai_agent/mitre_attck_agent/`
- Test: `ai_agent/tests/ttp_investigation/test_legacy_mitre_agent_removal.py`
- Test: `ai_agent/tests/integration/test_mitre_graph_selection.py`

- [ ] Step 1: Move reusable ATT&CK RAG behavior from `mitre_attck_agent/attack_rag.py` into `ttp_investigation/attack_rag.py`.

- [ ] Step 2: Move MITRE schema definitions from `mitre_attck_agent/schemas.py` into `ttp_investigation/schemas.py`.

- [ ] Step 3: Move report generation behavior from `mitre_attck_agent/agents/report_agent.py` into `ttp_investigation/reporting/report_agent.py`.

- [ ] Step 4: Move any still-needed workflow entry behavior from `mitre_attck_agent/workflows/run_workflow.py` into `ttp_investigation/investigation/run_workflow.py`.

- [ ] Step 5: Update `ttp_investigation/investigation/services.py`, `graph.py`, `nodes.py`, and `state.py` so all imports use `ttp_investigation.attack_rag`, `ttp_investigation.schemas`, `ttp_investigation.reporting.report_agent`, and `ttp_investigation.investigation.*`.

- [ ] Step 6: Update Short TTP and Long TTP callers so they do not import from `mitre_attck_agent`.

- [ ] Step 7: Add a regression test that imports the public MITRE graph, services, schemas, RAG helper, and report agent from `ttp_investigation/` and verifies no test imports require `mitre_attck_agent`.

- [ ] Step 8: Delete `ai_agent/mitre_attck_agent/` after all imports have moved.

- [ ] Step 9: Run `cd ai_agent && rg "mitre_attck_agent" .` and verify it returns no matches outside migration documentation.

- [ ] Step 10: Run `cd ai_agent && pytest tests/ttp_investigation/test_legacy_mitre_agent_removal.py tests/integration/test_mitre_graph_selection.py -v`.

- [ ] Step 11: Commit with `git commit -m "refactor: absorb legacy mitre agent into ttp investigation"`.

## Task 15: Operational Readiness and Cleanup

**Files:**
- Modify: `ai_agent/.dockerignore`
- Modify: `.gitignore`
- Modify: `ai_agent/README.md`
- Modify: `ai_agent/README_EN.md`

- [ ] Step 1: Ignore runtime artifacts: `__pycache__/`, `*.pyc`, `*.log`, `ai_agent/.cache/`, `out/`, and generated report files.

- [ ] Step 2: Document feature flags and rollback steps.

- [ ] Step 3: Document migration order: enable new Short TTP pipeline first, enable new MITRE graph second, then remove the legacy `mitre_attck_agent/` package after parity is proven.

- [ ] Step 4: Run `git status --short` and verify only intentional source, docs, and test files are changed.

- [ ] Step 5: Run `cd ai_agent && rg "mitre_attck_agent" .` and verify it returns no matches outside migration documentation.

- [ ] Step 6: Run `cd ai_agent && pytest tests/short_ttp tests/ttp_investigation tests/long_ttp tests/integration -v`.

- [ ] Step 7: Commit with `git commit -m "docs: document route b migration and cleanup runtime artifacts"`.

## Rollout Plan

1. Deploy with both flags disabled.
2. Enable `USE_NEW_SHORT_TTP_PIPELINE=true` in one non-production environment.
3. Compare legacy and new Short TTP output for the same Kafka replay sample.
4. Enable `USE_NEW_SHORT_TTP_PIPELINE=true` in production with `USE_NEW_MITRE_INVESTIGATION=false`.
5. After Short TTP stability is confirmed, enable `USE_NEW_MITRE_INVESTIGATION=true` in non-production.
6. Compare MITRE technique IDs, tactic grouping, event IDs, and report quality.
7. Enable new MITRE graph in production.
8. After at least one stable release cycle, move remaining MITRE agent internals into `ttp_investigation/` and remove `mitre_attck_agent/`.
9. Remove other legacy compatibility modules only after their old import paths are no longer needed.

## Verification Commands

Run these before calling the route B migration complete:

```bash
cd ai_agent
pytest tests/short_ttp tests/ttp_investigation tests/long_ttp tests/integration -v
python -m compileall short_ttp ttp_investigation long_ttp
rg "mitre_attck_agent" .
```

## Self-Review

- Spec coverage: The plan covers package structure, window reliability, Short TTP pipeline, Short TTP graph boundary simplification, Long TTP package boundaries, human feedback templates, explicit Long TTP graph construction, MITRE converter, MITRE graph, legacy MITRE agent absorption, feature flags, tests, rollout, and cleanup.
- Placeholder scan: No `TBD`, `TODO`, or implementation-later placeholders remain.
- Type consistency: Names are consistent across tasks: `ShortTTPRuntimeConfig`, `WindowPolicy`, `ShortTTPWindowManager`, `ShortTTPProcessor`, `MitreInvestigationConfig`.
