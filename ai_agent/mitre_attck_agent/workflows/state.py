
from __future__ import annotations
from typing import Any, Dict, List, Optional, TypedDict
from typing_extensions import Annotated

# Custom reducer for merging dicts
def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dicts, with right overwriting left."""
    return {**left, **right}


# Custom reducer for merging technique_events (Dict[str, List[str]])
def merge_technique_events(left: Dict[str, List[str]], right: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Merge technique_events dicts, merging lists for the same technique ID.

    例如:
    - left: {"T1059": ["event1"], "T1003": ["event3"]}
    - right: {"T1059": ["event2"], "T1047": ["event4"]}
    - 结果: {"T1059": ["event1", "event2"], "T1003": ["event3"], "T1047": ["event4"]}
    """
    result = {**left}  # 复制 left
    for tech_id, event_ids in right.items():
        if tech_id in result:
            # 合并列表并去重，保持原有顺序
            existing = set(result[tech_id])
            for eid in event_ids:
                if eid not in existing:
                    result[tech_id].append(eid)
                    existing.add(eid)
        else:
            result[tech_id] = event_ids.copy()
    return result

class InvestigationState(TypedDict, total=False):
    """State for the MITRE ATT&CK investigation workflow."""

    # ========== Inputs ==========
    incident_text: str

    # ========== Agent Outputs ==========
    triage_summary: Optional[str]
    technique_candidates: Dict[str, List[str]]
    technique_ids: List[str]
    # technique_events: Dict[str, List[str]]  # 新增字段：技术相关事件ID列表
    technique_events: Annotated[Dict[str, List[str]], merge_technique_events]  # 技术相关事件ID列表，使用专用reducer合并列表
    confirmed_techniques: List[Dict[str, Any]]
    not_found_techniques: List[str]
    unmapped_behaviors: List[Dict[str, Any]]
    retrieval_candidates: Dict[str, List[Dict[str, Any]]]
    attack_version: str
    intel: Annotated[Dict[str, Any], merge_dicts]
    detections: Annotated[Dict[str, Any], merge_dicts]
    detection_reasoning: Annotated[Dict[str, Any], merge_dicts]
    mitigations: Annotated[Dict[str, Any], merge_dicts]
    report: Dict[str, Any]
    report_markdown: Optional[str]

    # ========== Metadata ==========
    completed_agents: Annotated[List[str], lambda x, y: x + y]
    errors: Annotated[List[Dict[str, str]], lambda x, y: x + y]
    timings: Annotated[Dict[str, float], merge_dicts]  # ← Merge dicts
    domain: str
    llm_model: str


def create_initial_state(
    incident_text: str,
    domain: str = "enterprise",
    llm_model: str = "gpt-4o-mini",
) -> InvestigationState:
    """Create initial investigation state with required fields."""
    return InvestigationState(
        incident_text=incident_text,
        domain=domain,
        llm_model=llm_model,
        technique_candidates={},
        technique_ids=[],
        technique_events={},
        confirmed_techniques=[],
        not_found_techniques=[],
        unmapped_behaviors=[],
        retrieval_candidates={},
        attack_version="18.1",
        intel={},
        detections={},
        detection_reasoning={},
        mitigations={},
        completed_agents=[],
        errors=[],
        timings={},
    )

# Some utility functions for updating state
def add_error(
    agent_name: str,
    error: str
) -> Dict[str, Any]:
    """Add an error to state."""
    return {
        "errors": [{
            "agent": agent_name,
            "error": error,
            "timestamp": __import__("datetime").datetime.now().isoformat()
        }]
    }


def mark_agent_complete(
    agent_name: str
) -> Dict[str, Any]:
    """Mark an agent as completed."""
    return {
        "completed_agents": [agent_name]
    }


def add_timing(
    state: InvestigationState,
    agent_name: str,
    duration: float
) -> Dict[str, Any]:
    """Add timing information."""
    timings = state.get("timings", {}).copy()
    timings[agent_name] = duration
    return {"timings": timings}
