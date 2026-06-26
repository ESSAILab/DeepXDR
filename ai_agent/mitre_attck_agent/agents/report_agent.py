from __future__ import annotations

import json
import os
import re
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from openai import AsyncOpenAI

from mitre_attck_agent.schemas import IncidentExecutiveReport

load_dotenv()

# (gpt-4.1-mini, gpt-4o-mini, etc.)
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

def _extract_json_text(raw: str) -> str:
    """
    Returns a JSON string suitable for pydantic .model_validate_json().

    Handles common LLM wrappers:
      - ```json ... ```
      - ``` ... ```
      - Leading/trailing commentary around a JSON object
    """
    if not raw:
        return raw

    s = raw.strip()

    fence = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', s, flags=re.DOTALL)
    if fence:
        s = fence.group(1).strip()

    obj_start = s.find("{")
    arr_start = s.find("[")
    if obj_start == -1 and arr_start == -1:
        return s

    start = min([i for i in [obj_start, arr_start] if i != -1])
    candidate = s[start:].strip()

    try:
        json.loads(candidate)
        return candidate
    except Exception:
        last_obj = candidate.rfind("}")
        last_arr = candidate.rfind("]")
        end = max(last_obj, last_arr)
        if end != -1:
            return candidate[: end + 1].strip()
        return candidate


def _compact_techniques(confirmed: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for t in confirmed or []:
        tid = t.get("id", "")
        name = t.get("name", "")
        tactics = t.get("tactics", [])

        tactic_names: List[str] = []
        if isinstance(tactics, list):
            for x in tactics:
                if isinstance(x, dict) and x.get("tactic"):
                    tactic_names.append(str(x["tactic"]))

        tactic_str = ", ".join(sorted(set(tactic_names))) if tactic_names else "Unknown"
        out.append(f"{tid} {name} ({tactic_str})".strip())

    return out[:20]


def _extract_name_list(items: Any) -> List[str]:
    """从列表项中提取字典中 'name' 字段的字符串值。"""
    names: List[str] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("name"), str):
                names.append(it["name"])
    return names


def _compact_intel(intel: Dict[str, Any], max_items: int = 12) -> List[str]:
    """
    Compact intel agent data into readable lines for LLM context.
    Returns lines like:
      "T1055 Process Injection: Groups=APT28, FIN7 | Software=Cobalt Strike, Empire"
    """
    lines: List[str] = []
    intel_items = (intel or {}).get("intel", [])
    if not isinstance(intel_items, list):
        return lines

    for item in intel_items[:max_items]:
        if not isinstance(item, dict):
            continue

        tech = item.get("technique", {})
        if not isinstance(tech, dict):
            continue

        tid = str(tech.get("id", "") or "")
        tname = str(tech.get("name", "") or "")

        gnames = _extract_name_list(item.get("groups_using_technique", []))[:5]
        snames = _extract_name_list(item.get("software_using_technique", []))[:5]

        if gnames or snames:
            groups_str = ", ".join(gnames) if gnames else "—"
            software_str = ", ".join(snames) if snames else "—"
            lines.append(f"{tid} {tname}: Groups={groups_str} | Software={software_str}")

    return lines


