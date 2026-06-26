from __future__ import annotations

import asyncio
import hmac
import logging
import os
from datetime import timedelta
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from shared.utils.timezone import ChinaTime
from shared.models.ttp import ShortTTP
import ttp_generator.dx_analyzer_api as dx_analyzer_api
from ttp_generator.human_feedback_session import (
    session_manager,
    FeedbackStatus,
)

from api_server.schemas import (
    HealthResponse,
    StatsResponse,
    LongTTPListResponse,
    TTPDetailResponse,
    SubmitFeedbackRequest,
    SubmitFeedbackResponse,
    TriggerLongTTPResponse,
    GenerationStatusResponse,
    LongTTPDetailResponse,
    LongTTPTriggeredListResponse,
    DeleteResponse,
    TriggerLongTTPWithFeedbackResponse,
    PaginatedResponse,
    PendingFeedbackItem,
    PendingFeedbackListResponse,
    FeedbackStatusResponse,
    FeedbackHistoryItemSchema,
    FeedbackSessionItem,
    FeedbackSessionsListResponse,
)

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter()

# 全局组件引用（在main.py中设置）
window_manager = None
short_ttp_generator = None


BACKEND_API_KEY_ENV = "BACKEND_API_KEY"


def require_api_key(
    api_key: Optional[str] = Header(default=None, alias="X-API-Key")
) -> None:
    """通用 API Key 校验"""
    expected = os.getenv(BACKEND_API_KEY_ENV, "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=f"API Key 未配置: 设置 {BACKEND_API_KEY_ENV} 环境变量",
        )
    if not api_key or not hmac.compare_digest(api_key.strip(), expected):
        raise HTTPException(status_code=401, detail="Invalid API key")


def set_components(wm, stg):
    """设置全局组件引用"""
    global window_manager, short_ttp_generator
    window_manager = wm
    short_ttp_generator = stg


def calculate_pagination(total: int, page: int, size: int) -> Dict:
    """计算分页信息"""
    pages = (total + size - 1) // size
    has_next = page < pages
    has_prev = page > 1
    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "has_next": has_next,
        "has_prev": has_prev
    }


