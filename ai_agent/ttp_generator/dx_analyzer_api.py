"""
Open Deep Research API - 支持人机反馈的 Long TTP 生成
使用 LangGraph interrupt 机制的无状态 REST API 架构
交互方法：
  1. 进入容器内部
  nsenter -t $(docker inspect -f '{{.State.Pid}}' security-analysis) -n -F --
  2. 不带人机交互的longttp接口
  curl -X POST http://localhost:8000/trigger-long-ttp/<shorttp-id>
  3. 带人机交互的longttp接口（需配置 LONG_TTP_TRIGGER_API_KEY）
  export LONG_TTP_TRIGGER_API_KEY="replace-with-a-strong-random-trigger-key"
  curl -X POST -H "X-API-Key: $LONG_TTP_TRIGGER_API_KEY" \
    http://localhost:8000/trigger-long-ttp-feedback/<shorttp-id>
  等返回，返回中会携带生成的session_id，人机交互要用到这个session_id
  4. 人机交互API（需配置 HUMAN_FEEDBACK_API_TOKEN，均需 X-Feedback-API-Key）
  export HUMAN_FEEDBACK_API_TOKEN="replace-with-a-strong-random-feedback-token"
  （1）查询状态（显示question）
      curl -H "X-Feedback-API-Key: $HUMAN_FEEDBACK_API_TOKEN" \
        http://localhost:8000/feedback/{session_id}
  （2）提交反馈
      curl -X POST -H "X-Feedback-API-Key: $HUMAN_FEEDBACK_API_TOKEN" \
    -H "Content-Type: application/json" \
    http://localhost:8000/feedback/{session_id}   \
    -d '{"feedback": "请各个专家注意时间线，xxx"}'
  （3）无反馈，继续执行
      curl -X POST -H "X-Feedback-API-Key: $HUMAN_FEEDBACK_API_TOKEN" \
    -H "Content-Type: application/json" \
    http://localhost:8000/feedback/{session_id}  \
    -d '{"feedback": "ok"}'

"""

import asyncio
import json
import os
import time
import traceback
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, AsyncGenerator, List

from ttp_generator.dx_analyzer.state import AnalysisReport, TTP, Technique

from langgraph.types import Command, Interrupt
from uuid import uuid4
from shared.database.checkpointer import PostgresCheckpointSaver

from shared.models.ttp import ShortTTP
from ttp_generator.dx_analyzer.deep_researcher import (
    create_shorttp_triger_longttp_builder
)
from ttp_generator.dx_analyzer.prompts import (
    supervisor_longttp_prompt
)
from .human_feedback_session import (
    FeedbackSession,
    FeedbackStatus,
    session_manager
)

# sj add database --------------------------------------------------------------
from shared.database.elastic_repositories import get_mixed_repository
from shared.utils.timezone import ChinaTime

_DEFAULT_HUMAN_FEEDBACK_QUESTION = "请审核调研结果"
_DEFAULT_NO_REPORT_MSG = "No report generated"

# 全局变量，用于存储 Long TTP Generation ID 到 Session ID 的映射
_generation_id_to_session_id: Dict[str, str] = {}
# 反向映射：Session ID -> Generation ID
_session_id_to_generation_id: Dict[str, str] = {}

# 人机反馈超时自动继续配置
HUMAN_FEEDBACK_TIMEOUT_SECONDS = int(os.getenv("HUMAN_FEEDBACK_TIMEOUT_SECONDS", "1800"))
# 全局超时任务字典：session_id -> asyncio.Task
_auto_feedback_tasks: Dict[str, asyncio.Task] = {}

# Long TTP 生成是高成本的 LLM/工具工作流；对自动/手动触发路径做进程内保护，
# 防止同一 Short TTP 被重复触发或过多不同 Short TTP 同时运行导致资源耗尽。
LONG_TTP_TRIGGER_SUPPRESSION_SECONDS = int(os.getenv("LONG_TTP_TRIGGER_SUPPRESSION_SECONDS", "3600"))
LONG_TTP_MAX_CONCURRENT_GENERATIONS = int(os.getenv("LONG_TTP_MAX_CONCURRENT_GENERATIONS", "2"))
_long_ttp_trigger_lock = asyncio.Lock()
_active_long_ttp_short_ids: set[str] = set()
_last_long_ttp_trigger_times: Dict[str, float] = {}
_active_long_ttp_generation_count = 0


