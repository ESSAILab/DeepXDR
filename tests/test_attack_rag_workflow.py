from __future__ import annotations

import asyncio

import pytest

from mitre_attck_agent.attack_rag import (
    AttackKnowledgeBase,
    AttackRagService,
    BehaviorEvidence,
    BehaviorExtractionResult,
    OpenAIFinalTechniqueJudge,
    TechniqueDocument,
)
from mitre_attck_agent.workflows import nodes
from mitre_attck_agent.workflows.graph import create_investigation_graph
from mitre_attck_agent.workflows.state import create_initial_state


def test_local_attack_v18_catalog_confirms_technique_and_tactics():
    kb = AttackKnowledgeBase(include_procedure_examples=False)

    result = kb.confirm_techniques(["T1053.005", "T9999"])

    assert result["attack_version"] == "18.1"
    assert result["not_found"] == ["T9999"]
    assert len(kb.tactic_by_shortname) == 14

    scheduled_task = result["confirmed_techniques"][0]
    assert scheduled_task["id"] == "T1053.005"
    assert scheduled_task["name"] == "Scheduled Task"
    tactic_shortnames = {t["tactic"] for t in scheduled_task["tactics"]}
    assert {"execution", "persistence", "privilege-escalation"} <= tactic_shortnames


def test_extract_window_context_gets_summary_and_behaviors_in_one_llm_call():
    class FakeJudge(OpenAIFinalTechniqueJudge):
        def __init__(self):
            self.calls = 0

        async def _json_chat(self, payload, temperature):
            self.calls += 1
            assert "triage_summary" in payload["output_schema"]
            return {
                "triage_summary": "当前窗口显示攻击者创建计划任务维持持久化，并启动PowerShell下载远程脚本，涉及evt-1和evt-2。",
                "behaviors": [
                    {
                        "evidence": "攻击者创建计划任务UpdateCheck以在重启后执行恶意载荷",
                        "behavior": "created scheduled task for persistence",
                        "event_ids": ["evt-1"],
                    },
                    {
                        "evidence": "随后启动powershell下载远程脚本",
                        "behavior": "used powershell to download remote script",
                        "event_ids": ["evt-2"],
                    },
                ],
            }

    judge = FakeJudge()
    result = asyncio.run(judge.extract_window_context("window text"))

    assert judge.calls == 1
    assert len(result.triage_summary) <= 600
    assert "当前窗口" in result.triage_summary
    assert "evt-1" in result.triage_summary
    assert result.behaviors[0].behavior == "created scheduled task for persistence"


