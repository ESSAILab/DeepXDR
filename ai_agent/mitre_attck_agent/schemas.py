from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

Confidence = Literal["low", "medium", "high"]

class TriageInput(BaseModel):
    incident_text: str = Field(..., min_length=10)

class TriagePlanStep(BaseModel):
    step: int
    actor: Literal["mapping", "intel", "detection", "report"]
    intent: str
    suggested_tools: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

class TriageOutput(BaseModel):
    summary: str
    suspected_behaviors: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    candidate_platforms: List[str] = Field(default_factory=list)
    plan: List[TriagePlanStep] = Field(default_factory=list)

    # LLM-extracted evidence used by local ATT&CK mapping
    # technique_id -> list of evidence phrases from the incident text
    technique_evidence: Dict[str, List[str]] = Field(default_factory=dict)
    technique_events: Dict[str, List[str]] = Field(default_factory=dict)



def _clip(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    # keep it readable; ensure final length <= max_len
    return (s[: max_len - 1].rstrip()) + "…"


class DetectionHypothesis(BaseModel):
    title: str = Field(max_length=140)
    telemetry: List[str] = Field(min_length=2, max_length=8)
    rationale: str = Field(max_length=400)
    confidence: Confidence

    # Auto-truncate instead of crashing validation
    @field_validator("title", mode="before")
    @classmethod
    def _clip_title(cls, v: str) -> str:
        return _clip(str(v), 140)

    @field_validator("rationale", mode="before")
    @classmethod
    def _clip_rationale(cls, v: str) -> str:
        return _clip(str(v), 400)

    @field_validator("telemetry", mode="before")
    @classmethod
    def _clip_telemetry_items(cls, v):
        if not isinstance(v, list):
            return v
        return [_clip(str(x), 180) for x in v]


class DetectionLLMOutput(BaseModel):
    technique_id: str = Field(max_length=140)
    technique_name: str = Field(max_length=140)
    hypotheses: List[DetectionHypothesis] = Field(min_length=1, max_length=5)

    @field_validator("technique_id", mode="before")
    @classmethod
    def _clip_tid(cls, v: str) -> str:
        return _clip(str(v), 140)

    @field_validator("technique_name", mode="before")
    @classmethod
    def _clip_tname(cls, v: str) -> str:
        return _clip(str(v), 140)


# Report schema

class ReportIOCSummary(BaseModel):
    suspected_artifacts: List[str] = Field(default_factory=list, max_length=30)
    suspicious_processes: List[str] = Field(default_factory=list, max_length=30)
    suspicious_network: List[str] = Field(default_factory=list, max_length=30)

    @field_validator("suspected_artifacts", "suspicious_processes", "suspicious_network", mode="before")
    @classmethod
    def _clip_list_items(cls, v):
        if not isinstance(v, list):
            return v
        return [_clip(str(x), 180) for x in v][:30]


class IncidentExecutiveReport(BaseModel):
    title: str = Field(max_length=140)
    executive_summary: str = Field(max_length=900)
    likely_attack_flow: List[str] = Field(min_length=3, max_length=12)
    mapped_techniques: List[str] = Field(min_length=1, max_length=20)  # e.g., ["T1059.001 PowerShell (Execution)", ...]
    notable_groups_software: List[str] = Field(default_factory=list, max_length=30)
    detection_recommendations: List[str] = Field(min_length=3, max_length=20)
    immediate_actions: List[str] = Field(min_length=3, max_length=20)
    iocs: ReportIOCSummary = Field(default_factory=ReportIOCSummary)
    markdown: str = Field(max_length=12000)

    # Auto-truncate everywhere it matters
    @field_validator("title", mode="before")
    @classmethod
    def _clip_title(cls, v: str) -> str:
        return _clip(str(v), 140)

    @field_validator("executive_summary", mode="before")
    @classmethod
    def _clip_exec(cls, v: str) -> str:
        return _clip(str(v), 900)

    @field_validator("markdown", mode="before")
    @classmethod
    def _clip_md(cls, v: str) -> str:
        return _clip(str(v), 12000)

    @field_validator("likely_attack_flow", "mapped_techniques", "notable_groups_software",
                     "detection_recommendations", "immediate_actions", mode="before")
    @classmethod
    def _clip_lines(cls, v):
        if not isinstance(v, list):
            return v
        return [_clip(str(x), 240) for x in v]