async def _reserve_long_ttp_generation(short_ttp_id: str) -> bool:
    """Reserve capacity for one Long TTP generation if rate/concurrency limits allow it."""
    global _active_long_ttp_generation_count

    now = time.monotonic()
    async with _long_ttp_trigger_lock:
        if short_ttp_id in _active_long_ttp_short_ids:
            logger.warning("[sj] Long TTP 生成已在运行，跳过重复触发: %s", short_ttp_id)
            return False

        last_trigger_time = _last_long_ttp_trigger_times.get(short_ttp_id)
        if (
            last_trigger_time is not None
            and now - last_trigger_time < LONG_TTP_TRIGGER_SUPPRESSION_SECONDS
        ):
            remaining = int(LONG_TTP_TRIGGER_SUPPRESSION_SECONDS - (now - last_trigger_time))
            logger.warning(
                "[sj] Long TTP 触发过于频繁，跳过: %s，剩余冷却时间: %s 秒",
                short_ttp_id,
                remaining,
            )
            return False

        if _active_long_ttp_generation_count >= LONG_TTP_MAX_CONCURRENT_GENERATIONS:
            logger.warning(
                "[sj] Long TTP 并发生成已达上限 %s，跳过触发: %s",
                LONG_TTP_MAX_CONCURRENT_GENERATIONS,
                short_ttp_id,
            )
            return False

        _active_long_ttp_short_ids.add(short_ttp_id)
        _last_long_ttp_trigger_times[short_ttp_id] = now
        _active_long_ttp_generation_count += 1
        return True


async def _release_long_ttp_generation(short_ttp_id: str) -> None:
    """Release a previously reserved Long TTP generation slot."""
    global _active_long_ttp_generation_count

    async with _long_ttp_trigger_lock:
        _active_long_ttp_short_ids.discard(short_ttp_id)
        _active_long_ttp_generation_count = max(0, _active_long_ttp_generation_count - 1)


async def _create_long_ttp_generation_record(
    short_ttp_id: str,
    session_id: str,
    generation_id: str,
    mode: str = "auto",
    thread_id: str = ""
) -> bool:
    """创建 Long TTP 生成记录到数据库"""
    try:
        mixed_repo = await get_mixed_repository()

        generation_data = {
            "id": generation_id,
            "short_ttp_id": short_ttp_id,
            "session_id": session_id,
            "thread_id": thread_id,
            "status": "generating",
            "mode": mode,
            "started_at": ChinaTime.now(),
            "final_report": None,
            "final_ttps": None,
            "feedback_history": [],
            "error_message": None,
            "completed_at": None
        }

        await mixed_repo.create_long_ttp_generation(generation_data)
        # 保存映射关系
        _generation_id_to_session_id[generation_id] = session_id
        _session_id_to_generation_id[session_id] = generation_id
        logger.info(f"[数据库] 创建 Long TTP 生成记录: {generation_id}, 模式: {mode}")
        return True
    except Exception as e:
        logger.error(f"[数据库] 创建 Long TTP 生成记录失败: {e}")
        return False


async def _update_long_ttp_generation_record(
    generation_id: str,
    update_data: Dict[str, Any]
) -> bool:
    """更新 Long TTP 生成记录到数据库"""
    try:
        mixed_repo = await get_mixed_repository()
        await mixed_repo.update_long_ttp_generation(generation_id, update_data)
        logger.info(f"[数据库] 更新 Long TTP 生成记录: {generation_id}")
        return True
    except Exception as e:
        logger.error(f"[数据库] 更新 Long TTP 生成记录失败: {e}")
        return False

# sj add logging start -------------------------------------------------------------
import logging

logger = logging.getLogger(__name__)
# sj add logging end ----------------------------------------------------------------


# 全局 PostgresCheckpointSaver checkpointer 实例
# 使用 PostgreSQL 持久化 checkpoint，支持服务重启后恢复
_checkpointer: Optional[PostgresCheckpointSaver] = None


def get_checkpointer() -> PostgresCheckpointSaver:
    """获取或创建 PostgresCheckpointSaver checkpointer"""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = PostgresCheckpointSaver()
        logger.debug("初始化 PostgresCheckpointSaver checkpointer")
    return _checkpointer


