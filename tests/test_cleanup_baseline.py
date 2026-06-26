from __future__ import annotations

from mitre_attck_agent.workflows.graph import (
    create_investigation_graph,
    create_short_ttp_graph_no_checkpointing,
)


def _edge_tuples(graph):
    return {
        (edge.source, edge.target, edge.conditional, edge.data)
        for edge in graph.get_graph().edges
    }


def test_investigation_graph_shape_stays_stable_after_cleanup():
    graph = create_investigation_graph()

    assert set(graph.get_graph().nodes) == {
        "__start__",
        "triage",
        "mapping",
        "parallel_enrichment",
        "detection_reasoning_agent",
        "report_agent",
        "__end__",
    }
    assert _edge_tuples(graph) == {
        ("__start__", "triage", False, None),
        ("triage", "mapping", False, None),
        ("mapping", "parallel_enrichment", False, None),
        ("parallel_enrichment", "detection_reasoning_agent", True, None),
        ("parallel_enrichment", "report_agent", True, "join_parallel"),
        ("detection_reasoning_agent", "report_agent", False, None),
        ("report_agent", "__end__", False, None),
    }


def test_short_ttp_graph_shape_stays_stable_after_cleanup():
    graph = create_short_ttp_graph_no_checkpointing()

    assert set(graph.get_graph().nodes) == {"__start__", "triage", "mapping", "__end__"}
    assert _edge_tuples(graph) == {
        ("__start__", "triage", False, None),
        ("triage", "mapping", False, None),
        ("mapping", "__end__", False, None),
    }
