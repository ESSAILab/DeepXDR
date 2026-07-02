from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    JSON, LargeBinary, String, Text, func
)
from sqlalchemy.orm import relationship
from .connection import Base


class Event(Base):
    """事件表"""
    __tablename__ = "events"
    
    id = Column(String(255), primary_key=True, comment="事件唯一ID")
    event_type = Column(String(50), nullable=False, comment="事件类型")
    source = Column(String(50), nullable=False, comment="事件来源")
    category = Column(String(50), nullable=False, comment="事件类别")
    raw_data = Column(JSON, nullable=False, comment="原始事件数据")
    received_time = Column(DateTime, default=func.now(), comment="接收时间")
    processed = Column(Boolean, default=False, comment="是否已处理")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 索引
    __table_args__ = (
        Index("idx_events_type", "event_type"),
        Index("idx_events_source", "source"),
        Index("idx_events_received_time", "received_time"),
        Index("idx_events_processed", "processed"),
    )
    
    # 关系
    short_ttp_events = relationship("ShortTTPEvent", back_populates="event")
    long_ttp_events = relationship("LongTTPEvent", back_populates="event")


class ShortTTP(Base):
    """短期TTP表"""
    __tablename__ = "short_ttps"
    
    id = Column(String(255), primary_key=True, comment="TTP唯一ID")
    created_at = Column(DateTime, nullable=False, comment="创建时间")
    end_at = Column(DateTime, nullable=False, comment="结束时间")
    confidence = Column(Float, nullable=False, comment="置信度")
    summary = Column(Text, nullable=False, comment="总结")
    event_count = Column(Integer, nullable=False, comment="事件数量")
    source_event_ids = Column(JSON, nullable=False, comment="源事件ID列表")
    ttps_data = Column(JSON, nullable=False, comment="TTP数据")
    raw_analysis_result = Column(JSON, comment="原始分析结果")
    created_at_db = Column(DateTime, default=func.now(), comment="数据库创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 索引
    __table_args__ = (
        Index("idx_short_ttp_created", "created_at"),
        Index("idx_short_ttp_confidence", "confidence"),
    )
    
    # 关系
    events = relationship("ShortTTPEvent", back_populates="short_ttp")
    long_ttp_associations = relationship("LongTTPShortTTP", back_populates="short_ttp")


class LongTTP(Base):
    """长期TTP表"""
    __tablename__ = "long_ttps"
    
    id = Column(String(255), primary_key=True, comment="Long TTP唯一ID")
    created_at = Column(DateTime, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, comment="更新时间")
    analysis_start_time = Column(DateTime, nullable=False, comment="分析开始时间")
    analysis_end_time = Column(DateTime, nullable=False, comment="分析结束时间")
    short_ttps = Column(JSON, nullable=False, comment="包含的Short TTP ID列表")
    summary = Column(Text, nullable=False, comment="总结")
    total_events = Column(Integer, nullable=False, comment="总事件数")
    risk_score = Column(Float, nullable=False, comment="风险评分")
    key_threats = Column(JSON, nullable=False, comment="主要威胁")
    recommendations = Column(JSON, nullable=False, comment="安全建议")
    apts_data = Column(JSON, nullable=False, comment="APT数据")
    raw_analysis_result = Column(JSON, comment="原始分析结果")
    created_at_db = Column(DateTime, default=func.now(), comment="数据库创建时间")
    updated_at_db = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 索引
    __table_args__ = (
        Index("idx_long_ttp_created", "created_at"),
        Index("idx_long_ttp_risk_score", "risk_score"),
        Index("idx_long_ttp_analysis_time", "analysis_start_time", "analysis_end_time"),
    )
    
    # 关系
    events = relationship("LongTTPEvent", back_populates="long_ttp")
    short_ttp_associations = relationship("LongTTPShortTTP", back_populates="long_ttp")


class ShortTTPEvent(Base):
    """短期TTP与事件关联表"""
    __tablename__ = "short_ttp_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    short_ttp_id = Column(String(255), ForeignKey("short_ttps.id"), nullable=False)
    event_id = Column(String(255), ForeignKey("events.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    # 关系
    short_ttp = relationship("ShortTTP", back_populates="events")
    event = relationship("Event", back_populates="short_ttp_events")
    
    # 索引
    __table_args__ = (
        Index("idx_short_ttp_events_ttp", "short_ttp_id"),
        Index("idx_short_ttp_events_event", "event_id"),
        Index("idx_short_ttp_events_created", "created_at"),
    )


class LongTTPEvent(Base):
    """长期TTP与事件关联表"""
    __tablename__ = "long_ttp_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    long_ttp_id = Column(String(255), ForeignKey("long_ttps.id"), nullable=False)
    event_id = Column(String(255), ForeignKey("events.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    # 关系
    long_ttp = relationship("LongTTP", back_populates="events")
    event = relationship("Event", back_populates="long_ttp_events")
    
    # 索引
    __table_args__ = (
        Index("idx_long_ttp_events_ttp", "long_ttp_id"),
        Index("idx_long_ttp_events_event", "event_id"),
        Index("idx_long_ttp_events_created", "created_at"),
    )


class LongTTPShortTTP(Base):
    """长期TTP与短期TTP关联表"""
    __tablename__ = "long_ttp_short_ttps"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    long_ttp_id = Column(String(255), ForeignKey("long_ttps.id"), nullable=False)
    short_ttp_id = Column(String(255), ForeignKey("short_ttps.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    # 关系
    long_ttp = relationship("LongTTP", back_populates="short_ttp_associations")
    short_ttp = relationship("ShortTTP", back_populates="long_ttp_associations")
    
    # 索引
    __table_args__ = (
        Index("idx_long_short_ttp_long", "long_ttp_id"),
        Index("idx_long_short_ttp_short", "short_ttp_id"),
        Index("idx_long_short_ttp_created", "created_at"),
    )


class ProcessingStatus(Base):
    """处理状态跟踪表"""
    __tablename__ = "processing_status"
    
    id = Column(String(255), primary_key=True, comment="处理任务ID")
    task_type = Column(String(50), nullable=False, comment="任务类型")
    status = Column(String(50), nullable=False, comment="处理状态")
    progress = Column(Float, default=0.0, comment="处理进度")
    total_items = Column(Integer, default=0, comment="总项目数")
    processed_items = Column(Integer, default=0, comment="已处理项目数")
    error_message = Column(Text, comment="错误信息")
    started_at = Column(DateTime, default=func.now(), comment="开始时间")
    completed_at = Column(DateTime, comment="完成时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 索引
    __table_args__ = (
        Index("idx_processing_status_type", "task_type"),
        Index("idx_processing_status_status", "status"),
        Index("idx_processing_status_started", "started_at"),
    )


class SystemMetrics(Base):
    """系统指标表"""
    __tablename__ = "system_metrics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    metric_name = Column(String(100), nullable=False, comment="指标名称")
    metric_value = Column(JSON, nullable=False, comment="指标值")
    timestamp = Column(DateTime, default=func.now(), comment="时间戳")
    
    # 索引
    __table_args__ = (
        Index("idx_system_metrics_name", "metric_name"),
        Index("idx_system_metrics_timestamp", "timestamp"),
    )


class LongTTPGeneration(Base):
    """Long TTP 生成会话表"""
    __tablename__ = "long_ttp_generations"

    id = Column(String(255), primary_key=True, comment="Long TTP 生成ID")
    short_ttp_id = Column(String(255), nullable=False, comment="关联的 Short TTP ID")
    session_id = Column(String(255), nullable=False, comment="会话ID")
    thread_id = Column(String(255), nullable=True, comment="LangGraph 线程ID，用于清理 checkpoint")
    status = Column(String(50), nullable=False, comment="生成状态")  # generating/completed/error
    mode = Column(String(20), nullable=False, default="auto", comment="生成模式: auto-自动, feedback-人机反馈")
    final_report = Column(Text, comment="最终报告")
    final_ttps = Column(JSON, comment="TTP 数据")
    feedback_history = Column(JSON, comment="人机反馈历史记录")
    error_message = Column(Text, comment="错误信息")
    started_at = Column(DateTime, nullable=False, comment="开始时间")
    completed_at = Column(DateTime, comment="完成时间")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 索引
    __table_args__ = (
        Index("idx_long_ttp_gen_short_ttp", "short_ttp_id"),
        Index("idx_long_ttp_gen_status", "status"),
        Index("idx_long_ttp_gen_started", "started_at"),
    )


class AgentSession(Base):
    """智能体会话审计表"""
    __tablename__ = "agent_sessions"

    run_id = Column(String(255), primary_key=True, comment="智能体会话运行ID")
    nono_session_id = Column(String(255), nullable=False, comment="nono rollback session ID")
    original_request = Column(Text, nullable=False, comment="用户原始请求")
    agent_command = Column(JSON, comment="智能体命令")
    workspace = Column(Text, nullable=False, comment="工作空间")
    diff_ref = Column(JSON, nullable=False, comment="diff对象存储引用")
    conversation = Column(JSON, comment="智能体对话信息")
    status = Column(String(50), nullable=False, default="received", comment="处理状态")
    rollback_status = Column(String(50), nullable=False, default="not_requested", comment="韧性恢复状态")
    raw_event = Column(JSON, nullable=False, comment="原始会话事件")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_agent_sessions_status", "status"),
        Index("idx_agent_sessions_rollback_status", "rollback_status"),
        Index("idx_agent_sessions_created", "created_at"),
    )


class AgentAdjudication(Base):
    """智能体会话增量裁决表"""
    __tablename__ = "agent_adjudications"

    id = Column(String(255), primary_key=True, comment="裁决ID")
    run_id = Column(String(255), ForeignKey("agent_sessions.run_id"), nullable=False)
    verdict = Column(String(50), nullable=False, comment="裁决结果")
    risk_level = Column(String(50), nullable=False, comment="风险等级")
    out_of_intent = Column(Boolean, nullable=True, comment="是否超出原始意图")
    confidence = Column(Float, nullable=True, comment="置信度")
    summary = Column(Text, nullable=False, comment="裁决摘要")
    findings = Column(JSON, nullable=False, comment="发现列表")
    recommended_action = Column(String(100), nullable=False, comment="推荐动作")
    rollback_recommended = Column(Boolean, default=False, comment="是否建议韧性恢复")
    raw_result = Column(JSON, nullable=False, comment="原始裁决结果")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    __table_args__ = (
        Index("idx_agent_adjudications_run", "run_id"),
        Index("idx_agent_adjudications_verdict", "verdict"),
        Index("idx_agent_adjudications_risk", "risk_level"),
    )


class AgentRollback(Base):
    """智能体会话韧性恢复表"""
    __tablename__ = "agent_rollbacks"

    id = Column(String(255), primary_key=True, comment="恢复请求ID")
    run_id = Column(String(255), ForeignKey("agent_sessions.run_id"), nullable=False)
    nono_session_id = Column(String(255), nullable=False, comment="nono rollback session ID")
    snapshot = Column(Integer, nullable=False, default=0, comment="恢复快照")
    requested_by = Column(String(255), nullable=False, comment="请求人")
    status = Column(String(50), nullable=False, comment="恢复状态")
    command_results = Column(JSON, comment="命令执行结果")
    error_message = Column(Text, comment="错误信息")
    requested_at = Column(DateTime, default=func.now(), comment="请求时间")
    completed_at = Column(DateTime, comment="完成时间")

    __table_args__ = (
        Index("idx_agent_rollbacks_run", "run_id"),
        Index("idx_agent_rollbacks_status", "status"),
        Index("idx_agent_rollbacks_requested", "requested_at"),
    )


class LangGraphCheckpoint(Base):
    """LangGraph checkpoint 持久化表"""
    __tablename__ = "langgraph_checkpoints"

    thread_id = Column(String(255), primary_key=True, comment="线程ID")
    checkpoint_ns = Column(String(255), primary_key=True, default="", comment="命名空间")
    checkpoint_id = Column(String(255), primary_key=True, comment="Checkpoint ID")
    checkpoint_type = Column(String(50), nullable=False, comment="Checkpoint 序列化类型")
    checkpoint_data = Column(LargeBinary, nullable=False, comment="Checkpoint 序列化数据")
    metadata_type = Column(String(50), nullable=False, comment="Metadata 序列化类型")
    metadata_data = Column(LargeBinary, nullable=False, comment="Metadata 序列化数据")
    parent_checkpoint_id = Column(String(255), nullable=True, comment="父 Checkpoint ID")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    # 索引
    __table_args__ = (
        Index("idx_lg_ckpt_thread", "thread_id"),
    )


class LangGraphWrite(Base):
    """LangGraph pending writes 持久化表"""
    __tablename__ = "langgraph_writes"

    thread_id = Column(String(255), primary_key=True, comment="线程ID")
    checkpoint_ns = Column(String(255), primary_key=True, default="", comment="命名空间")
    checkpoint_id = Column(String(255), primary_key=True, comment="Checkpoint ID")
    task_id = Column(String(255), primary_key=True, comment="任务ID")
    write_idx = Column(Integer, primary_key=True, comment="写入索引")
    channel = Column(String(255), nullable=False, comment="通道名称")
    value_type = Column(String(50), nullable=False, comment="值序列化类型")
    value_data = Column(LargeBinary, nullable=False, comment="值序列化数据")
    task_path = Column(String(255), default="", comment="任务路径")


class LangGraphBlob(Base):
    """LangGraph channel value blobs 持久化表"""
    __tablename__ = "langgraph_blobs"

    thread_id = Column(String(255), primary_key=True, comment="线程ID")
    checkpoint_ns = Column(String(255), primary_key=True, default="", comment="命名空间")
    channel = Column(String(255), primary_key=True, comment="通道名称")
    version = Column(String(255), primary_key=True, comment="版本号")
    type_name = Column(String(50), nullable=False, comment="数据类型")
    value_data = Column(LargeBinary, nullable=False, comment="序列化数据")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    # 索引
    __table_args__ = (
        Index("idx_lg_blob_thread", "thread_id"),
    )