def _long_ttp_store_unavailable(message: str) -> HTTPException:
    logger.exception(message)
    return HTTPException(status_code=503, detail="Long TTP 存储服务不可用")


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查接口"""
    components = {
        "window_manager": "healthy" if window_manager else "unhealthy",
        "short_ttp_generator": "healthy" if short_ttp_generator else "unhealthy"
    }
    return HealthResponse(
        status="healthy",
        timestamp=ChinaTime.now(),
        components=components
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """获取系统统计信息"""
    try:
        window_stats = await window_manager.get_window_stats()
        short_ttp_stats = await short_ttp_generator.get_generation_stats()
        system_stats = {
            "uptime": ChinaTime.now().isoformat(),
            "timestamp": ChinaTime.now()
        }
        return StatsResponse(
            window_stats=window_stats,
            short_ttp_stats=short_ttp_stats,
            long_ttp_stats={},
            system_stats=system_stats
        )
    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/short-ttp", response_model=PaginatedResponse)
async def get_short_ttps(
    hours: int = Query(default=24, ge=1, le=168, description="查询时间范围（小时）"),
    min_confidence: float = Query(default=0.5, ge=0.0, le=1.0),
    page: int = Query(default=1, ge=1, description="页码"),
    size: int = Query(default=10, ge=1, le=100, description="每页大小"),
    sort_by: str = Query(default="created_at", regex="^(created_at|created_at_db|confidence|event_count)$"),
    sort_order: str = Query(default="desc", regex="^(asc|desc)$")
):
    """分页获取短期TTP列表"""
    try:
        # API请求日志已禁用，避免日志过多
        offset = (page - 1) * size
        from shared.database.elastic_repositories import get_mixed_repository
        mixed_repo = await get_mixed_repository()
        es_repo = mixed_repo.get_short_ttp_repository()
        end_time = ChinaTime.now()
        start_time = end_time - timedelta(hours=hours)
        result = await es_repo.get_short_ttps(
            offset=offset, limit=size, start_time=start_time, end_time=end_time,
            min_confidence=min_confidence
        )
        total = result.get("total", 0)
        pagination = calculate_pagination(total, page, size)
        return {**pagination, "items": result.get("items", []), "timestamp": ChinaTime.now()}
    except Exception as e:
        logger.error(f"获取短期TTP列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/short-ttp/{ttp_id}", response_model=TTPDetailResponse)
async def get_short_ttp_detail(ttp_id: str):
    """获取短期TTP详情"""
    try:
        ttp = await short_ttp_generator.get_short_ttp_by_id(ttp_id)
        if not ttp:
            raise HTTPException(status_code=404, detail="短期TTP未找到")
        return TTPDetailResponse(data=ttp.model_dump(), timestamp=ChinaTime.now())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取短期TTP详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/longttp",
    response_model=PaginatedResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_long_ttps(
    hours: Optional[int] = Query(default=None, ge=1, le=720, description="查询时间范围（小时），不传则查询所有历史数据"),
    min_confidence: float = Query(default=0.0, ge=0.0, description="最低风险评分（LongTTPGeneration无此字段，暂忽略）"),
    page: int = Query(default=1, ge=1, description="页码"),
    size: int = Query(default=10, ge=1, le=100, description="每页大小"),
    sort_by: str = Query(default="created_at", regex="^(created_at|started_at|status)$"),
    sort_order: str = Query(default="desc", regex="^(asc|desc)$")
):
    """分页获取 Long TTP 生成记录列表"""
    try:
        from shared.database.elastic_repositories import get_mixed_repository
        mixed_repo = await get_mixed_repository()
        result = await mixed_repo.get_long_ttp_generations(
            hours=hours,
            page=page,
            size=size,
            sort_by=sort_by,
            sort_order=sort_order
        )
        total = result.get("total", 0)
        pagination = calculate_pagination(total, page, size)
        return {
            **pagination,
            "items": [
                {
                    "id": r.id,
                    "short_ttp_id": r.short_ttp_id,
                    "session_id": r.session_id,
                    "generation_status": r.status,
                    "mode": r.mode,
                    "final_report": r.final_report,
                    "final_ttps": r.final_ttps,
                    "error_message": r.error_message,
                    "feedback_history": r.feedback_history or [],
                    "started_at": r.started_at,
                    "completed_at": r.completed_at,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                }
                for r in result.get("items", [])
            ],
            "timestamp": ChinaTime.now()
        }
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _long_ttp_store_unavailable("获取长期TTP列表失败")
    except Exception as e:
        logger.exception(f"获取长期TTP列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-risk", response_model=LongTTPListResponse)
async def get_top_risk_ttps(
    limit: int = Query(default=10, ge=1, le=100),
    hours: int = Query(default=24, ge=1, le=168)
):
    """获取高风险的长期TTP"""
    try:
        from shared.database.repositories import TTPRepository
        from shared.database.connection import get_db, get_redis
        async with get_db() as db:
            redis = get_redis()
            ttp_repo = TTPRepository(db, redis)
            ttps = await ttp_repo.get_top_risk_long_ttps(limit=limit, hours=hours)
        return LongTTPListResponse(
            total=len(ttps), items=ttps, timestamp=ChinaTime.now()
        )
    except Exception as e:
        logger.error(f"获取高风险TTP失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/trigger-long-ttp/{short_ttp_id}",
    response_model=TriggerLongTTPResponse,
    dependencies=[Depends(require_api_key)],
)
async def trigger_long_ttp_api(short_ttp_id: str):
    """手动触发长期TTP生成"""
    try:
        from shared.database.elastic_repositories import get_mixed_repository
        mixed_repo = await get_mixed_repository()
        es_repo = mixed_repo.get_short_ttp_repository()
        result = await es_repo.get_short_ttp_by_id(short_ttp_id)
        if not result:
            raise HTTPException(status_code=404, detail="Short TTP未找到")
        short_ttp = ShortTTP.model_validate(result)
        logger.info(f"手动触发长期TTP生成: {short_ttp_id}")
        use_mitre = os.getenv("USE_MITRE_INVESTIGATION_SUBGRAPH", "false").lower() == "true"
        message = "长期TTP生成已触发（使用MITRE调查）" if use_mitre else "长期TTP生成已触发"
        asyncio.create_task(dx_analyzer_api.trigger_long_ttp_generation(short_ttp))
        return TriggerLongTTPResponse(
            status="success", message=message, short_ttp_id=short_ttp_id,
            status_url=f"/gen-longttp-status/{short_ttp_id}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"手动触发长期TTP生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"触发失败: {str(e)}")


def _build_db_feedback_history(record):
    """从数据库记录解析 feedback history"""
    if not record or not record.feedback_history:
        return []
    from datetime import datetime
    feedback_history = []
    for item in record.feedback_history:
        ts = item.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                logger.exception("解析 feedback 历史时间戳失败: %r", ts)
                ts = None
        feedback_history.append(FeedbackHistoryItemSchema(
            step=item.get("step", 0), timestamp=ts,
            question=item.get("question", ""),
            notes_preview=item.get("notes_preview"),
            research_brief=item.get("research_brief"),
            user_feedback=item.get("user_feedback"),
            status=item.get("status", "interrupt"),
            responded_at=item.get("responded_at"),
        ))
    return feedback_history


@router.get(
    "/gen-longttp-status/{short_ttp_id}",
    response_model=GenerationStatusResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_generation_status_api(short_ttp_id: str):
    """查询 Long TTP 生成状态和结果"""
    try:
        session = await dx_analyzer_api.get_status_by_short_ttp(short_ttp_id)

        # 路径1：无活跃 session，尝试从数据库 fallback
        if not session:
            try:
                from shared.database.elastic_repositories import get_mixed_repository
                mixed_repo = await get_mixed_repository()
                record = await mixed_repo.get_recent_long_ttp_generation_by_short_ttp(short_ttp_id)
                if record:
                    feedback_history = _build_db_feedback_history(record)
                    return GenerationStatusResponse(
                        status="success", message="已找到数据库中的生成记录",
                        session_id=record.session_id, short_ttp_id=short_ttp_id,
                        generation_status=record.status,
                        is_generating=record.status == "generating",
                        is_completed=record.status == "completed",
                        is_failed=record.status == "error",
                        final_report=record.final_report, final_ttps=record.final_ttps,
                        error_message=record.error_message, feedback_history=feedback_history,
                        created_at=record.created_at, updated_at=record.updated_at
                    )
            except SQLAlchemyError:
                raise _long_ttp_store_unavailable("查询数据库中的 Long TTP 生成记录失败")
            except (ValueError, TypeError, AttributeError):
                logger.exception("解析数据库中的 Long TTP 生成记录失败: short_ttp_id=%s", short_ttp_id)
                raise HTTPException(status_code=500, detail="Long TTP 数据格式错误")
            except Exception:
                logger.exception("查询 Long TTP 生成状态 fallback 失败: short_ttp_id=%s", short_ttp_id)
                raise HTTPException(status_code=500, detail="查询 Long TTP 生成状态失败")
            return GenerationStatusResponse(
                status="success", message="尚未触发 Long TTP 生成",
                short_ttp_id=short_ttp_id, is_generating=False, is_completed=False, is_failed=False
            )

        # 路径2：有活跃 session，按需加载 final_ttps
        final_ttps = None
        if session.status == FeedbackStatus.COMPLETED and session.generation_id:
            try:
                from shared.database.elastic_repositories import get_mixed_repository
                mixed_repo = await get_mixed_repository()
                record = await mixed_repo.get_long_ttp_generation_by_id(session.generation_id)
                final_ttps = record.final_ttps if record else None
            except SQLAlchemyError:
                raise _long_ttp_store_unavailable("加载已完成 Long TTP 结果失败")
            except (ValueError, TypeError, AttributeError):
                logger.exception("解析已完成 Long TTP 结果失败: generation_id=%s", session.generation_id)
                raise HTTPException(status_code=500, detail="Long TTP 数据格式错误")
            except Exception:
                logger.exception("加载已完成 Long TTP 结果失败: generation_id=%s", session.generation_id)
                raise HTTPException(status_code=500, detail="加载 Long TTP 结果失败")

        is_generating = session.status in (FeedbackStatus.GENERATING, FeedbackStatus.PENDING, FeedbackStatus.RESPONDED)
        is_completed = session.status == FeedbackStatus.COMPLETED
        is_failed = session.status in (FeedbackStatus.ERROR, FeedbackStatus.TIMEOUT)

        status_messages = {
            FeedbackStatus.GENERATING: "正在生成中...",
            FeedbackStatus.PENDING: "等待用户反馈",
            FeedbackStatus.RESPONDED: "正在恢复执行...",
            FeedbackStatus.COMPLETED: "生成完成",
            FeedbackStatus.ERROR: "执行出错",
            FeedbackStatus.TIMEOUT: "执行超时",
        }

        return GenerationStatusResponse(
            status="success", message=status_messages.get(session.status, "未知状态"),
            session_id=session.session_id, short_ttp_id=short_ttp_id,
            generation_status=session.status.value if session.status else None,
            is_generating=is_generating, is_completed=is_completed, is_failed=is_failed,
            final_report=session.final_report, final_ttps=final_ttps,
            error_message=session.error_message,
            feedback_history=[
                FeedbackHistoryItemSchema(
                    step=item.step, timestamp=item.timestamp,
                    question=item.question, notes_preview=item.notes_preview,
                    research_brief=item.research_brief,
                    user_feedback=item.user_feedback, status=item.status,
                    responded_at=item.responded_at,
                )
                for item in session.feedback_history
            ],
            created_at=session.created_at, updated_at=session.updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"查询生成状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get(
    "/get-all-triggered-longttp/{short_ttp_id}",
    response_model=LongTTPTriggeredListResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_all_triggered_longttp_api(short_ttp_id: str):
    """获取该short TTP触发的所有long TTP记录列表"""
    try:
        from shared.database.elastic_repositories import get_mixed_repository
        mixed_repo = await get_mixed_repository()
        records = await mixed_repo.get_all_long_ttp_generations_by_short_ttp(short_ttp_id)
        long_ttp_list = [{
            "id": r.id, "session_id": r.session_id,
            "generation_status": r.status, "mode": r.mode,
            "started_at": r.started_at, "completed_at": r.completed_at
        } for r in records]
        return LongTTPTriggeredListResponse(
            status="success", message=f"共找到 {len(long_ttp_list)} 条记录",
            short_ttp_id=short_ttp_id, long_ttp_count=len(long_ttp_list),
            long_ttp_list=long_ttp_list
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _long_ttp_store_unavailable("查询指定 Short TTP 触发的 Long TTP 记录失败")
    except Exception as e:
        logger.exception(f"查询失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get(
    "/longttp/{long_ttp_id}",
    response_model=LongTTPDetailResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_longttp_detail_api(long_ttp_id: str):
    """获取指定long TTP的详细信息"""
    try:
        from shared.database.elastic_repositories import get_mixed_repository
        mixed_repo = await get_mixed_repository()
        record = await mixed_repo.get_long_ttp_generation_by_id(long_ttp_id)
        if not record:
            raise HTTPException(status_code=404, detail="Long TTP记录不存在")
        # 解析数据库中的 feedback_history
        feedback_history = []
        if record.feedback_history:
            from datetime import datetime
            for item in record.feedback_history:
                ts = item.get("timestamp")
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except ValueError:
                        logger.exception("解析 Long TTP feedback 历史时间戳失败: %r", ts)
                        ts = None
                feedback_history.append(FeedbackHistoryItemSchema(
                    step=item.get("step", 0),
                    timestamp=ts,
                    question=item.get("question", ""),
                    notes_preview=item.get("notes_preview"),
                    research_brief=item.get("research_brief"),
                    user_feedback=item.get("user_feedback"),
                    status=item.get("status", "interrupt"),
                    responded_at=item.get("responded_at"),
                ))

        return LongTTPDetailResponse(
            status="success", message="已找到记录", id=record.id,
            session_id=record.session_id, short_ttp_id=record.short_ttp_id,
            generation_status=record.status, mode=record.mode, final_report=record.final_report,
            final_ttps=record.final_ttps, feedback_history=feedback_history,
            error_message=record.error_message,
            started_at=record.started_at, completed_at=record.completed_at,
            created_at=record.created_at, updated_at=record.updated_at
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _long_ttp_store_unavailable("查询 Long TTP 详情失败")
    except Exception as e:
        logger.exception(f"查询失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.delete("/longttp/{long_ttp_id}", response_model=DeleteResponse)
async def delete_longttp_api(
    long_ttp_id: str,
    _authorized: None = Depends(require_api_key),
):
    """删除指定的long TTP记录"""
    try:
        from shared.database.elastic_repositories import get_mixed_repository
        mixed_repo = await get_mixed_repository()
        record = await mixed_repo.get_long_ttp_generation_by_id(long_ttp_id)
        if not record:
            raise HTTPException(status_code=404, detail="Long TTP记录不存在")

        # 校验：正在执行中的任务不允许删除
        if record.short_ttp_id:
            session = await session_manager.get_session_by_short_ttp(record.short_ttp_id)
            if session and session.status in (FeedbackStatus.GENERATING, FeedbackStatus.RESPONDED):
                raise HTTPException(
                    status_code=400,
                    detail=f"任务正在执行中（{session.status.value}），请等待完成或到达中断点后再删除"
                )

        # 同时清理关联的 checkpoint
        if record.thread_id:
            from shared.database.checkpointer import PostgresCheckpointSaver
            checkpointer = PostgresCheckpointSaver()
            await checkpointer.adelete_thread(record.thread_id)
            logger.info(f"删除 long ttp 时清理 checkpoint，thread: {record.thread_id}")

        # 清理关联的 Redis session（通过 short_ttp_id）
        if record.short_ttp_id:
            session = await session_manager.get_session_by_short_ttp(record.short_ttp_id)
            if session:
                await session_manager.delete_session(session.session_id)
                logger.info(f"删除 long ttp 时清理 Redis session，short_ttp: {record.short_ttp_id}")

        success = await mixed_repo.delete_long_ttp_generation(long_ttp_id)
        if not success:
            raise HTTPException(status_code=500, detail="删除失败")
        return DeleteResponse(
            status="success", message="删除成功", deleted_id=long_ttp_id
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _long_ttp_store_unavailable("删除 Long TTP 前查询记录失败")
    except Exception as e:
        logger.exception(f"删除失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.post(
    "/trigger-long-ttp-feedback/{short_ttp_id}",
    response_model=TriggerLongTTPWithFeedbackResponse,
    dependencies=[Depends(require_api_key)],
)
async def trigger_long_ttp_with_feedback_api(short_ttp_id: str):
    """触发带人机反馈的长期TTP生成"""
    try:
        from shared.database.elastic_repositories import get_mixed_repository
        mixed_repo = await get_mixed_repository()
        es_repo = mixed_repo.get_short_ttp_repository()
        result = await es_repo.get_short_ttp_by_id(short_ttp_id)
        if not result:
            raise HTTPException(status_code=404, detail="Short TTP未找到")
        short_ttp = ShortTTP.model_validate(result)
        logger.info(f"启动带人机反馈的长期TTP生成: {short_ttp_id}")
        session = await dx_analyzer_api.start_feedback_session_async(short_ttp)
        return TriggerLongTTPWithFeedbackResponse(
            status="success", message="带人机反馈的长期TTP生成已启动（异步执行）",
            session_id=session.session_id,
            long_ttp_id=session.generation_id or "",
            short_ttp_id=short_ttp_id,
            status_url=f"/feedback/{session.session_id}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


@router.get(
    "/feedback/pending/list",
    response_model=PendingFeedbackListResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_pending_feedback_list():
    """获取所有等待用户反馈的会话列表"""
    try:
        pending_sessions = await session_manager.get_pending_sessions()
        items = [PendingFeedbackItem(
            session_id=s.session_id, short_ttp_id=s.short_ttp_id,
            created_at=s.created_at, question=s.interrupt_question or "请审核调研结果"
        ) for s in pending_sessions]
        return PendingFeedbackListResponse(
            total=len(items), items=items
        )
    except Exception as e:
        logger.error(f"获取待处理反馈列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取列表失败: {str(e)}")


@router.get(
    "/feedback/sessions",
    response_model=FeedbackSessionsListResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_all_feedback_sessions():
    """获取所有 feedback 会话列表（包括正在生成、等待反馈、已完成等所有状态）"""
    try:
        sessions = await session_manager.get_all_sessions()
        items = [FeedbackSessionItem(
            session_id=s.session_id,
            short_ttp_id=s.short_ttp_id,
            status=s.status.value,
            created_at=s.created_at,
            updated_at=s.updated_at,
            question=s.interrupt_question if s.status == FeedbackStatus.PENDING else None,
            can_submit_feedback=s.status == FeedbackStatus.PENDING,
            error_message=s.error_message if s.status == FeedbackStatus.ERROR else None
        ) for s in sessions]
        return FeedbackSessionsListResponse(total=len(items), items=items)
    except Exception as e:
        logger.error(f"获取 feedback 会话列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取列表失败: {str(e)}")


@router.get(
    "/feedback/{session_id}",
    response_model=FeedbackStatusResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_feedback_status(session_id: str):
    """查询人机反馈会话状态"""
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        return FeedbackStatusResponse(
            session_id=session.session_id, short_ttp_id=session.short_ttp_id,
            status=session.status.value, created_at=session.created_at,
            updated_at=session.updated_at,
            question=session.interrupt_question if session.status == FeedbackStatus.PENDING else None,
            can_submit_feedback=session.status == FeedbackStatus.PENDING,
            final_report=session.final_report if session.status == FeedbackStatus.COMPLETED else None,
            error_message=session.error_message if session.status == FeedbackStatus.ERROR else None,
            feedback_history=[
                FeedbackHistoryItemSchema(
                    step=item.step,
                    timestamp=item.timestamp,
                    question=item.question,
                    notes_preview=item.notes_preview,
                    research_brief=item.research_brief,
                    user_feedback=item.user_feedback,
                    status=item.status,
                    responded_at=item.responded_at,
                )
                for item in session.feedback_history
            ]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询反馈状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.post(
    "/feedback/{session_id}",
    response_model=SubmitFeedbackResponse,
    dependencies=[Depends(require_api_key)],
)
async def submit_feedback(session_id: str, request: SubmitFeedbackRequest):
    """提交人机反馈"""
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.status != FeedbackStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"会话状态不是等待反馈状态，当前状态: {session.status.value}"
            )
        # 后台启动图恢复，立即返回
        asyncio.create_task(dx_analyzer_api.resume_long_ttp_generation(session_id, request.feedback))
        return SubmitFeedbackResponse(
            status="success", message="反馈已提交，正在后台处理", session_id=session_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交反馈失败: {e}")
        raise HTTPException(status_code=500, detail=f"提交失败: {str(e)}")


@router.get("/queue-stats", response_model=Dict)
async def get_queue_stats():
    """获取处理队列统计信息"""
    try:
        short_ttp_queue_stats = short_ttp_generator.get_queue_stats()
        return {"short_ttp_queue": short_ttp_queue_stats, "timestamp": ChinaTime.now()}
    except Exception as e:
        logger.error(f"获取队列统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events/{event_id}", response_model=TTPDetailResponse)
async def get_event_detail(event_id: str):
    """获取事件详情"""
    try:
        from shared.database.elastic_repositories import get_event_es_repository
        event_es_repo = await get_event_es_repository()
        event = await event_es_repo.get_event_by_id(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="事件未找到")
        return TTPDetailResponse(data=event, timestamp=ChinaTime.now())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取事件详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events")
async def get_events(
    event_ids: str = Query(None, description="逗号分隔的事件ID列表"),
    page: int = Query(default=1, ge=1, description="页码"),
    size: int = Query(default=10, ge=1, le=100, description="每页大小"),
    hours: int = Query(default=24, ge=1, le=168, description="时间范围(小时)"),
    event_types: str = Query(None, description="逗号分隔的事件类型"),
    sources: str = Query(None, description="逗号分隔的事件来源")
):
    """分页获取事件列表"""
    try:
        from shared.database.elastic_repositories import get_event_es_repository
        offset = (page - 1) * size
        event_type_list = [et.strip() for et in event_types.split(",")] if event_types else None
        source_list = [s.strip() for s in sources.split(",")] if sources else None
        event_es_repo = await get_event_es_repository()
        if event_ids:
            event_id_list = event_ids.split(",")[:size]
            events = []
            for event_id in event_id_list:
                event = await event_es_repo.get_event_by_id(event_id.strip())
                if event:
                    events.append(event)
            pagination = calculate_pagination(len(events), page, size)
            return {**pagination, "items": events, "timestamp": ChinaTime.now()}
        result = await event_es_repo.search_events(
            hours=hours, event_types=event_type_list, sources=source_list,
            offset=offset, limit=size
        )
        pagination = calculate_pagination(result["total"], page, size)
        return {**pagination, "items": result["items"], "timestamp": ChinaTime.now()}
    except Exception as e:
        logger.error(f"获取事件列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard")
async def get_dashboard_data():
    """获取仪表板数据"""
    try:
        window_stats = await window_manager.get_window_stats()
        short_ttp_stats = await short_ttp_generator.get_generation_stats()
        recent_short_ttps = await short_ttp_generator.get_recent_short_ttps(hours=1, limit=5)
        from shared.database.repositories import TTPRepository
        from shared.database.connection import get_db, get_redis
        async with get_db() as db:
            redis = get_redis()
            ttp_repo = TTPRepository(db, redis)
            recent_long_ttps = await ttp_repo.get_recent_long_ttps(hours=1, limit=5)
            top_risk_ttps = await ttp_repo.get_top_risk_long_ttps(limit=5, hours=24)
            long_ttp_stats = {
                "recent_count": len(recent_long_ttps),
                "high_risk_count": len([t for t in top_risk_ttps if t.risk_score >= 8.0])
            }
        return {
            "stats": {"windows": window_stats, "short_ttp": short_ttp_stats, "long_ttp": long_ttp_stats},
            "recent_short_ttps": [t.model_dump() for t in recent_short_ttps],
            "recent_long_ttps": [t.model_dump() for t in recent_long_ttps],
            "top_risk_ttps": [t.model_dump() for t in top_risk_ttps],
            "timestamp": ChinaTime.now()
        }
    except Exception as e:
        logger.error(f"获取仪表板数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
