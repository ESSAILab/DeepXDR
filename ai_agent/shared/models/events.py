from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union, TypeVar, Generic
from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """事件类型枚举"""
    FALCO_ALERT = "falco_alert"
    FALCO_RAW = "falco_raw"
    OPENRASP_ALERT = "openrasp_alert"
    OPENRASP_RAW = "openrasp_raw"
    OPENRASP_RAW_SQL = "openrasp_raw_sql"
    SURICATA_ALERT = "suricata_alert"


class EventSource(str, Enum):
    """事件来源枚举"""
    FALCO = "falco"
    OPENRASP = "openrasp"
    SURICATA = "suricata"


class EventCategory(str, Enum):
    """事件类别枚举"""
    ALERT = "alert"
    RAW = "raw"


class AttackLocation(BaseModel):
    """攻击位置信息"""
    latitude: float = Field(..., description="纬度")
    location_en: str = Field(..., description="英文位置描述")
    location_zh_cn: str = Field(..., description="中文位置描述")
    longitude: float = Field(..., description="经度")


class AttackParams(BaseModel):
    """普通攻击参数 - 适用于非SQL攻击事件"""
    content: Optional[str] = Field(None, description="攻击内容")
    path: Optional[str] = Field(None, description="攻击路径")
    realpath: Optional[str] = Field(None, description="真实路径")

class AttackSQLParams(BaseModel):
    """SQL攻击参数 - 适用于SQL攻击事件"""
    query: Optional[str] = Field(None, description="SQL语句")
    server: Optional[str] = Field(None, description="SQL服务名称")


class HeaderInfo(BaseModel):
    """HTTP头信息"""
    accept: Optional[str] = Field(None, description="Accept头")
    accept_encoding: Optional[str] = Field(None, description="Accept-Encoding头", alias="accept-encoding")
    accept_language: Optional[str] = Field(None, description="Accept-Language头", alias="accept-language")
    connection: Optional[str] = Field(None, description="Connection头")
    cookie: Optional[str] = Field(None, description="Cookie")
    host: Optional[str] = Field(None, description="Host")
    referer: Optional[str] = Field(None, description="Referer")
    upgrade_insecure_requests: Optional[str] = Field(None, description="Upgrade-Insecure-Requests", alias="upgrade-insecure-requests")
    user_agent: Optional[str] = Field(None, description="User-Agent", alias="user-agent")
    x_real_ip: Optional[str] = Field(None, description="X-Real-IP头，用于获取真实客户端IP", alias="x-real-ip")
    
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        extra='allow'  # 允许额外字段，用于处理x-real-ip等动态头信息
    )


class ParameterData(BaseModel):
    """请求参数"""
    form: Optional[str] = Field(None, description="表单数据")
    json_data: Optional[str] = Field(None, description="JSON数据", alias="json")
    multipart: Optional[str] = Field(None, description="Multipart数据")


class ServerNic(BaseModel):
    """服务器网卡信息"""
    ip: str = Field(..., description="IP地址")
    name: str = Field(..., description="网卡名称")


class FalcoAlertEvent(BaseModel):
    """Falco告警事件数据结构"""
    uuid: Optional[str] = Field(None, description="事件唯一标识")
    output: str = Field(..., description="事件描述文本")
    priority: str = Field(..., description="事件优先级")
    rule: str = Field(..., description="触发规则名称")
    time: datetime = Field(..., description="事件时间")
    output_fields: Dict[str, Any] = Field(..., description="事件字段详情")
    source: str = Field(..., description="事件来源")
    tags: List[str] = Field(..., description="事件标签")
    hostname: str = Field(..., description="主机名")
    event_id: Optional[str] = Field(None, description="Kafka事件标识符")

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        json_encoders={datetime: lambda v: v.isoformat()}
    )


class FalcoRawEvent(BaseModel):
    """Falco原始事件数据结构"""
    uuid: Optional[str] = Field(None, description="事件唯一标识")
    output: str = Field(..., description="事件描述文本")
    priority: str = Field(..., description="事件优先级")
    rule: str = Field(..., description="触发规则名称")
    time: datetime = Field(..., description="事件时间")
    output_fields: Dict[str, Any] = Field(..., description="事件字段详情")
    source: str = Field(..., description="事件来源")
    tags: List[str] = Field(..., description="事件标签，必须包含behavior-collection")
    hostname: str = Field(..., description="主机名")
    event_id: Optional[str] = Field(None, description="Kafka事件标识符")

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        json_encoders={datetime: lambda v: v.isoformat()}
    )