@asynccontextmanager
async def compiled_graph(enable_human_feedback: bool) -> AsyncGenerator[Any, None]:
    """上下文管理器，提供编译好的图

    Args:
        enable_human_feedback: 是否启用人工反馈。True 启用，False 禁用。
    """
    checkpointer = get_checkpointer()
    builder = create_shorttp_triger_longttp_builder(enable_human_feedback=enable_human_feedback)
    graph = builder.compile(checkpointer=checkpointer)
    yield graph


def _create_graph_config(
    thread_id: str,
    enable_human_feedback: bool,
    short_ttp_summary: Optional[str] = None
) -> Dict[str, Any]:
    """创建图执行配置

    Args:
        thread_id: 线程ID
        enable_human_feedback: 是否启用人工反馈。True 启用，False 禁用。
        short_ttp_summary: Short TTP 摘要，用于 human_feedback 节点展示
    """
    configurable = {
        "thread_id": thread_id,
        "search_api": "tavily",
        "allow_clarification": False,
        "max_concurrent_research_units": 5,
        "max_researcher_iterations": 6,
        "max_react_tool_calls": 10,
        "enable_human_feedback": enable_human_feedback,
    }
    if short_ttp_summary is not None:
        configurable["short_ttp_summary"] = short_ttp_summary
    return {"configurable": configurable, "recursion_limit": 60}


def _parse_ttps_from_json(ttps_json: str) -> list:
    """从 JSON 字符串解析 TTP 对象列表"""
    try:
        ttps_data = json.loads(ttps_json)
    except Exception as e:
        logger.error(f"解析 TTP 数据失败: {e}")
        return []

    ttps = []
    for ttp_dict in ttps_data:
        tech_objects = []
        for tech_dict in ttp_dict.get("techniques", []):
            tech = Technique(
                tech_id=tech_dict.get("tech_id", ""),
                tech_name=tech_dict.get("tech_name", ""),
                description=tech_dict.get("description", ""),
                procedures=tech_dict.get("procedures", [])
            )
            tech_objects.append(tech)

        ttp = TTP(
            id=ttp_dict.get("id", ""),
            name=ttp_dict.get("name", ""),
            description=ttp_dict.get("description", ""),
            techniques=tech_objects,
            event_ids=ttp_dict.get("event_ids", [])
        )
        ttps.append(ttp)
    return ttps


def _log_analysis_report_debug(final_result, label: str = "") -> None:
    """打印 AnalysisReport 结构的调试日志"""
    prefix = f"[调试] {label} - " if label else "[调试] "
    logger.debug("=" * 60)
    logger.debug(f"{prefix}最终返回的 AnalysisReport 结构:")
    logger.debug(f"  - 报告内容长度: {len(final_result.final_report)} 字符")
    logger.debug(f"  - TTP 数量: {len(final_result.ttps)} 个")
    for idx, ttp in enumerate(final_result.ttps, 1):
        logger.debug(f"    [{idx}] 战术: {ttp.name} (ID: {ttp.id})")
        logger.debug(f"        描述: {ttp.description[:50]}...")
        logger.debug(f"        包含 {len(ttp.techniques)} 个技术:")
        for tech_idx, tech in enumerate(ttp.techniques, 1):
            logger.debug(f"          [{tech_idx}] {tech.tech_id} - {tech.tech_name}")
            logger.debug(f"              过程数: {len(tech.procedures)}")
    logger.debug("=" * 60)


