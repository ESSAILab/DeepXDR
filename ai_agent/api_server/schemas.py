from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from shared.utils.timezone import ChinaTime


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    timestamp: datetime
    components: Dict[str, str]


class StatsResponse(BaseModel):
    """统计信息响应"""
    window_stats: Dict
    short_ttp_stats: Dict
    long_ttp_stats: Dict
    system_stats: Dict


class ShortTTPListResponse(BaseModel):
    """短期TTP列表响应"""
    total: int
    items: List[Any]
    timestamp: datetime


class LongTTPListResponse(BaseModel):
    """长期TTP列表响应"""
    total: int
    items: List[Any]
    timestamp: datetime


class TTPDetailResponse(BaseModel):
    """TTP详情响应"""
    data: Optional[Dict]
    timestamp: datetime


class PaginatedResponse(BaseModel):
    """分页响应基类"""
    items: List[Dict]
    total: int
    page: int
    size: int
    pages: int
    has_next: bool
    has_prev: bool
    timestamp: datetime


class SubmitFeedbackRequest(BaseModel):
    """提交反馈请求"""
    feedback: str


class SubmitFeedbackResponse(BaseModel):
    """提交反馈响应"""
    status: str
    message: str
    session_id: str


class TriggerLongTTPResponse(BaseModel):
    """触发长期TTP生成响应"""
    status: str
    message: str
    short_ttp_id: str
    status_url: Optional[str] = None
    timestamp: datetime = Field(default_factory=ChinaTime.now)


class GenerationStatusResponse(BaseModel):
    """生成状态响应"""
    status: str
    message: str
    session_id: Optional[str] = None
    short_ttp_id: str
    generation_status: Optional[str] = None
    is_generating: bool = False  # 流程尚未结束（包括 generating / pending / responded）
    is_completed: bool = False   # 已成功完成
    is_failed: bool = False      # 执行失败或超时
    final_report: Optional[str] = None
    final_ttps: Optional[List] = None
    error_message: Optional[str] = None
    feedback_history: List[FeedbackHistoryItemSchema] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    timestamp: datetime = Field(default_factory=ChinaTime.now)


class LongTTPDetailResponse(BaseModel):
    """Long TTP 详细信息响应"""
    status: str
    message: str
    id: str
    session_id: str
    short_ttp_id: str
    generation_status: str
    mode: Optional[str] = None
    final_report: Optional[str] = None
    final_ttps: Optional[List] = None
    feedback_history: List[FeedbackHistoryItemSchema] = []
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    timestamp: datetime = Field(default_factory=ChinaTime.now)


class LongTTPTriggeredListResponse(BaseModel):
    """Long TTP 触发记录列表响应"""
    status: str
    message: str
    short_ttp_id: str
    long_ttp_count: int
    long_ttp_list: List[Dict[str, Any]]
    timestamp: datetime = Field(default_factory=ChinaTime.now)


class DeleteResponse(BaseModel):
    """删除操作响应"""
    status: str
    message: str
    deleted_id: str
    timestamp: datetime = Field(default_factory=ChinaTime.now)


class FeedbackHistoryItemSchema(BaseModel):
    """人机反馈历史记录项"""
    step: int
    timestamp: datetime
    question: str
    notes_preview: Optional[str] = None
    research_brief: Optional[str] = None
    user_feedback: Optional[str] = None
    status: str  # interrupt / responded
    responded_at: Optional[datetime] = None  # 用户提交反馈的时间


class TriggerLongTTPWithFeedbackResponse(BaseModel):
    """带人机反馈的长期TTP生成响应"""
    status: str
    message: str
    session_id: str
    long_ttp_id: str  # LongTTPGeneration.id，前端占位符用
    short_ttp_id: str
    status_url: str
    timestamp: datetime = Field(default_factory=ChinaTime.now)


class PendingFeedbackItem(BaseModel):
    """待处理反馈项"""
    session_id: str
    short_ttp_id: str
    created_at: datetime
    question: str


class PendingFeedbackListResponse(BaseModel):
    """待处理反馈列表响应"""
    total: int
    items: List[PendingFeedbackItem]
    timestamp: datetime = Field(default_factory=ChinaTime.now)


class FeedbackStatusResponse(BaseModel):
    """反馈状态查询响应"""
    session_id: str
    short_ttp_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    question: Optional[str] = None  # 等待反馈时的问题
    can_submit_feedback: bool = False  # 是否可以提交反馈
    final_report: Optional[str] = None  # 完成的报告
    error_message: Optional[str] = None  # 错误信息
    feedback_history: List[FeedbackHistoryItemSchema] = []  # 人机反馈完整历史


class FeedbackSessionItem(BaseModel):
    """反馈会话列表项"""
    session_id: str
    short_ttp_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    question: Optional[str] = None
    can_submit_feedback: bool = False
    error_message: Optional[str] = None


class FeedbackSessionsListResponse(BaseModel):
    """所有反馈会话列表响应"""
    total: int
    items: List[FeedbackSessionItem]
    timestamp: datetime = Field(default_factory=ChinaTime.now)
