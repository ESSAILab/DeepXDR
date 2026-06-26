"""
最终的Short TTP LangGraph工作流
使用ChatDeepSeek和with_structured_output简化工作流
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TypedDict
from uuid import uuid4
from shared.utils.timezone import ChinaTime

from langgraph.graph import StateGraph, END

from shared.models.events import SecurityEvent
from shared.models.ttp import ShortTTP, TTP, Technique, AttackerFingerprint

logger = logging.getLogger(__name__)

# 静态导入 mitre_attck_agent 模块（使用完整包路径）
from mitre_attck_agent.workflows.graph import create_short_ttp_graph_no_checkpointing
from mitre_attck_agent.workflows.state import create_initial_state


class ShortTTPState(TypedDict):
    """Short TTP工作流状态"""
    events: List[SecurityEvent]
    window_start: datetime
    window_end: datetime
    analysis_result: Optional[ShortTTP]
    error: Optional[str]
    attacker_ip: Optional[str]  # 攻击者IP（用于IP分组分析）


class EventCollectorNode:
    """事件收集节点"""
    
    def __call__(self, state: ShortTTPState) -> Dict:
        """收集和预处理事件"""
        try:
            if not state["events"]:
                return {"error": "没有事件需要分析"}
            
            # 按时间排序事件
            sorted_events = sorted(state["events"], 
                                 key=lambda e: e.raw_event.time if hasattr(e.raw_event, 'time') else ChinaTime.now())
            
            window_start = sorted_events[0].raw_event.time if hasattr(sorted_events[0].raw_event, 'time') else ChinaTime.now()
            window_end = sorted_events[-1].raw_event.time if hasattr(sorted_events[-1].raw_event, 'time') else ChinaTime.now()
            
            logger.debug(f"收集到{len(sorted_events)}个事件，时间窗口: {window_start} - {window_end}")
            
            return {
                "events": sorted_events,
                "window_start": window_start,
                "window_end": window_end
            }
        except Exception as e:
            logger.error(f"事件收集节点错误: {str(e)}")
            return {"error": str(e)}


class TTPAnalyzerNode:
    """使用 mitre-agentic-threat-investigation 的 investigation graph 进行TTP分析"""

    # 类级别信号量，限制并发调查数量以避免 cancel scope 错误
    _investigation_semaphore = asyncio.Semaphore(2)

    def __init__(self):
        # 注意：不在__init__中缓存任何实例，每次调用创建新的实例以避免并发问题
        pass

    def _create_investigation_graph(self) -> Any:
        """创建新的 investigation graph 实例（每次调用创建新的，避免并发共享问题）

        使用 Short TTP 专用的简化版 graph，只包含 triage 和 mapping 节点，
        跳过 parallel_enrichment、detection_reasoning、visualization、report 等节点。
        """
        try:
            graph = create_short_ttp_graph_no_checkpointing()
            logger.debug("Short TTP Investigation graph 创建成功 (简化版 - 仅 triage + mapping)")
            return graph
        except Exception as e:
            logger.error(f"创建 Short TTP Investigation graph 失败: {e}")
            raise

    async def __call__(self, state: ShortTTPState) -> Dict:
        """使用 investigation graph 分析事件并生成结构化TTP"""
        try:
            if state.get("error"):
                return {}

            events = state["events"]
            logger.info(f"开始分析 {len(events)} 个安全事件...")

            # 将事件转换为 incident_text
            incident_text = self._build_incident_text(events)

            # 使用 investigation graph 进行完整的 MITRE ATT&CK 分析
            investigation_result = await self._run_investigation(incident_text)

            if investigation_result.get("error"):
                logger.error(f"Investigation 分析失败: {investigation_result['error']}")
                return {"error": investigation_result['error']}

            # 将 investigation 结果转换为 ShortTTP 对象
            short_ttp = self._convert_investigation_to_short_ttp(
                investigation_result, state, events
            )

            logger.info(f"分析完成，识别出 {len(short_ttp.ttps)} 个战术，置信度: {short_ttp.confidence}")

            return {"analysis_result": short_ttp}

        except Exception as e:
            logger.error(f"TTP分析节点错误: {str(e)}")
            raise ValueError(f"short TTP analysis failed: {str(e)}")

    def _build_incident_text(self, events: List[SecurityEvent]) -> str:
        """将安全事件列表转换为 incident_text 格式"""
        lines = []
        lines.append("安全事件分析报告")
        lines.append("=" * 60)
        lines.append("")

        for i, event in enumerate(events, 1):
            lines.append(f"事件 {i}:")
            lines.append(f"  事件ID: {event.event_id}")
            lines.append(f"  事件类型: {event.event_type.value}")
            lines.append(f"  时间: {event.get_event_time()}")
            lines.append("  原始数据:")
            lines.append(f"  {event.raw_event.model_dump_json(indent=2, exclude_none=True)}")
            lines.append("")

        return "\n".join(lines)

    async def _run_investigation(self, incident_text: str) -> Dict[str, Any]:
        """运行 investigation graph 进行完整的 MITRE ATT&CK 分析

        使用信号量限制并发数，避免 cancel scope 错误。
        """
        # 使用信号量限制并发，避免 cancel scope 清理错误
        async with self._investigation_semaphore:
            result = None
            try:
                # 获取模型配置，使用兼容的默认模型
                model = os.getenv("OPENAI_MODEL", "deepseek-v3-2-251201")
                # 提取冒号后的真实模型名称（如 openai:deepseek-v3-2-251201 -> deepseek-v3-2-251201）
                if ":" in model:
                    model = model.split(":", 1)[1]

                # 创建初始状态
                initial_state = create_initial_state(
                    incident_text=incident_text,
                    domain="enterprise",
                    llm_model=model,
                )

                # 创建新的 investigation graph 实例（避免并发共享问题）
                graph = self._create_investigation_graph()

                # 执行分析
                logger.info("开始执行 investigation graph 分析...")
                final_state = await graph.ainvoke(initial_state)
                logger.info("Investigation graph 分析完成")
                
                result = {
                    "success": True,
                    "state": final_state
                }

            except Exception as e:
                logger.error(f"Investigation 执行失败: {e}")
                result = {
                    "success": False,
                    "error": str(e)
                }

            return result

    def _build_tactic_groups(self, confirmed_techniques: List[Dict]) -> Dict[str, List[Dict]]:
        """将确认的技术按战术分组"""
        tactic_groups: Dict[str, List[Dict]] = {}
        for tech in confirmed_techniques:
            tech_id = tech.get("id", "")
            tech_name = tech.get("name", "")
            tactics = tech.get("tactics", [])
            for tactic_info in tactics:
                tactic_name = tactic_info.get("tactic", "Unknown") if isinstance(tactic_info, dict) else str(tactic_info)
                if tactic_name not in tactic_groups:
                    tactic_groups[tactic_name] = []
                tactic_groups[tactic_name].append({
                    "tech_id": tech_id,
                    "tech_name": tech_name,
                    "description": tech.get("description", "")
                })
        return tactic_groups

    def _build_ttp_objects(
        self,
        tactic_groups: Dict[str, List[Dict]],
        technique_procedures: Dict,
        technique_events: Dict
    ) -> List[TTP]:
        """将战术分组转换为 TTP 对象列表"""
        ttps = []
        for tactic_name, techniques in tactic_groups.items():
            tech_objects = []
            tactic_events = set()
            for t in techniques:
                procedures = technique_procedures.get(t["tech_id"], [])
                current_tech_events = technique_events.get(t["tech_id"]) or []
                tech_obj = Technique(
                    tech_id=t["tech_id"],
                    tech_name=t["tech_name"],
                    description=t.get("description", ""),
                    procedures=procedures,
                    event_ids=technique_events.get(t["tech_id"], [])
                )
                tech_objects.append(tech_obj)
                if procedures:
                    logger.info(f"技术 {t['tech_id']} ({t['tech_name']}) 已添加 {len(procedures)} 条行为证据到 procedures 中")
                else:
                    logger.debug(f"技术 {t['tech_id']} ({t['tech_name']}) 没有对应的行为证据")
                if isinstance(current_tech_events, list):
                    tactic_events.update(current_tech_events)
                else:
                    logger.warning(f"技术 {t['tech_id']} ({t['tech_name']}) 的事件ID不是列表: {current_tech_events}, 未添加到战术事件集合中")
            ttp = TTP(
                id=str(uuid4()),
                name=tactic_name,
                description=f"战术: {tactic_name}",
                techniques=tech_objects,
                event_ids=list(tactic_events)
            )
            ttps.append(ttp)
        return ttps

    def _resolve_summary(self, final_state: Dict) -> str:
        """从最终状态中解析摘要"""
        summary = final_state.get("triage_summary", "未生成摘要")
        report = final_state.get("report", {})
        if isinstance(report, dict):
            executive_summary = report.get("executive_summary", "")
            if executive_summary:
                return executive_summary
        return summary

    def _build_technique_procedures(self, confirmed_techniques: List[Dict]) -> Dict[str, List[str]]:
        """Build technique_id -> procedure descriptions from behavior and evidence."""
        technique_procedures: Dict[str, List[str]] = {}
        for tech in confirmed_techniques:
            tech_id = str(tech.get("id") or "").strip()
            behaviors = tech.get("procedures") or []
            evidences = tech.get("evidence") or []
            if not tech_id:
                continue
            if not isinstance(behaviors, list):
                behaviors = []
            if not isinstance(evidences, list):
                evidences = []

            combined: List[str] = []
            for index in range(max(len(behaviors), len(evidences))):
                behavior = str(behaviors[index]).strip() if index < len(behaviors) else ""
                evidence = str(evidences[index]).strip() if index < len(evidences) else ""
                if behavior and evidence and behavior != evidence:
                    item = f"行为: {behavior}；证据: {evidence}"
                else:
                    item = behavior or evidence
                if item and item not in combined:
                    combined.append(item)

            technique_procedures[tech_id] = combined
        return technique_procedures

    def _extract_ips_from_events(self, events: List[SecurityEvent]) -> Tuple[str, set]:
        """从事件列表中提取IP信息"""
        primary_ip = "unknown"
        ip_list = set()
        for event in events:
            x_real_ip = event.get_x_real_ip()
            if x_real_ip:
                primary_ip = x_real_ip
                ip_list.add(x_real_ip)

            raw_event = event.raw_event
            for attr in ('source_ip', 'dest_ip'):
                ip = getattr(raw_event, attr, None)
                if isinstance(ip, str) and ip.strip():
                    ip_list.add(ip)

        if primary_ip == "unknown" and ip_list:
            primary_ip = list(ip_list)[0]
        return primary_ip, ip_list

    def _convert_investigation_to_short_ttp(
        self,
        investigation_result: Dict[str, Any],
        state: ShortTTPState,
        events: List[SecurityEvent]
    ) -> ShortTTP:
        """将 investigation graph 的结果转换为 ShortTTP 对象

        Args:
            investigation_result: investigation graph 返回的结果
            state: Short TTP 工作流状态
            events: 安全事件列表
        """
        # 从 state 获取 attacker_ip（用于IP分组分析）
        attacker_ip = state.get("attacker_ip")

        final_state = investigation_result.get("state", {})

        # 提取 confirmed_techniques 和 technique_candidates (注: 状态中存储的是 technique_candidates)
        confirmed_techniques = final_state.get("confirmed_techniques", [])
        technique_procedures = self._build_technique_procedures(confirmed_techniques)
        technique_events = final_state.get("technique_events", {})

        logger.debug(f"[DEBUG] 提取到的 technique procedures (行为+证据): {technique_procedures}")
        logger.debug(f"[DEBUG] 确认的技术数量: {len(confirmed_techniques)}")
        logger.debug(f"[DEBUG] technique_events: {technique_events}")

        # 构建 TTP 列表
        tactic_groups = self._build_tactic_groups(confirmed_techniques)
        ttps = self._build_ttp_objects(tactic_groups, technique_procedures, technique_events)

        # 解析摘要
        summary = self._resolve_summary(final_state)

        # 构建攻击者指纹（从事件中提取）
        attacker_fingerprint = self._extract_attacker_fingerprint(events, state)

        # 计算置信度（基于技术数量和证据充分程度）
        confidence = min(0.5 + len(confirmed_techniques) * 0.05, 0.95)

        return ShortTTP(
            id=str(uuid4()),
            created_at=state["window_start"],
            end_at=state["window_end"],
            ttps=ttps,
            confidence=confidence,
            summary=summary,
            event_count=len(events),
            attacker_fingerprint=attacker_fingerprint,
            source_events=[e.event_id for e in events],
            attacker_ip=attacker_ip
        )

    def _extract_attacker_fingerprint(
        self,
        events: List[SecurityEvent],
        state: ShortTTPState
    ) -> Optional[AttackerFingerprint]:
        """从事件中提取攻击者指纹"""
        primary_ip, ip_list = self._extract_ips_from_events(events)

        if primary_ip == "unknown" and not ip_list:
            return None

        return AttackerFingerprint(
            primary_ip=primary_ip,
            ip_list=list(ip_list),
            user_agents=[],
            patterns=[],
            first_seen=state["window_start"],
            last_seen=state["window_end"]
        )
    
class ShortTTPWorkflowFinal:
    """最终的Short TTP工作流管理器"""

    def __init__(self):
        self.workflow = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        """构建优化后的工作流图（3个节点）"""
        workflow = StateGraph(ShortTTPState)

        # 添加节点 - 使用异步版本
        workflow.add_node("collect_events", EventCollectorNode())
        workflow.add_node("analyze_ttp", TTPAnalyzerNode())
        workflow.add_node("validate_result", lambda state: state)  # 简化验证

        # 添加边
        workflow.add_edge("collect_events", "analyze_ttp")
        workflow.add_edge("analyze_ttp", "validate_result")
        workflow.add_edge("validate_result", END)

        # 设置入口点
        workflow.set_entry_point("collect_events")

        # 编译工作流（无需内存检查点）
        return workflow.compile()

    async def analyze_events(self, events: List[SecurityEvent], attacker_ip: Optional[str] = None) -> ShortTTP:
        """分析事件并生成Short TTP

        Args:
            events: 安全事件列表
            attacker_ip: 攻击者IP（可选，用于IP分组分析时）

        Returns:
            ShortTTP对象
        """
        try:
            initial_state = {
                "events": events,
                "window_start": None,
                "window_end": None,
                "analysis_result": None,
                "error": None,
                "attacker_ip": attacker_ip  # 将攻击者IP传入状态
            }

            result = await self.workflow.ainvoke(initial_state)

            if result.get("error"):
                raise ValueError(result["error"])

            return result["analysis_result"]

        except Exception as e:
            logger.error(f"Short TTP分析失败: {str(e)}")
            raise

    
