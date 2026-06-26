from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List


REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCHER_PATH = REPO_ROOT / "ai_agent" / "ttp_generator" / "dx_analyzer" / "deep_researcher.py"


def _load_grouping_helpers():
    module = ast.parse(RESEARCHER_PATH.read_text(encoding="utf-8"))
    wanted = {
        "_parse_procedure_items",
        "_combine_behavior_evidence_procedures",
        "_group_techniques_by_tactic",
    }
    selected = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {"Dict": Dict, "List": List}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(RESEARCHER_PATH), "exec"), namespace)
    return namespace["_group_techniques_by_tactic"]


def test_long_ttp_groups_combine_behavior_and_evidence_procedures():
    group_techniques = _load_grouping_helpers()

    confirmed_techniques = [
        {
            "id": "T1059.001",
            "name": "PowerShell",
            "procedures": ["used powershell to download remote script"],
            "evidence": ["fallback evidence should not be used when candidates exist"],
            "tactics": [{"tactic": "execution"}],
        }
    ]
    technique_candidates = {
        "T1059.001": ["raw event: powershell downloaded http://example.test/a.ps1"],
    }

    groups = group_techniques(confirmed_techniques, technique_candidates)

    assert groups["execution"][0]["procedures"] == [
        "行为: used powershell to download remote script；证据: raw event: powershell downloaded http://example.test/a.ps1"
    ]