def _compact_detections(
    detections: Dict[str, Any],
    reasoning: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Provide both STIX-backed detections and LLM fallback hypotheses (if present)
    as context to the report writer.
    """
    stix_rows: List[Dict[str, Any]] = []
    for item in (detections or {}).get("detections", []):
        tech = item.get("technique", {}) if isinstance(item, dict) else {}
        det = item.get("detection", {}) if isinstance(item, dict) else {}

        stix_rows.append(
            {
                "technique_id": tech.get("id"),
                "technique_name": tech.get("name"),
                "stix_total_datacomponents": det.get("total_datacomponents", 0),
                "stix_top_datacomponents": det.get("top_datacomponents", []),
                "note": det.get("message") or "",
            }
        )

    llm_rows: List[Any] = []
    if isinstance(reasoning, dict):
        if "llm_detections" in reasoning:
            llm_rows = reasoning.get("llm_detections") or []
        elif "hypotheses" in reasoning:
            llm_rows = reasoning.get("hypotheses") or []

    return {"stix": stix_rows, "llm": llm_rows}


def _build_mitigation_top(mit_list: List[Any], max_per_technique: int) -> List[Dict[str, Any]]:
    """从缓解措施列表中提取前 N 条核心字段。"""
    top: List[Dict[str, Any]] = []
    for m in mit_list[:max_per_technique]:
        if isinstance(m, dict):
            top.append(
                {
                    "attack_id": m.get("attack_id"),
                    "name": m.get("name"),
                    "stix_id": m.get("stix_id"),
                }
            )
    return top


def _compact_mitigations(mitigations_ctx: Dict[str, Any], max_per_technique: int = 6) -> Dict[str, Any]:
    """
    mitigation_agent output (expected):
      {"domain": "...", "mitigations": [{"technique": {...}, "mitigations":[...], "count":..., "formatted":...}, ...]}

    We give the LLM:
      - structured lines per technique (names/ids)
      - and the raw 'formatted' block as fallback reference (but clipped)
    """
    items = (mitigations_ctx or {}).get("mitigations", [])
    if not isinstance(items, list):
        items = []

    structured: List[Dict[str, Any]] = []
    formatted_by_tech: List[Dict[str, str]] = []

    for it in items:
        if not isinstance(it, dict):
            continue

        tech = it.get("technique", {})
        if not isinstance(tech, dict):
            tech = {}

        tech_id = str(tech.get("id") or "")
        tech_name = str(tech.get("name") or "")

        mit_list = it.get("mitigations", [])
        if not isinstance(mit_list, list):
            mit_list = []

        top = _build_mitigation_top(mit_list, max_per_technique)

        structured.append(
            {
                "technique_id": tech_id,
                "technique_name": tech_name,
                "count": int(it.get("count") or len(mit_list)),
                "top_mitigations": top,
            }
        )

        fmt = it.get("formatted") or ""
        if isinstance(fmt, str) and fmt.strip():
            formatted_by_tech.append(
                {
                    "technique_id": tech_id,
                    "formatted": fmt[:2000],  # bounded
                }
            )

    return {"structured": structured, "formatted": formatted_by_tech}


def _clean_invalid_json(content: str) -> str:
    """尝试清理无效的 JSON 字符串"""
    import re

    # 移除控制字符 (\u0000-\u001F)，这些字符在 JSON 中是无效的
    # 保留换行符 \n 和制表符 \t，因为它们在 JSON 中是允许的
    content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', content)

    # 移除可能截断的部分
    content = content.strip()

    # 尝试修复未闭合的对象和数组
    open_braces = content.count("{")
    closed_braces = content.count("}")
    open_brackets = content.count("[")
    closed_brackets = content.count("]")

    # 修复大括号
    while open_braces > closed_braces:
        content += "}"
        closed_braces += 1
    while open_braces < closed_braces:
        content = "{" + content
        open_braces += 1

    # 修复方括号
    while open_brackets > closed_brackets:
        content += "]"
        closed_brackets += 1
    while open_brackets < closed_brackets:
        content = "[" + content
        open_brackets += 1

    # 移除可能的截断标记
    content = re.sub(r"\.\.\.$", "", content).strip()

    return content


def _create_fallback_report(
    incident_text: str,
    triage_summary: str,
    confirmed_techniques: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """创建一个基于真实数据的回退报告，避免报告失败"""
    # 基于 triage_summary 生成标题
    title = "Incident Fallback Report"
    if triage_summary and len(triage_summary) > 0:
        # 提取前 80 个字符作为标题
        title = triage_summary[:80] + ("..." if len(triage_summary) > 80 else "")

    # 基于 confirmed_techniques 生成技术列表
    mapped_techniques = []
    for tech in confirmed_techniques:
        tech_id = tech.get("id", "unknown")
        tech_name = tech.get("name", "unknown")
        tactics = ", ".join([t.get("tactic", "unknown") for t in tech.get("tactics", [])])
        mapped_techniques.append(f"- **{tech_id}** {tech_name} ({tactics})")

    # 基于 incident_text 提取简单的攻击流程
    likely_attack_flow = []
    if incident_text:
        lines = incident_text.split("\n")
        for line in lines[:6]:  # 取前6行作为攻击流程
            line = line.strip()
            if line and len(line) < 200:
                likely_attack_flow.append(line)

    # 如果没有提取到，使用通用的
    if not likely_attack_flow:
        likely_attack_flow = [
            "Analysis of security events identified",
            "MITRE ATT&CK techniques mapped",
            "Technical context collected"
        ]

    fallback_report = {
        "title": title,
        "executive_summary": triage_summary or "Analysis of security events based on available data.",
        "likely_attack_flow": likely_attack_flow,
        "mapped_techniques": mapped_techniques,
        "notable_groups_software": [],
        "detection_recommendations": [
            "Review and validate the mapped MITRE ATT&CK techniques",
            "Continue monitoring for similar activity patterns"
        ],
        "immediate_actions": [
            "Review triage summary for key insights",
            "Examine mapped MITRE ATT&CK techniques"
        ],
        "iocs": {
            "suspected_artifacts": [],
            "suspicious_processes": [],
            "suspicious_network": []
        },
        "markdown": f"# {title}\n\n"
                   "## Executive Summary\n"
                   f"{triage_summary}\n\n"
                   "## Mapped MITRE ATT&CK Techniques\n"
                   + "\n".join(mapped_techniques)
    }

    return fallback_report


async def write_executive_report_llm(
    incident_text: str,
    triage_summary: str,
    confirmed_techniques: List[Dict[str, Any]],
    intel: Dict[str, Any],
    detections: Dict[str, Any],
    mitigations: Optional[Dict[str, Any]] = None,
    detection_reasoning: Optional[Dict[str, Any]] = None,
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """
    Agent (Reporting):
    LLM writes a full executive report as JSON (validated by IncidentExecutiveReport),
    then returns {"report": <validated dict>}.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to .env")

    context = {
        "incident_text": incident_text,
        "triage_summary": triage_summary,
        "mapped_techniques": _compact_techniques(confirmed_techniques),
        "intel_summary": _compact_intel(intel),
        "detection_context": _compact_detections(detections, detection_reasoning),
        "mitigations_context": _compact_mitigations(mitigations or {}),
    }

    from ttp_generator.dx_analyzer.mitre_investigation_prompts import (
        report_system_prompt,
        report_user_prompt_template,
    )

    system = report_system_prompt

    user = report_user_prompt_template.format(
        context_json=json.dumps(context, indent=2),
    )

    # 使用 AsyncOpenAI 客户端，与其他 agent 保持一致
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL"),  # 支持自定义代理/转发服务
        timeout=180.0,  # 增加超时时间到180秒
    )

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=16000,  # 增加足够的 token 限制以避免截断
        timeout=900.0  # 显式指定此次请求的超时，单位秒
    )
    content = resp.choices[0].message.content or ""
    content = _extract_json_text(content)

    try:
        report = IncidentExecutiveReport.model_validate_json(content)
        return {"report": report.model_dump()}
    except Exception as e:
        # 详细记录验证错误以便诊断
        error_detail = f"Validation error: {type(e).__name__}: {e}"
        logger.error(f"   [ReportAgent] {error_detail}")
        logger.debug(f"   [ReportAgent] Raw content: {content}")

        # 尝试容错处理：清理并重新解析
        try:
            logger.warning("   [ReportAgent] 尝试容错解析...")
            cleaned_content = _clean_invalid_json(content)
            if cleaned_content != content:
                logger.warning(f"   [ReportAgent] 清理了 {len(content)-len(cleaned_content)} 字符")

            report = IncidentExecutiveReport.model_validate_json(cleaned_content)
            logger.info("   [ReportAgent] 容错解析成功")
            return {"report": report.model_dump()}
        except Exception as fallback_e:
            if isinstance(fallback_e, (KeyboardInterrupt, SystemExit)):
                raise
            logger.error(f"   [ReportAgent] 容错解析也失败: {fallback_e}")
            # 生成一个简化的报告作为最终回退方案
            logger.warning("   [ReportAgent] 使用回退报告方案")
            fallback_report = _create_fallback_report(
                incident_text, triage_summary, confirmed_techniques
            )
            return {"report": fallback_report}
