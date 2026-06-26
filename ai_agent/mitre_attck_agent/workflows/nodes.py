from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict

from mitre_attck_agent.agents.report_agent import write_executive_report_llm
from mitre_attck_agent.attack_rag import get_attack_rag_service
from mitre_attck_agent.workflows.state import (
    InvestigationState,
    add_error,
    add_timing,
    mark_agent_complete,
)

logger = logging.getLogger(__name__)


def retry_async(max_attempts: int = 1, backoff: float = 1.0):
    """Retry an async node with exponential backoff."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exception: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if attempt < max_attempts:
                        wait_time = backoff * (2 ** (attempt - 1))
                        logger.warning("%s attempt %d failed: %s", func.__name__, attempt, exc)
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error("%s failed after %d attempts", func.__name__, max_attempts)
            if last_exception is not None:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed with no exception captured")

        return wrapper

    return decorator


def _merge_confirmed_with_evidence(
    confirmed: list[dict[str, Any]],
    enriched: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep official catalog fields while preserving RAG evidence/confidence."""
    enriched_by_id = {item.get("id"): item for item in enriched if isinstance(item, dict)}
    merged_rows: list[dict[str, Any]] = []
    for item in confirmed:
        evidence_item = enriched_by_id.get(item.get("id"), {})
        merged = {**item, **evidence_item}
        merged["name"] = item.get("name")
        merged["stix_id"] = item.get("stix_id")
        merged["description"] = item.get("description")
        merged["is_subtechnique"] = item.get("is_subtechnique")
        merged["platforms"] = item.get("platforms", [])
        merged["url"] = item.get("url")
        merged["tactics"] = item.get("tactics", [])
        merged_rows.append(merged)
    return merged_rows


@retry_async(max_attempts=1, backoff=1.0)
async def triage_node(state: InvestigationState) -> Dict[str, Any]:
    """
    Node 1: map report evidence to ATT&CK v18.1 techniques.

    Internally this uses the mature RAG pipeline:
    LLM behavior extraction -> embedding recall -> cross-encoder rerank ->
    LLM final judgement.
    """
    logger.info("[1] Running technique triage with embedding + rerank + LLM")
    start_time = time.time()

    incident_text = state.get("incident_text", "")
    if not incident_text:
        raise ValueError("No incident text provided")

    service = get_attack_rag_service()
    triage_out = await service.map_report_to_techniques(incident_text)
    technique_ids = triage_out.get("technique_ids", [])
    if not technique_ids:
        raise ValueError("RAG triage produced no technique candidates")

    duration = time.time() - start_time
    logger.info(
        "Technique triage complete: %d candidates (%.2fs): %s",
        len(technique_ids),
        duration,
        ", ".join(technique_ids),
    )

    return {
        "triage_summary": triage_out.get("triage_summary"),
        "technique_candidates": triage_out.get("technique_candidates", {}),
        "technique_ids": technique_ids,
        "technique_events": triage_out.get("technique_events", {}),
        "confirmed_techniques": triage_out.get("confirmed_techniques", []),
        "unmapped_behaviors": triage_out.get("unmapped_behaviors", []),
        "retrieval_candidates": triage_out.get("retrieval_candidates", {}),
        "attack_version": triage_out.get("attack_version"),
        **mark_agent_complete("triage"),
        **add_timing(state, "triage", duration),
    }


@retry_async(max_attempts=1, backoff=1.0)
async def mapping_node(state: InvestigationState) -> Dict[str, Any]:
    """Node 2: validate and normalize technique IDs with local mitreattack."""
    logger.info("[2] Running local ATT&CK mapping validation")
    start_time = time.time()

    technique_ids = state.get("technique_ids", [])
    if not technique_ids:
        return add_error("mapping", "No technique IDs from triage")

    try:
        service = get_attack_rag_service()
        mapping = service.confirm_techniques(technique_ids)
        confirmed = mapping.get("confirmed_techniques", []) or []
        if not confirmed:
            raise ValueError("No techniques confirmed by local ATT&CK catalog")

        confirmed = _merge_confirmed_with_evidence(
            confirmed,
            state.get("confirmed_techniques", []),
        )
        not_found = mapping.get("not_found", []) or []

        duration = time.time() - start_time
        logger.info(
            "Mapping complete: %d techniques confirmed (%.2fs)",
            len(confirmed),
            duration,
        )

        return {
            "confirmed_techniques": confirmed,
            "not_found_techniques": not_found,
            **mark_agent_complete("mapping"),
            **add_timing(state, "mapping", duration),
        }
    except Exception as exc:
        logger.error("Mapping failed: %s", exc)
        return add_error("mapping", str(exc))


async def _run_enrichment_task(name: str, coro, key: str) -> Dict[str, Any]:
    logger.info("  starting %s enrichment", name)
    started = time.time()
    try:
        result = await coro
        logger.info("  %s enrichment complete (%.2fs)", name, time.time() - started)
        return {key: result, "success": True}
    except Exception as exc:
        logger.error("  %s enrichment failed: %s", name, exc)
        return {key: {}, "success": False, "error": str(exc)}


