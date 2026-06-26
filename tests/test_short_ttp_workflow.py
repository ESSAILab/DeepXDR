from __future__ import annotations

import importlib.util
from pathlib import Path


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