async def _execute_feedback_graph(short_ttp: ShortTTP, session: FeedbackSession) -> None:
    """执行人机反馈图（后台任务）

    该函数在后台运行，遇到 interrupt 时更新 session 状态，不返回给调用方。
    """
    thread_id = session.thread_id

    # 准备查询内容
    short_ttp_str = short_ttp.model_dump_json(indent=2, ensure_ascii=False)
    prompt_content = supervisor_longttp_prompt.format(
        Short_Term_TTP=short_ttp_str
    )

    short_ttp_summary = f"Short TTP ID: {short_ttp.id}\n\n{short_ttp.summary}"
    config = _create_graph_config(
        thread_id, enable_human_feedback=True, short_ttp_summary=short_ttp_summary
    )
    messages = [{"role": "user", "content": prompt_content}]

    try:
        async with compiled_graph(enable_human_feedback=True) as graph:
            # 启动图执行，short_ttp_summary 通过 config 传递，可穿透子图
            async for event in graph.astream(
                {"messages": messages},
                config,
                stream_mode="updates"
            ):
                # 检查是否遇到 interrupt
                for node_name, node_data in event.items():
                    if node_name == "__interrupt__":
                        logger.info(f"图在 human_feedback 节点暂停，会话: {session.session_id}")

                        # 解析 interrupt 数据
                        interrupt_info = _parse_interrupt_data(node_data)

                        # 更新会话状态
                        await session_manager.update_interrupt_info(
                            session.session_id,
                            interrupt_info,
                            interrupt_info.get("question", _DEFAULT_HUMAN_FEEDBACK_QUESTION)
                        )

                        # 启动自动反馈定时器，超时后自动输入 /continue 继续调查
                        _start_auto_feedback_timer(session.session_id)

                        # 后台任务暂停，等待用户通过 /feedback/{session_id} 提交反馈
                        return

            # 如果没有遇到 interrupt，说明流程已完成
            logger.info(f"图执行完成（无中断），会话: {session.session_id}")

            # 获取最终结果
            final_state = await graph.aget_state(config)
            report = final_state.values.get('final_report', _DEFAULT_NO_REPORT_MSG)
            ttps_json = final_state.values.get('ttps', "[]")

            # 解析 TTP 数据
            ttps = _parse_ttps_from_json(ttps_json)

            # 创建 AnalysisReport 结构
            final_result = AnalysisReport(
                final_report=report,
                ttps=ttps
            )

            # 打印返回结果，方便调试
            _log_analysis_report_debug(final_result, "人机反馈模式")

            # 完成会话，保存完整的 AnalysisReport 或字符串形式
            await session_manager.complete_session(session.session_id, final_result.final_report)

            # 更新数据库记录（优先从 session 取 generation_id，兼容进程重启场景）
            gen_id = _session_id_to_generation_id.get(session.session_id) or session.generation_id
            if gen_id:
                await _update_long_ttp_generation_record(
                    gen_id,
                    {
                        "status": "completed",
                        "final_report": final_result.final_report,
                        "final_ttps": [ttp.model_dump() for ttp in final_result.ttps],
                        "feedback_history": _serialize_feedback_history(session),
                        "completed_at": ChinaTime.now()
                    }
                )

            # 任务完成，清理 checkpoint
            await get_checkpointer().adelete_thread(session.thread_id)
            logger.debug(f"清理 checkpoint，thread: {session.thread_id}")

    except Exception as e:
        logger.error(f"启动 Long TTP 生成失败: {e}")
        await session_manager.fail_session(session.session_id, str(e))
        # 更新数据库状态为失败（优先从 session 取 generation_id，兼容进程重启场景）
        gen_id = _session_id_to_generation_id.get(session.session_id) or session.generation_id
        if gen_id:
            await _update_long_ttp_generation_record(
                gen_id,
                {
                    "status": "error",
                    "error_message": str(e),
                    "feedback_history": _serialize_feedback_history(session),
                    "completed_at": ChinaTime.now()
                }
            )
        raise


async def start_long_ttp_generation_with_feedback(short_ttp: ShortTTP) -> FeedbackSession:
    """
    启动带人机反馈的 Long TTP 生成流程（同步等待模式，向后兼容）

    Args:
        short_ttp: 短期 TTP 对象

    Returns:
        FeedbackSession 会话对象
    """
    session = await start_feedback_session_async(short_ttp)
    # 等待图执行到第一个 interrupt（旧行为兼容）
    while session.status == FeedbackStatus.GENERATING:
        await asyncio.sleep(0.5)
        session = await session_manager.get_session(session.session_id)
        if session is None:
            break
    return session