class FakeAttackRagService:
    async def map_report_to_techniques(self, incident_text: str):
        assert "scheduled task" in incident_text.lower()
        return {
            "triage_summary": "Mapped scheduled task execution and persistence behavior.",
            "technique_ids": ["T1053.005"],
            "technique_candidates": {
                "T1053.005": ["malware created a scheduled task to run after reboot"]
            },
            "technique_events": {"T1053.005": ["evt-1"]},
            "confirmed_techniques": [
                {
                    "id": "T1053.005",
                    "name": "Scheduled Task",
                    "stix_id": "attack-pattern--fake",
                    "description": "Fake description from RAG evidence.",
                    "is_subtechnique": True,
                    "platforms": ["Windows"],
                    "tactics": [
                        {"tactic": "execution", "tactic_id": "TA0002", "name": "Execution"},
                        {"tactic": "persistence", "tactic_id": "TA0003", "name": "Persistence"},
                    ],
                    "evidence": ["malware created a scheduled task to run after reboot"],
                    "procedures": ["created scheduled task for persistence"],
                    "event_ids": ["evt-1"],
                    "confidence": 0.91,
                    "reason": "The evidence explicitly mentions scheduled task creation.",
                }
            ],
            "unmapped_behaviors": [],
            "retrieval_candidates": {
                "created scheduled task for persistence": [
                    {
                        "attack_id": "T1053.005",
                        "name": "Scheduled Task",
                        "embedding_score": 0.7,
                        "rerank_score": 0.95,
                    }
                ]
            },
            "attack_version": "18.1",
        }

    def confirm_techniques(self, technique_ids):
        assert technique_ids == ["T1053.005"]
        return {
            "domain": "enterprise",
            "attack_version": "18.1",
            "confirmed_techniques": [
                {
                    "id": "T1053.005",
                    "name": "Scheduled Task",
                    "stix_id": "attack-pattern--official",
                    "description": "Official Scheduled Task description.",
                    "is_subtechnique": True,
                    "platforms": ["Windows"],
                    "url": "https://attack.mitre.org/techniques/T1053/005",
                    "tactics": [
                        {"tactic": "execution", "tactic_id": "TA0002", "name": "Execution"},
                        {"tactic": "persistence", "tactic_id": "TA0003", "name": "Persistence"},
                        {
                            "tactic": "privilege-escalation",
                            "tactic_id": "TA0004",
                            "name": "Privilege Escalation",
                        },
                    ],
                }
            ],
            "not_found": [],
        }

    def enrich_intel(self, confirmed, max_items=5):
        return {
            "domain": "enterprise",
            "intel": [
                {
                    "technique": {
                        "id": confirmed[0]["id"],
                        "name": confirmed[0]["name"],
                        "stix_id": confirmed[0]["stix_id"],
                    },
                    "groups_using_technique": [],
                    "software_using_technique": [],
                }
            ],
        }

    def enrich_detections(self, confirmed, max_items=7):
        return {
            "domain": "enterprise",
            "detections": [
                {
                    "technique": {
                        "id": confirmed[0]["id"],
                        "name": confirmed[0]["name"],
                        "stix_id": confirmed[0]["stix_id"],
                    },
                    "detection": {
                        "mode": "technique_context",
                        "total_datacomponents": 0,
                        "top_datacomponents": [],
                    },
                }
            ],
        }

    def enrich_mitigations(self, confirmed, include_description=False):
        return {
            "domain": "enterprise",
            "mitigations": [
                {
                    "technique": {"id": confirmed[0]["id"], "name": confirmed[0]["name"]},
                    "count": 1,
                    "mitigations": [{"attack_id": "M1047", "name": "Audit"}],
                    "formatted": "Audit",
                }
            ],
            "errors": [],
            "summary": {
                "total_techniques": 1,
                "with_mitigations": 1,
                "total_mitigations": 1,
            },
        }


def test_investigation_graph_runs_with_rag_nodes(monkeypatch):
    fake_service = FakeAttackRagService()
    monkeypatch.setattr(nodes, "get_attack_rag_service", lambda: fake_service)

    async def fake_report_writer(**kwargs):
        confirmed = kwargs["confirmed_techniques"]
        return {
            "report": {
                "title": "Scheduled Task Investigation",
                "executive_summary": kwargs["triage_summary"],
                "likely_attack_flow": ["Scheduled task created", "Persistence established", "Detection reviewed"],
                "mapped_techniques": [f"{confirmed[0]['id']} {confirmed[0]['name']}"],
                "notable_groups_software": [],
                "detection_recommendations": ["Review scheduled task creation logs", "Review process command lines", "Audit persistence"],
                "immediate_actions": ["Inspect task definition", "Isolate affected host", "Collect triage artifacts"],
                "iocs": {
                    "suspected_artifacts": [],
                    "suspicious_processes": [],
                    "suspicious_network": [],
                },
                "markdown": "# Scheduled Task Investigation\n\nMapped T1053.005.",
            }
        }

    monkeypatch.setattr(nodes, "write_executive_report_llm", fake_report_writer)

    graph = create_investigation_graph(checkpointer=None)
    initial = create_initial_state(
        "The malware created a scheduled task named UpdateCheck to run after reboot. Event ID: evt-1",
        llm_model="test-model",
    )

    final_state = asyncio.run(graph.ainvoke(initial))

    assert final_state["technique_ids"] == ["T1053.005"]
    assert final_state["confirmed_techniques"][0]["stix_id"] == "attack-pattern--official"
    assert final_state["detections"]["detections"][0]["detection"]["total_datacomponents"] == 0
    assert final_state["detection_reasoning"]["detection_reasoning"]
    assert "Mapped T1053.005" in final_state["report_markdown"]
    assert final_state["errors"] == []