class OpenRASPAlertEvent(BaseModel):
    """OpenRASP告警事件数据结构"""
    timestamp: datetime = Field(..., description="时间戳", alias="@timestamp")
    app_id: Optional[str] = Field(None, description="应用ID - 可选")
    attack_location: Optional[AttackLocation] = Field(None, description="攻击位置")
    attack_params: Optional[AttackParams] = Field(None, description="攻击参数")
    attack_source: Optional[str] = Field(None, description="攻击源IP")
    attack_type: Optional[str] = Field(None, description="攻击类型")
    body: Optional[str] = Field(None, description="请求体")
    client_ip: Optional[str] = Field(None, description="客户端IP")
    event_level: Optional[str] = Field(None, description="事件级别")
    event_time: Optional[datetime] = Field(None, description="事件时间")
    event_type: Optional[str] = Field(None, description="事件类型，固定为attack")
    header: Optional[HeaderInfo] = Field(None, description="HTTP头信息")
    intercept_state: Optional[str] = Field(None, description="拦截状态")
    parameter: Optional[ParameterData] = Field(None, description="请求参数")
    path: Optional[str] = Field(None, description="请求路径")
    plugin_algorithm: Optional[str] = Field(None, description="插件算法")
    plugin_confidence: Optional[int] = Field(None, description="插件置信度")
    plugin_message: Optional[str] = Field(None, description="插件消息")
    plugin_name: Optional[str] = Field(None, description="插件名称")
    rasp_id: Optional[str] = Field(None, description="RASP ID")
    request_id: Optional[str] = Field(None, description="请求ID")
    request_method: Optional[str] = Field(None, description="请求方法")
    server_hostname: Optional[str] = Field(None, description="服务器主机名")
    server_ip: Optional[str] = Field(None, description="服务器IP")
    server_nic: Optional[List[ServerNic]] = Field(None, description="服务器网卡信息")
    server_type: Optional[str] = Field(None, description="服务器类型")
    server_version: Optional[str] = Field(None, description="服务器版本")
    source_code: Optional[str] = Field(None, description="源代码")
    stack_md5: Optional[str] = Field(None, description="堆栈MD5")
    target: Optional[str] = Field(None, description="目标")
    url: Optional[str] = Field(None, description="URL")
    # 兼容旧数据中的upsert_id，但它是可选的

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        json_encoders={datetime: lambda v: v.isoformat()},
        extra='allow'  # 允许额外字段
    )


T = TypeVar('T', bound=Union[AttackParams, AttackSQLParams])  # 约束泛型类型


class BaseOpenRASPRawEvent(BaseModel, Generic[T]):
    """OpenRASP原始事件基类
    
    这是一个泛型基类，用于OpenRASP原始事件和SQL原始事件的统一结构定义。
    通过泛型参数T来区分不同的攻击参数类型：
    - OpenRASPRawEvent: 使用AttackParams，适用于普通攻击事件
    - OpenRASPRawSQLEvent: 使用AttackSQLParams，适用于SQL攻击事件
    
    这种设计避免了代码重复，同时保持了类型安全。
    """
    timestamp: datetime = Field(..., description="时间戳", alias="@timestamp")
    app_id: str = Field(..., description="应用ID")
    attack_location: AttackLocation = Field(..., description="攻击位置")
    attack_source: str = Field(..., description="攻击源IP")
    attack_type: str = Field(..., description="攻击类型")
    body: Optional[str] = Field(None, description="请求体")
    client_ip: Optional[str] = Field(None, description="客户端IP")
    event_level: str = Field(..., description="事件级别")
    event_time: datetime = Field(..., description="事件时间")
    event_type: str = Field(..., description="事件类型，固定为record_log")
    header: Optional[HeaderInfo] = Field(None, description="HTTP头信息")
    intercept_state: str = Field(..., description="拦截状态")
    parameter: Optional[ParameterData] = Field(None, description="请求参数")
    path: str = Field(..., description="请求路径")
    plugin_algorithm: str = Field(..., description="插件算法")
    plugin_confidence: int = Field(..., description="插件置信度")
    plugin_message: str = Field(..., description="插件消息")
    plugin_name: str = Field(..., description="插件名称")
    rasp_id: str = Field(..., description="RASP ID")
    request_id: str = Field(..., description="请求ID")
    request_method: str = Field(..., description="请求方法")
    server_hostname: str = Field(..., description="服务器主机名")
    server_ip: str = Field(..., description="服务器IP")
    server_nic: List[ServerNic] = Field(..., description="服务器网卡信息")
    server_type: str = Field(..., description="服务器类型")
    server_version: str = Field(..., description="服务器版本")
    source_code: Optional[str] = Field(None, description="源代码")
    stack_md5: str = Field(..., description="堆栈MD5")
    target: str = Field(..., description="目标")
    upsert_id: str = Field(..., description="唯一标识")
    url: str = Field(..., description="URL")

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        json_encoders={datetime: lambda v: v.isoformat()},
        extra='allow'  # 允许额外字段
    )


class OpenRASPRawEvent(BaseOpenRASPRawEvent[AttackParams]):
    """OpenRASP原始事件数据结构"""
    attack_params: AttackParams = Field(..., description="攻击参数")

class OpenRASPRawSQLEvent(BaseOpenRASPRawEvent[AttackSQLParams]):
    """OpenRASP SQL原始事件数据结构"""
    attack_params: AttackSQLParams = Field(..., description="SQL攻击参数")