async def start_feedback_session_async(short_ttp: ShortTTP) -> FeedbackSession:
    """
    创建人机反馈会话并后台启动图执行，立即返回 session_id

    Args:
        short_ttp: 短期 TTP 对象

    Returns:
        FeedbackSession 会话对象（此时图正在后台执行）
    """
    # 创建会话
    thread_id = str(uuid4())
    session = await session_manager.create_session(
        short_ttp_id=str(short_ttp.id),
        thread_id=thread_id
    )
    session.status = FeedbackStatus.GENERATING

    logger.info(f"启动 Long TTP 生成（异步），会话: {session.session_id}, thread: {thread_id}")

    # 创建数据库记录
    generation_id = str(uuid4())
    await _create_long_ttp_generation_record(
        str(short_ttp.id),
        session.session_id,
        generation_id,
        mode="feedback",
        thread_id=thread_id
    )

    # 把 generation_id 挂到 session 上，方便前端使用
    session.generation_id = generation_id
    # 保存 short_ttp_summary，供 resume 时恢复 config 使用
    session.short_ttp_summary = f"Short TTP ID: {short_ttp.id}\n\n{short_ttp.summary}"

    # 保存更新后的 session 到 Redis，确保进程重启后能恢复 generation_id
    await session_manager._save_session(session)

    # 后台启动图执行
    asyncio.create_task(_execute_feedback_graph(short_ttp, session))

    return session


def _serialize_feedback_history(session: FeedbackSession) -> List[Dict[str, Any]]:
    """将 FeedbackSession 的 feedback_history 序列化为可存储的格式"""
    return [
        {
            "step": item.step,
            "timestamp": item.timestamp.isoformat() if item.timestamp else None,
            "question": item.question,
            "notes_preview": item.notes_preview,
            "research_brief": item.research_brief,
            "user_feedback": item.user_feedback,
            "status": item.status,
            "responded_at": item.responded_at.isoformat() if item.responded_at else None,
        }
        for item in session.feedback_history
    ]


def _parse_interrupt_data(node_data: Any) -> Dict[str, Any]:
    """解析 interrupt 数据

    human_feedback_node 中 interrupt() 传入的是字典：
    {
        "question": feedback_request,      # markdown 格式的提示文本
        "notes_preview": findings_summary[:1000],
        "research_brief": research_brief
    }
    """
    # node_data 可能是 Interrupt 对象、字典、列表或元组（stream_mode="updates" 时可能是元组/列表）
    if isinstance(node_data, (list, tuple)) and len(node_data) > 0:
        # 取第一个元素处理
        node_data = node_data[0]

    if isinstance(node_data, Interrupt):
        value = node_data.value
        if isinstance(value, dict):
            return {
                "question": value.get("question", _DEFAULT_HUMAN_FEEDBACK_QUESTION),
                "notes_preview": value.get("notes_preview", ""),
                "research_brief": value.get("research_brief", ""),
                "interrupt_value": value
            }
        return {
            "question": str(value) if value else _DEFAULT_HUMAN_FEEDBACK_QUESTION,
            "interrupt_value": value
        }
    elif isinstance(node_data, dict):
        if "question" in node_data:
            return {
                "question": node_data.get("question", _DEFAULT_HUMAN_FEEDBACK_QUESTION),
                "notes_preview": node_data.get("notes_preview", ""),
                "research_brief": node_data.get("research_brief", ""),
                "interrupt_value": node_data
            }
        return node_data
    else:
        return {"question": str(node_data), "interrupt_value": node_data}


async def _schedule_auto_feedback(session_id: str, delay_seconds: float) -> None:
    """后台任务：等待超时后自动提交 /continue 反馈"""
    try:
        await asyncio.sleep(delay_seconds)
    except asyncio.CancelledError:
        logger.debug("自动反馈定时器已取消，会话: %s", session_id)
        return

    session = await session_manager.get_session(session_id)
    if not session or session.status != FeedbackStatus.PENDING:
        logger.debug("会话已处理，跳过自动反馈，会话: %s", session_id)
        return

    logger.info(
        "会话 %s 超过 %.0f 秒未收到反馈，自动触发继续调查",
        session_id, delay_seconds
    )
    # 先从字典中移除自己，避免 resume_long_ttp_generation 调用 _cancel_auto_feedback_timer 时自我取消
    _auto_feedback_tasks.pop(session_id, None)
    try:
        await resume_long_ttp_generation(session_id, "/continue")
    except asyncio.CancelledError:
        logger.warning("自动反馈任务被取消，会话: %s", session_id)
    except Exception as e:
        logger.error("自动反馈恢复失败，会话 %s: %s", session_id, e)