async def parallel_enrichment_node(state: InvestigationState) -> Dict[str, Any]:
    """Node 3: enrich mapped techniques from local ATT&CK STIX data."""
    logger.info("[3] Running local ATT&CK enrichment")
    start_time = time.time()

    confirmed = state.get("confirmed_techniques", [])
    if not confirmed:
        return add_error("parallel_enrichment", "No confirmed techniques")

    service = get_attack_rag_service()
    intel_result, detection_result, mitigation_result = await asyncio.gather(
        _run_enrichment_task(
            "intel",
            asyncio.to_thread(service.enrich_intel, confirmed, 5),
            "intel",
        ),
        _run_enrichment_task(
            "detection",
            asyncio.to_thread(service.enrich_detections, confirmed, 7),
            "detections",
        ),
        _run_enrichment_task(
            "mitigation",
            asyncio.to_thread(service.enrich_mitigations, confirmed, False),
            "mitigations",
        ),
        return_exceptions=True,
    )

    def _extract(result: Any, key: str) -> Any:
        if isinstance(result, Exception):
            return {}
        return result.get(key, {})

    errors: list[str] = []
    for name, result in [
        ("intel", intel_result),
        ("detection", detection_result),
        ("mitigation", mitigation_result),
    ]:
        if isinstance(result, Exception):
            errors.append(f"{name}: {result}")
        elif not result.get("success"):
            errors.append(f"{name}: {result.get('error', 'unknown')}")

    duration = time.time() - start_time
    output: Dict[str, Any] = {
        "intel": _extract(intel_result, "intel"),
        "detections": _extract(detection_result, "detections"),
        "mitigations": _extract(mitigation_result, "mitigations"),
        **mark_agent_complete("parallel_enrichment"),
        **add_timing(state, "parallel_enrichment", duration),
    }
    if errors:
        output.update(add_error("parallel_enrichment", f"Partial failures: {'; '.join(errors)}"))
    return output


@retry_async(max_attempts=1, backoff=1.0)
async def detection_reasoning_node(state: InvestigationState) -> Dict[str, Any]:
    """
    Node 4: deterministic detection fallback for techniques without STIX data components.

    The core technique mapping already used LLM judgement in triage. This node keeps
    the graph contract intact and supplies report-ready detection hypotheses when the
    v18.1 STIX data has no data-component relationships.
    """
    logger.info("[4] Running detection reasoning fallback")
    start_time = time.time()

    confirmed = state.get("confirmed_techniques", [])
    detections = state.get("detections", {})
    if not confirmed or not detections:
        return add_error("detection_reasoning", "Missing prerequisites")

    detections_by_id = {
        item.get("technique", {}).get("id"): item.get("detection", {})
        for item in detections.get("detections", [])
        if isinstance(item, dict)
    }

    rows: list[dict[str, Any]] = []
    for tech in confirmed:
        detection = detections_by_id.get(tech.get("id"), {})
        if detection.get("total_datacomponents", 0) > 0:
            continue
        rows.append(
            {
                "technique_id": tech.get("id"),
                "technique_name": tech.get("name"),
                "hypotheses": [
                    {
                        "title": f"Monitor behavior consistent with {tech.get('name')}",
                        "telemetry": [
                            "Process creation and command line telemetry",
                            "File, registry, authentication, and network telemetry tied to the mapped evidence",
                        ],
                        "rationale": (
                            "ATT&CK v18.1 has no local data-component relationship for this technique; "
                            "use the mapped report evidence and platform context to drive detection."
                        ),
                        "confidence": "medium",
                    }
                ],
            }
        )

    duration = time.time() - start_time
    return {
        "detection_reasoning": {
            "detection_reasoning": rows,
            "incident_context_used": bool(state.get("incident_text")),
        },
        **mark_agent_complete("detection_reasoning"),
        **add_timing(state, "detection_reasoning", duration),
    }


@retry_async(max_attempts=1, backoff=2.0)
async def report_node(state: InvestigationState) -> Dict[str, Any]:
    """Node 5: generate the final executive report."""
    logger.info("[5] Running report generation")
    start_time = time.time()

    triage_summary = state.get("triage_summary")
    confirmed = state.get("confirmed_techniques", [])
    intel = state.get("intel", {})
    detections = state.get("detections", {})
    incident_text = state.get("incident_text", "")

    missing = []
    if not triage_summary:
        missing.append("triage_summary")
    if not confirmed:
        missing.append("confirmed_techniques")
    if not intel:
        missing.append("intel")
    if not detections:
        missing.append("detections")
    if missing:
        return add_error("report", f"Missing required data: {', '.join(missing)}")

    try:
        report_out = await write_executive_report_llm(
            incident_text=incident_text,
            triage_summary=triage_summary,
            confirmed_techniques=confirmed,
            intel=intel,
            detections=detections,
            detection_reasoning=state.get("detection_reasoning", {}),
            mitigations=state.get("mitigations", {}),
            model=state.get("llm_model", "deepseek-v3-2-251201"),
        )
        report = report_out.get("report", {})
        markdown = report.get("markdown", "")

        report_path = "./out/incident_report.md"
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(markdown)

        duration = time.time() - start_time
        return {
            "report": report,
            "report_markdown": markdown,
            **mark_agent_complete("report"),
            **add_timing(state, "report", duration),
        }
    except Exception as exc:
        logger.error("Report failed: %s", exc)
        return add_error("report", f"{type(exc).__name__}: {exc}")
