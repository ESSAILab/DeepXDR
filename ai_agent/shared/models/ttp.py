"""
TTP数据模型定义
基于MITRE ATT&CK框架的战术技术程序模型
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Technique(BaseModel):
    """技术层级"""
    tech_id: str = Field(..., description="技术ID，如T1059")
    tech_name: str = Field(..., description="技术名称")
    description: str = Field(..., description="技术描述")
    procedures: List[str] = Field(..., description="关联的过程描述列表，需要引用具体事件字段作为证据，包含攻击者IP、行为特征、攻击的目标、攻击链等信息")
    event_ids: List[str] = Field(..., description="与该技术有关的事件ID列表，从而可以追溯到具体的事件数据")


class TTP(BaseModel):
    """战术技术程序"""
    id: str = Field(..., description="战术ID，如TA0001")
    name: str = Field(..., description="战术名称")
    description: str = Field(..., description="战术描述")
    techniques: List[Technique] = Field(..., description="包含的技术列表")
    event_ids: List[str] = Field(..., description="与该战术有关的事件ID列表，从而可以追溯到具体的事件数据")


class ShortTTP(BaseModel):
    """短期TTP分析结果"""
    id: str = Field(..., description="唯一TTP标识")
    created_at: datetime = Field(..., description="TTP创建时间，窗口内最早事件时间")
    end_at: datetime = Field(..., description="TTP结束时间，窗口内最晚事件时间")
    ttps: List[TTP] = Field(..., description="攻击步骤列表")
    confidence: float = Field(..., ge=0, le=1, description="置信度评分")
    summary: str = Field(..., description="人工可读总结")
    event_count: int = Field(..., description="包含的事件数量")
    source_events: List[str] = Field(..., description="源事件ID列表")
    attacker_fingerprint: Optional[AttackerFingerprint] = Field(None, description="提取攻击者指纹")
    attacker_ip: Optional[str] = Field(None, description="攻击者IP地址（窗口分组分析时使用）")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    def to_es_document(self) -> Dict[str, Any]:
        """转换为ElasticSearch文档格式"""
        doc = self.model_dump()
        # ES需要的默认字段
        doc.update({
            "@timestamp": self.created_at.isoformat(),
            "window_start": self.created_at.isoformat(),
            "window_end": self.end_at.isoformat()
        })
        return doc

    @classmethod
    def from_es_document(cls, doc: Dict[str, Any]) -> 'ShortTTP':
        """从ElasticSearch文档创建ShortTTP"""
        # 清理ES内部字段，保留业务数据
        es_internal_fields = ['@timestamp', '_id', '_index', '_score', 'window_start', 'window_end']
        cleaned_doc = {k: v for k, v in doc.items() if k not in es_internal_fields}

        return cls.model_validate(cleaned_doc)

class AttackerFingerprint(BaseModel):
    """攻击者指纹信息"""
    primary_ip: str = Field(..., description="主要IP地址")
    ip_list: List[str] = Field(..., description="相关IP地址列表")
    user_agents: List[str] = Field(..., description="User-Agent列表")
    patterns: List[str] = Field(..., description="行为模式特征")
    first_seen: datetime = Field(..., description="首次出现时间")
    last_seen: datetime = Field(..., description="最后出现时间")


class Apt(BaseModel):
    """APT攻击链"""
    id: str = Field(..., description="APT唯一标识")
    name: str = Field(..., description="APT名称")
    description: str = Field(..., description="详细描述")
    attacker_fingerprint: AttackerFingerprint = Field(..., description="攻击者指纹")
    ttps: List[TTP] = Field(..., description="关联的TTP列表")
    short_ttp_ids: List[str] = Field(..., description="关联的Short TTP ID列表")
    attack_chain: List[str] = Field(..., description="攻击链步骤描述")
    objectives: List[str] = Field(..., description="攻击目标")
    severity: str = Field(..., description="严重程度")
    confidence: float = Field(..., ge=0, le=1, description="置信度")
    first_activity: datetime = Field(..., description="首次活动时间")
    last_activity: datetime = Field(..., description="最后活动时间")
    affected_systems: List[str] = Field(..., description="受影响系统")


class LongTTP(BaseModel):
    """长期TTP分析结果"""
    id: str = Field(..., description="唯一Long TTP标识")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    analysis_start_time: datetime = Field(..., description="分析开始时间")
    analysis_end_time: datetime = Field(..., description="分析结束时间")
    short_ttps: List[str] = Field(..., description="包含的Short TTP ID列表")
    summary: str = Field(..., description="人工可读总结")
    apts: List[Apt] = Field(..., description="APT攻击链列表")
    total_events: int = Field(..., description="总事件数量")
    risk_score: float = Field(..., ge=0, le=10, description="风险评分")
    key_threats: List[str] = Field(..., description="主要威胁列表")
    recommendations: List[str] = Field(..., description="安全建议")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TTPAnalysisRequest(BaseModel):
    """TTP分析请求"""
    event_ids: List[str] = Field(..., description="要分析的事件ID列表")
    analysis_type: str = Field(..., description="分析类型：short或long")
    

class TTPAnalysisResponse(BaseModel):
    """TTP分析响应"""
    success: bool = Field(..., description="是否成功")
    short_ttp: Optional[ShortTTP] = Field(None, description="Short TTP结果")
    long_ttp: Optional[LongTTP] = Field(None, description="Long TTP结果")
    error: Optional[str] = Field(None, description="错误信息")