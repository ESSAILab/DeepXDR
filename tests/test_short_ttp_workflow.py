from __future__ import annotations

import importlib.util
from pathlib import Path
from datetime import datetime

import pytest


def convert_scores(scores):
    analyzer = _load_short_ttp_workflow_module().TTPAnalyzerNode()
    techniques = [
        {"id": f"T{i}", "name": f"Technique {i}", "confidence": score,
         "reason": "Supported by event evidence", "tactics": ["execution", "discovery"]}
        for i, score in enumerate(scores)
    ]
    return analyzer._convert_investigation_to_short_ttp(
        {"state": {"confirmed_techniques": techniques}},
        {"window_start": datetime(2026, 1, 1), "window_end": datetime(2026, 1, 1)},
        [],
    )


def test_confidence_uses_mean_and_preserves_technique_scores():
    result = convert_scores([0.2, 0.8])
    assert result.confidence == pytest.approx(0.5)
    assert result.ttps[0].techniques[0].confidence == 0.2
    assert "confidence_reason" not in result.ttps[0].techniques[0].model_dump()
    assert convert_scores([0.2] * 10).confidence == pytest.approx(0.2)
    assert convert_scores([0.9]).confidence == pytest.approx(0.9)


@pytest.mark.parametrize("invalid", [None, "bad", float("nan"), float("inf"), -0.1, 1.1, True])
def test_invalid_confidence_counts_as_zero(invalid):
    result = convert_scores([invalid, 0.8])
    assert result.confidence == pytest.approx(0.4)
    assert result.ttps[0].techniques[0].confidence == 0.0


def test_empty_techniques_have_zero_confidence():
    assert convert_scores([]).confidence == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [0.2, 0.9])
async def test_generation_stores_all_scores_and_gates_defense(monkeypatch, score):
    import sys
    from types import SimpleNamespace, ModuleType
    from unittest.mock import AsyncMock
    # LongTTP external clients are unrelated to this generation/storage test.
    api = ModuleType("ttp_generator.dx_analyzer_api")
    api.trigger_long_ttp_generation = AsyncMock()
    monkeypatch.setitem(sys.modules, "ttp_generator.dx_analyzer_api", api)
    from ttp_generator.short_ttp_generator import ShortTTPGenerator
    from ttp_generator.short_ttp_workflow import ShortTTPWorkflowFinal

    result = convert_scores([score])
    monkeypatch.setattr(ShortTTPWorkflowFinal, "analyze_events", AsyncMock(return_value=result))
    generator = object.__new__(ShortTTPGenerator)
    generator.confidence_threshold = 0.5
    generator._store_short_ttp = AsyncMock()
    generator.defense_manager = SimpleNamespace(process_short_ttp=AsyncMock(return_value={"status": "success"}))
    event = SimpleNamespace(event_type="test", get_unique_id=lambda: "event-1", get_event_time=lambda: datetime(2026, 1, 1))
    await generator._analyze_ip_group(SimpleNamespace(window_id="window-1"), "198.51.100.1", [event])
    generator._store_short_ttp.assert_awaited_once_with(result)
    assert generator.defense_manager.process_short_ttp.await_count == int(score >= 0.5)


def test_storage_preserves_confidence_and_legacy_techniques():
    from shared.database.elastic_repositories import ShortTTPESRepository
    from shared.models.ttp import Technique

    result = convert_scores([0.2, 0.8])
    repo = object.__new__(ShortTTPESRepository)
    document = repo._convert_to_es_format(result.model_dump())
    assert document["confidence"] == pytest.approx(0.5)
    assert document["ttps"][0]["techniques"][0]["confidence"] == 0.2
    legacy = Technique(tech_id="T1059", tech_name="Command", description="", procedures=[], event_ids=[])
    assert legacy.confidence is None


def _load_short_ttp_workflow_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "ai_agent" / "ttp_generator" / "short_ttp_workflow.py"
    spec = importlib.util.spec_from_file_location("short_ttp_workflow_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_ttp_objects_uses_behavior_and_evidence_procedures():
    module = _load_short_ttp_workflow_module()
    analyzer = module.TTPAnalyzerNode()

    tactic_groups = {
        "execution": [
            {
                "tech_id": "T1059.001",
                "tech_name": "PowerShell",
                "description": "PowerShell command execution",
            }
        ]
    }
    technique_procedures = analyzer._build_technique_procedures(
        [
            {
                "id": "T1059.001",
                "procedures": ["used powershell to download remote script"],
                "evidence": ["raw event: powershell downloaded http://example.test/a.ps1"],
            }
        ]
    )
    technique_events = {"T1059.001": ["evt-2"]}

    ttps = analyzer._build_ttp_objects(tactic_groups, technique_procedures, technique_events)

    technique = ttps[0].techniques[0]
    assert technique.procedures == [
        "行为: used powershell to download remote script；证据: raw event: powershell downloaded http://example.test/a.ps1"
    ]
    assert technique.event_ids == ["evt-2"]
