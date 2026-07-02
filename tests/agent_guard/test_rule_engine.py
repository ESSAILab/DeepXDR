from __future__ import annotations

from ai_agent.agent_guard.diff_parser import ChangedFile
from ai_agent.agent_guard.rule_engine import detect_risk_signals


def test_rule_engine_flags_sensitive_paths_and_dangerous_patterns():
    changed = ChangedFile(
        path=".github/workflows/deploy.yml",
        change_type="modified",
        added_lines=2,
        deleted_lines=0,
        diff="+ chmod 777 /tmp/build\n+ deploy --verify=false\n",
    )

    signals = detect_risk_signals(changed)

    assert {signal.type for signal in signals} >= {
        "sensitive_path",
        "dangerous_pattern",
    }
    assert any(signal.severity == "high" for signal in signals)


def test_rule_engine_treats_docs_as_low_risk_when_no_pattern_matches():
    changed = ChangedFile(
        path="docs/README.md",
        change_type="modified",
        added_lines=1,
        deleted_lines=1,
        diff="+ Updated usage wording\n- Old wording\n",
    )

    signals = detect_risk_signals(changed)

    assert signals == []
