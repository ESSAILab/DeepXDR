from __future__ import annotations

import logging
from typing import Literal, AsyncIterator, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver

from mitre_attck_agent.workflows.state import InvestigationState
from mitre_attck_agent.workflows.nodes import (
    triage_node,
    mapping_node,
    parallel_enrichment_node,
    detection_reasoning_node,
    report_node,
)

logger = logging.getLogger(__name__)

CompiledGraphType = Any  # This is the return type from workflow.compile()

# ========== Conditional Edge Logic ==========

def should_run_detection_reasoning(state: InvestigationState) -> Literal["detection_reasoning_agent", "join_parallel"]:
    """
    Decide whether to run detection reasoning based on STIX data availability.

    If any technique has 0 data components, run LLM reasoning.
    Otherwise, skip to report node.
    """
    detections = state.get("detections", {})
    detection_list = detections.get("detections", [])

    # Check if any technique has 0 data components
    for item in detection_list:
        detection_data = item.get("detection", {})
        total_components = detection_data.get("total_datacomponents", 0)

        if total_components == 0:
            logger.debug("Some techniques have 0 data components → Running Detection Reasoning")
            return "detection_reasoning_agent"

    logger.debug("All techniques have STIX data → Skipping Detection Reasoning")
    return "join_parallel"


# ========== Graph Construction ==========

def create_investigation_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None
) -> Any:  # ← Fixed return type
    """
    Create the MITRE ATT&CK investigation workflow graph.

    Flow:
        START → triage → mapping → parallel_enrichment (内部并行intel/detection/mitigation)
              → detection_reasoning (conditional) → report → END

    Args:
        checkpointer: Optional checkpoint saver for persistence.
                     Use MemorySaver() for in-memory checkpoints.

    Returns:
        Compiled StateGraph ready for execution.
    """

    # Initialize graph
    workflow = StateGraph(InvestigationState)

    # ========== Add Nodes ==========

    workflow.add_node("triage", triage_node)
    workflow.add_node("mapping", mapping_node)
    workflow.add_node("parallel_enrichment", parallel_enrichment_node)
    workflow.add_node("detection_reasoning_agent", detection_reasoning_node)
    workflow.add_node("report_agent", report_node)

    # ========== Define Edges ==========

    # Sequential: START → triage → mapping → parallel_enrichment
    workflow.add_edge(START, "triage")
    workflow.add_edge("triage", "mapping")
    workflow.add_edge("mapping", "parallel_enrichment")

    # Conditional: parallel_enrichment → detection_reasoning OR report
    # 根据 detection 结果决定是否需要 LLM 推理补充
    workflow.add_conditional_edges(
        "parallel_enrichment",
        should_run_detection_reasoning,
        {
            "detection_reasoning_agent": "detection_reasoning_agent",
            "join_parallel": "report_agent",  # 直接到 report，跳过 detection_reasoning
        },
    )

    # detection_reasoning → report
    workflow.add_edge("detection_reasoning_agent", "report_agent")

    # Sequential: report → END
    workflow.add_edge("report_agent", END)

    # ========== Compile Graph ==========

    # Compile with optional checkpointing
    if checkpointer is None:
        app = workflow.compile()
    else:
        app = workflow.compile(checkpointer=checkpointer)

    return app


# ========== Convenience Functions ==========

def create_graph_with_memory() -> Any:  # ← Fixed return type
    """
    Create investigation graph with in-memory checkpointing.

    Enables:
    - Resume from any point if execution fails
    - Inspect intermediate state
    - Time-travel debugging

    Usage:
        graph = create_graph_with_memory()
        config = {"configurable": {"thread_id": "investigation-123"}}
        result = await graph.ainvoke(initial_state, config)
    """
    checkpointer = MemorySaver()
    return create_investigation_graph(checkpointer=checkpointer)


def create_graph_no_checkpointing() -> Any:  # ← Fixed return type
    """
    Create investigation graph without checkpointing.

    Faster execution, no persistence.
    Use for production runs where checkpoint overhead is unwanted.
    """
    return create_investigation_graph(checkpointer=None)


def create_short_ttp_graph_no_checkpointing() -> Any:
    """
    Create a simplified investigation graph for Short TTP generation.

    This graph only includes triage and mapping nodes, skipping:
    - parallel_enrichment
    - detection_reasoning
    - visualization
    - report

    Flow:
        START → triage → mapping → END
create_investigation_graph
    Returns:
        Compiled StateGraph ready for execution.
    """
    from mitre_attck_agent.workflows.nodes import (
        triage_node,
        mapping_node,
    )

    workflow = StateGraph(InvestigationState)

    # Add nodes
    workflow.add_node("triage", triage_node)
    workflow.add_node("mapping", mapping_node)

    # Define edges
    workflow.add_edge(START, "triage")
    workflow.add_edge("triage", "mapping")
    workflow.add_edge("mapping", END)

    # Compile without checkpointing
    return workflow.compile()


# ========== Streaming Helpers ==========

async def stream_investigation(
    graph: Any,
    initial_state: InvestigationState,
    config: Optional[Dict[str, Any]] = None  # ← Fixed type hint
) -> AsyncIterator[Dict[str, Any]]:  # ← Fixed return type
    """
    Stream investigation progress with real-time updates.

    Args:
        graph: Compiled LangGraph
        initial_state: Starting state
        config: Optional config (e.g., thread_id for checkpointing)

    Yields:
        Dict with node name and updated state after each step

    Usage:
        graph = create_graph_with_memory()
        initial = create_initial_state("EDR alert: ...")
        config = {"configurable": {"thread_id": "inv-123"}}

        async for update in stream_investigation(graph, initial, config):
            node = update["node"]
            state = update["state"]
            print(f"Completed: {node}")
    """
    if config is None:
        config = {}

    async for event in graph.astream(initial_state, config, stream_mode="updates"):
        for node_name, node_state in event.items():
            yield {
                "node": node_name,
                "state": node_state,
                "completed_agents": node_state.get("completed_agents", []),
                "errors": node_state.get("errors", []),
            }


async def run_investigation(
    graph: Any,
    initial_state: InvestigationState,
    config: Optional[Dict[str, Any]] = None  # ← Fixed type hint
) -> InvestigationState:
    """
    Run complete investigation and return final state.

    Args:
        graph: Compiled LangGraph
        initial_state: Starting state
        config: Optional config (e.g., thread_id for checkpointing)

    Returns:
        Final investigation state

    Usage:
        graph = create_graph_with_memory()
        initial = create_initial_state("EDR alert: ...")
        final = await run_investigation(graph, initial)

        print(final["report_markdown"])
    """
    if config is None:
        config = {}

    final_state = await graph.ainvoke(initial_state, config)
    return final_state

