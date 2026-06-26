"""
FastAPI应用主入口
提供REST API接口
"""
from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ttp_generator import DynamicEventWindowManager, ShortTTPGenerator
from api_server.routes import router, set_components

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期管理：启动时恢复对 PENDING session 的超时监控"""
    try:
        from ttp_generator.dx_analyzer_api import (
            HUMAN_FEEDBACK_TIMEOUT_SECONDS,
            _start_auto_feedback_timer,
        )
        from ttp_generator.human_feedback_session import session_manager

        logger.info("人机反馈超时自动继续功能配置: HUMAN_FEEDBACK_TIMEOUT_SECONDS=%d 秒", HUMAN_FEEDBACK_TIMEOUT_SECONDS)
        if HUMAN_FEEDBACK_TIMEOUT_SECONDS > 0:
            pending_sessions = await session_manager.get_pending_sessions()
            logger.info("启动时扫描到 %d 个 PENDING 会话，准备恢复超时监控", len(pending_sessions))
            for session in pending_sessions:
                # 重启后给用户一个新的完整观察窗口（用户可能还没来得及看到新的 question）
                remaining = HUMAN_FEEDBACK_TIMEOUT_SECONDS
                _start_auto_feedback_timer(session.session_id, remaining)
                logger.info(
                    "恢复 session %s 的超时监控，给予新的完整观察窗口 %.0f 秒",
                    session.session_id, remaining
                )
    except Exception as e:
        logger.error("恢复 PENDING 会话超时监控失败: %s", e)

    yield

    # 关闭时取消所有自动反馈定时器
    try:
        from ttp_generator.dx_analyzer_api import _auto_feedback_tasks
        for task in list(_auto_feedback_tasks.values()):
            if not task.done():
                task.cancel()
        logger.info("已取消所有自动反馈定时器")
    except Exception as e:
        logger.error("取消自动反馈定时器失败: %s", e)


def create_app(
    window_manager: DynamicEventWindowManager,
    short_ttp_generator: ShortTTPGenerator
) -> FastAPI:
    """创建FastAPI应用"""

    app = FastAPI(
        title="安全分析系统API",
        description="基于深度行为裁决的AI辅助安全分析系统",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 添加CORS中间件（生产环境应通过环境变量限制来源）
    cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8000").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    # 设置路由组件引用
    set_components(window_manager, short_ttp_generator)

    # 包含API路由
    app.include_router(router)

    return app