def _start_auto_feedback_timer(session_id: str, delay_seconds: Optional[float] = None) -> None:
    """启动自动反馈超时定时器"""
    timeout = HUMAN_FEEDBACK_TIMEOUT_SECONDS if delay_seconds is None else delay_seconds
    if timeout <= 0:
        return
    _cancel_auto_feedback_timer(session_id)
    task = asyncio.create_task(_schedule_auto_feedback(session_id, timeout))
    _auto_feedback_tasks[session_id] = task
    logger.debug("启动自动反馈定时器，会话: %s, 超时: %.0f 秒", session_id, timeout)


def _cancel_auto_feedback_timer(session_id: str) -> None:
    """取消自动反馈超时定时器"""
    task = _auto_feedback_tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()
        logger.debug("取消自动反馈定时器，会话: %s", session_id)


async def resume_long_ttp_generation(
    session_id: str,
    feedback: str
) -> FeedbackSession:
    """
    恢复 Long TTP 生成流程

    这是第二阶段：用户使用相同的 thread_id 提交反馈，恢复图执行

    Args:
        session_id: 会话ID
        feedback: 用户反馈内容

    Returns:
        更新后的 FeedbackSession
    """
    # 获取会话
    session = await session_manager.get_session(session_id)
    if not session:
        raise ValueError(f"会话不存在: {session_id}")

    if session.status != FeedbackStatus.PENDING:
        raise ValueError(f"会话状态不是等待反馈，当前: {session.status.value}")

    logger.info(f"恢复 Long TTP 生成，会话: {session_id}, 反馈: {feedback}")

    # 取消可能存在的自动反馈定时器（用户已主动提交）
    _cancel_auto_feedback_timer(session_id)

    # 通过 session_manager 提交反馈，更新 feedback_history 中的状态为 responded
    session = await session_manager.submit_feedback(session_id, feedback)
    if not session:
        raise ValueError(f"提交反馈失败，会话: {session_id}")

    # 恢复执行时也要带上 short_ttp_summary，确保后续 human_feedback 节点能正确展示
    config = _create_graph_config(
        session.thread_id,
        enable_human_feedback=True,
        short_ttp_summary=session.short_ttp_summary
    )

    try:
        # resume_long_ttp_generation 是专门用于人机反馈的流程，强制启用 human_feedback
        logger.debug("开始编译图并恢复执行，会话: %s", session_id)
        async with compiled_graph(enable_human_feedback=True) as graph:
            logger.debug("图已编译，开始 astream，会话: %s", session_id)
            # 使用 Command(resume=...) 恢复图执行
            async for event in graph.astream(
                Command(resume=feedback),
                config,
                stream_mode="updates"
            ):
                logger.debug("收到 event: %s, 会话: %s", list(event.keys()), session_id)
                # 检查是否再次遇到 interrupt（用户可能还需要再次反馈）
                for node_name, node_data in event.items():
                    if node_name == "__interrupt__":
                        logger.info(f"图再次暂停，等待更多反馈，会话: {session_id}")

                        # 解析新的 interrupt 数据
                        interrupt_info = _parse_interrupt_data(node_data)

                        # 更新会话状态为等待反馈
                        session.status = FeedbackStatus.PENDING
                        await session_manager.update_interrupt_info(
                            session_id,
                            interrupt_info,
                            interrupt_info.get("question", _DEFAULT_HUMAN_FEEDBACK_QUESTION)
                        )

                        # 启动自动反馈定时器，防止再次超时
                        _start_auto_feedback_timer(session_id)

                        return session

            # 流程完成
            logger.info(f"图执行完成，会话: {session_id}")

            # 获取最终结果
            final_state = await graph.aget_state(config)
            report = final_state.values.get('final_report', _DEFAULT_NO_REPORT_MSG)
            ttps_json = final_state.values.get('ttps', "[]")

            # 解析 TTP 数据
            ttps = _parse_ttps_from_json(ttps_json)

            # 创建 AnalysisReport 结构
            final_result = AnalysisReport(
                final_report=report,
                ttps=ttps
            )

            # 打印返回结果，方便调试
            _log_analysis_report_debug(final_result, "恢复流程")

            # 完成会话
            await session_manager.complete_session(session_id, final_result.final_report)

            # 更新数据库记录（优先从 session 取 generation_id，兼容进程重启场景）
            gen_id = _session_id_to_generation_id.get(session_id) or session.generation_id
            if gen_id:
                await _update_long_ttp_generation_record(
                    gen_id,
                    {
                        "status": "completed",
                        "final_report": final_result.final_report,
                        "final_ttps": [ttp.model_dump() for ttp in final_result.ttps],
                        "feedback_history": _serialize_feedback_history(session),
                        "completed_at": ChinaTime.now()
                    }
                )

            # 清理 checkpoint
            await get_checkpointer().adelete_thread(session.thread_id)
            logger.debug(f"清理 checkpoint，thread: {session.thread_id}")

            # 获取更新后的会话
            session = await session_manager.get_session(session_id)

            return session

    except Exception as e:
        logger.error("恢复 Long TTP 生成失败，会话: %s, 错误: %s", session_id, e)
        logger.error("详细堆栈:\n%s", traceback.format_exc())
        await session_manager.fail_session(session_id, str(e))
        # 更新数据库状态为失败（优先从 session 取 generation_id，兼容进程重启场景）
        gen_id = _session_id_to_generation_id.get(session_id) or session.generation_id
        if gen_id:
            await _update_long_ttp_generation_record(
                gen_id,
                {
                    "status": "error",
                    "error_message": str(e),
                    "feedback_history": _serialize_feedback_history(session),
                    "completed_at": ChinaTime.now()
                }
            )
        raise