class SuricataAlertEvent(BaseModel):
    """Suricata告警事件数据结构 - 完整EVE格式"""
    
    # === 基础信息 ===
    timestamp: datetime = Field(..., description="事件时间戳")
    flow_id: int = Field(..., description="流量ID")
    in_iface: Optional[str] = Field(None, description="网络接口")
    event_type: str = Field(..., description="事件类型")
    
    # === 网络信息 ===
    src_ip: str = Field(..., description="源IP地址")
    src_port: int = Field(..., description="源端口")
    dest_ip: str = Field(..., description="目标IP地址") 
    dest_port: int = Field(..., description="目标端口")
    proto: str = Field(..., description="协议")
    
    # === 告警核心信息 ===
    alert: Dict[str, Any] = Field(..., description="告警详情")
    
    # === 完整扩展字段（全部存储） ===
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")
    tx_id: Optional[int] = Field(None, description="事务ID")
    http: Optional[Dict[str, Any]] = Field(None, description="HTTP详情")
    app_proto: Optional[str] = Field(None, description="应用层协议")
    flow: Optional[Dict[str, Any]] = Field(None, description="流量统计信息")

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        json_encoders={datetime: lambda v: v.isoformat()},
        extra='allow'  # 允许任何额外字段，确保完全兼容
    )


RawEvent = Union[
    FalcoAlertEvent, FalcoRawEvent, 
    OpenRASPAlertEvent, OpenRASPRawEvent, OpenRASPRawSQLEvent,
    SuricataAlertEvent
]


class SecurityEvent(BaseModel):
    """统一安全事件封装"""
    event_id: str = Field(..., description="事件唯一ID")
    event_type: EventType = Field(..., description="事件类型")
    raw_event: RawEvent = Field(..., description="原始事件数据")
    received_time: datetime = Field(..., description="接收时间")
    source: EventSource = Field(..., description="事件来源")
    category: EventCategory = Field(..., description="事件类别")
    
    def get_unique_id(self) -> str:
        """获取事件唯一标识

        现在直接使用创建SecurityEvent时传入的event_id，该值应该来自Kafka原始JSON的event_id字段。
        这个方法主要确保event_id的一致性，避免重复生成。

        返回:
            str: 事件唯一ID
        """
        # 如果已经有缓存的唯一ID，直接返回
        if hasattr(self, '_cached_unique_id'):
            return self._cached_unique_id

        # 直接使用传入的event_id，它应该来自原始Kafka数据的event_id字段
        unique_id = self.event_id

        # 缓存生成的ID以确保一致性
        self._cached_unique_id = unique_id

        return unique_id
    
    def get_event_time(self) -> datetime:
        """获取事件时间（统一为东八区时间）"""
        # 避免循环导入，延迟导入
        from shared.utils.timezone import to_china_time
        
        if isinstance(self.raw_event, (FalcoAlertEvent, FalcoRawEvent)):
            time = self.raw_event.time
        elif isinstance(self.raw_event, (OpenRASPAlertEvent, OpenRASPRawEvent,  OpenRASPRawSQLEvent)):
            time = self.raw_event.event_time
        elif isinstance(self.raw_event, SuricataAlertEvent):
            time = self.raw_event.timestamp  # ✅ Suricata使用原始timestamp
        else:
            time = self.received_time
        
        # 统一转换为东八区时间
        return to_china_time(time)
    
    def get_x_real_ip(self) -> Optional[str]:
        """获取X-Real-IP头信息，用于OpenRASP事件获取真实客户端IP"""
        if isinstance(self.raw_event, (OpenRASPAlertEvent, OpenRASPRawEvent, OpenRASPRawSQLEvent)):
            logger.debug(f"检查OpenRASP事件的X-Real-IP: event_id={self.event_id}")
            logger.debug(f"raw_event.header存在: {self.raw_event.header is not None}")
            
            if self.raw_event.header:
                # 直接使用x_real_ip字段（通过alias映射）
                x_real_ip_value = self.raw_event.header.x_real_ip
                logger.debug(f"提取到的X-Real-IP值: {x_real_ip_value}")
                
                if x_real_ip_value:
                    logger.info(f"成功提取X-Real-IP: {x_real_ip_value}")
                    return x_real_ip_value
                else:
                    # 如果没有值，检查原始数据
                    header_data = self.raw_event.header.model_dump(by_alias=True)
                    logger.debug(f"Header原始数据: {header_data}")
            else:
                logger.debug("OpenRASP事件没有header信息")
        else:
            logger.debug(f"事件类型 {type(self.raw_event)} 不支持X-Real-IP提取")
        return None


class EventBatch(BaseModel):
    """事件批次处理"""
    events: List[SecurityEvent] = Field(..., description="事件列表")
    batch_id: str = Field(..., description="批次ID")
    received_at: datetime = Field(..., description="接收时间")


class EventStatistics(BaseModel):
    """事件统计信息"""
    total_events: int = Field(0, description="总事件数")
    falco_alerts: int = Field(0, description="Falco告警数")
    falco_raw: int = Field(0, description="Falco原始事件数")
    openrasp_alerts: int = Field(0, description="OpenRASP告警数")
    openrasp_raw: int = Field(0, description="OpenRASP原始事件数")
    last_event_time: Optional[datetime] = Field(None, description="最后事件时间")