def test_map_report_to_techniques_dedupes_events_and_tracks_unmapped_behaviors():
    technique = TechniqueDocument(
        attack_id="T1053.005",
        stix_id="attack-pattern--scheduled-task",
        name="Scheduled Task",
        description="Adversaries may abuse scheduled task functionality.",
        is_subtechnique=True,
        platforms=["Windows"],
        tactic_shortnames=["execution", "persistence"],
        url="https://attack.mitre.org/techniques/T1053/005",
        procedure_examples=[],
        search_text="scheduled task persistence",
    )

    class FakeKB:
        include_procedure_examples = False

        def __init__(self):
            self.by_id = {technique.attack_id: technique}

        def tactics_for(self, doc):
            assert doc == technique
            return [
                {"tactic": "execution", "tactic_id": "TA0002", "name": "Execution"},
                {"tactic": "persistence", "tactic_id": "TA0003", "name": "Persistence"},
            ]

    class FakeRetriever:
        def retrieve(self, query, recall_k=50, rerank_k=8):
            assert recall_k == 5
            assert rerank_k == 2
            return [{"technique": technique, "embedding_score": 0.42, "rerank_score": 0.88}]

    class FakeJudge:
        async def extract_window_context(self, incident_text):
            assert "scheduled task" in incident_text
            return BehaviorExtractionResult(
                triage_summary="Scheduled task persistence and one unmatched behavior.",
                behaviors=[
                    BehaviorEvidence("created UpdateCheck task", "scheduled task persistence", ["evt-1", "evt-1"]),
                    BehaviorEvidence("created backup task", "scheduled task persistence", ["evt-2"]),
                    BehaviorEvidence("unclear registry change", "registry change", ["evt-3"]),
                ],
            )

        async def judge(self, behavior, hits):
            if behavior.behavior == "registry change":
                return [{"attack_id": "T9999", "confidence": 0.99, "reason": "not official"}]
            return [
                {
                    "attack_id": "T1053.005",
                    "confidence": 0.61 if behavior.evidence.startswith("created UpdateCheck") else 0.83,
                    "reason": f"matched {behavior.behavior}",
                }
            ]

    service = AttackRagService(kb=FakeKB(), retriever=FakeRetriever(), judge=FakeJudge())

    result = asyncio.run(
        service.map_report_to_techniques(
            "The malware created a scheduled task for persistence.",
            recall_k=5,
            rerank_k=2,
        )
    )

    assert result["technique_ids"] == ["T1053.005"]
    confirmed = result["confirmed_techniques"][0]
    assert confirmed["confidence"] == 0.83
    assert confirmed["event_ids"] == ["evt-1", "evt-2"]
    assert result["technique_events"] == {"T1053.005": ["evt-1", "evt-2"]}
    assert result["technique_candidates"] == {
        "T1053.005": ["created UpdateCheck task", "created backup task"]
    }
    assert result["unmapped_behaviors"] == [
        {
            "evidence": "unclear registry change",
            "behavior": "registry change",
            "event_ids": ["evt-3"],
        }
    ]


def test_map_report_to_techniques_rejects_empty_behavior_extraction():
    class FakeKB:
        include_procedure_examples = False

    class FakeJudge:
        async def extract_window_context(self, incident_text):
            return BehaviorExtractionResult(triage_summary="No behavior.", behaviors=[])

    service = AttackRagService(kb=FakeKB(), retriever=object(), judge=FakeJudge())

    with pytest.raises(ValueError, match="No concrete adversary behaviors"):
        asyncio.run(service.map_report_to_techniques("benign status update"))