async def get_generation_status(session_id: str) -> Optional[FeedbackSession]:
    """
    获取生成状态

    Args:
        session_id: 会话ID

    Returns:
        会话对象，如果不存在返回 None
    """
    return await session_manager.get_session(session_id)


async def get_status_by_short_ttp(short_ttp_id: str) -> Optional[FeedbackSession]:
    """
    通过 Short TTP ID 查询生成状态和结果

    Args:
        short_ttp_id: 短期 TTP ID

    Returns:
        会话对象，如果不存在返回 None
    """
    return await session_manager.get_session_by_short_ttp(short_ttp_id)


# ==================== 兼容旧接口 ====================

async def trigger_long_ttp_with_feedback(short_ttp: ShortTTP) -> FeedbackSession:
    """
    触发带人机反馈的 Long TTP 生成（兼容旧接口）

    Args:
        short_ttp: 短期 TTP 对象

    Returns:
        人机反馈会话对象
    """
    return await start_long_ttp_generation_with_feedback(short_ttp)


async def submit_user_feedback(session_id: str, feedback: str) -> bool:
    """
    提交用户反馈（兼容旧接口）

    Args:
        session_id: 会话ID
        feedback: 用户反馈内容

    Returns:
        是否成功提交
    """
    try:
        await resume_long_ttp_generation(session_id, feedback)
        return True
    except Exception as e:
        logger.error(f"提交反馈失败: {e}")
        return False


# ==================== 传统同步模式（无人工反馈）====================

async def trigger_long_ttp_generation(short_ttp: ShortTTP) -> str:
    """
    传统的 Long TTP 生成（无人工反馈，向后兼容）

    Args:
        short_ttp: 短期 TTP 对象

    Returns:
        最终报告字符串；如果触发被限流/去重则返回空字符串
    """
    short_ttp_id = str(short_ttp.id)
    if not await _reserve_long_ttp_generation(short_ttp_id):
        return ""

    logger.debug("🔥 触发长时间TTP生成")


    # 创建会话来跟踪生成状态
    thread_id = str(uuid4())
    session = await session_manager.create_session(
        short_ttp_id=str(short_ttp.id),
        thread_id=thread_id
    )
    session.status = FeedbackStatus.GENERATING
    logger.info(f"传统模式 - 会话 {session.session_id} 正在生成中")

    # 创建数据库记录
    generation_id = str(uuid4())
    await _create_long_ttp_generation_record(
        str(short_ttp.id),
        session.session_id,
        generation_id,
        mode="auto",
        thread_id=thread_id
    )

    short_ttp_str = short_ttp.model_dump_json(indent=2, ensure_ascii=False)
    prompt_content = supervisor_longttp_prompt.format(
        Short_Term_TTP=short_ttp_str
    )

    # 传统实现使用 PostgresCheckpointSaver（持久化到 PostgreSQL）
    config = {
        "configurable": {
            "thread_id": thread_id,
            "search_api": "tavily",
            "allow_clarification": False,
            "max_concurrent_research_units": 5,
            "max_researcher_iterations": 6,
            "max_react_tool_calls": 10,
        },
        "recursion_limit": 60  # LangChain 核心配置，默认25
    }

    messages = [{"role": "user", "content": prompt_content}]
    checkpointer = PostgresCheckpointSaver()
    # 传统模式明确禁用 human_feedback
    builder = create_shorttp_triger_longttp_builder(enable_human_feedback=False)
    graph = builder.compile(checkpointer=checkpointer)

    try:
        async for event in graph.astream(
            {"messages": messages},
            config,
            stream_mode="updates"
        ):
            for node_name in event.keys():
                logger.debug(f"节点执行: {node_name}")

        final_state = await graph.aget_state(config)
        report = final_state.values.get('final_report', _DEFAULT_NO_REPORT_MSG)
        ttps_json = final_state.values.get('ttps', "[]")

        # 解析 TTP 数据
        # 尝试解析 TTP JSON
        try:
            ttps_data = json.loads(ttps_json)
            ttps = []
            for ttp_dict in ttps_data:
                # 转换为 Technique 对象
                tech_objects = []
                for tech_dict in ttp_dict.get("techniques", []):
                    tech = Technique(
                        tech_id=tech_dict.get("tech_id", ""),
                        tech_name=tech_dict.get("tech_name", ""),
                        description=tech_dict.get("description", ""),
                        procedures=tech_dict.get("procedures", [])
                    )
                    tech_objects.append(tech)

                ttp = TTP(
                    id=ttp_dict.get("id", ""),
                    name=ttp_dict.get("name", ""),
                    description=ttp_dict.get("description", ""),
                    techniques=tech_objects,
                    event_ids=ttp_dict.get("event_ids", [])
                )
                ttps.append(ttp)
        except Exception as e:
            logger.error(f"解析 TTP 数据失败: {e}")
            ttps = []

        # 创建 AnalysisReport 结构
        final_result = AnalysisReport(
            final_report=report,
            ttps=ttps
        )

        # 打印返回结果，方便调试
        logger.debug("=" * 60)
        logger.debug("[调试] 最终返回的 AnalysisReport 结构:")
        logger.debug(f"  - 报告内容长度: {len(final_result.final_report)} 字符")
        logger.debug(f"  - TTP 数量: {len(final_result.ttps)} 个")
        for idx, ttp in enumerate(final_result.ttps, 1):
            logger.debug(f"    [{idx}] 战术: {ttp.name} (ID: {ttp.id})")
            logger.debug(f"        描述: {ttp.description[:50]}...")
            logger.debug(f"        包含 {len(ttp.techniques)} 个技术:")
            for tech_idx, tech in enumerate(ttp.techniques, 1):
                logger.debug(f"          [{tech_idx}] {tech.tech_id} - {tech.tech_name}")
                logger.debug(f"              过程数: {len(tech.procedures)}")
        logger.debug("=" * 60)

        # 更新会话状态为完成
        await session_manager.complete_session(session.session_id, final_result.final_report)

        # 更新数据库记录
        update_data = {
            "status": "completed",
            "final_report": final_result.final_report,
            "final_ttps": [ttp.model_dump() for ttp in final_result.ttps],
            "completed_at": ChinaTime.now()
        }
        await _update_long_ttp_generation_record(generation_id, update_data)

        # 清理 checkpoint
        await get_checkpointer().adelete_thread(thread_id)
        logger.debug(f"清理 checkpoint，thread: {thread_id}")

        return final_result

    except Exception as e:
        logger.error(f"Long TTP 生成失败: {e}")
        await session_manager.fail_session(session.session_id, str(e))
        # 更新数据库状态为失败
        update_data = {
            "status": "error",
            "error_message": str(e),
            "completed_at": ChinaTime.now()
        }
        await _update_long_ttp_generation_record(generation_id, update_data)
        raise
    finally:
        await _release_long_ttp_generation(short_ttp_id)
