"""
东八区时间工具模块
提供统一的时间处理功能，确保所有时间戳都使用东八区（Asia/Shanghai）
"""
from datetime import datetime, timezone
from typing import Optional
import pytz

# 东八区时区
CHINA_TZ = pytz.timezone('Asia/Shanghai')


def now() -> datetime:
    """获取当前东八区时间"""
    return datetime.now(CHINA_TZ)


def utc_now() -> datetime:
    """获取当前UTC时间并转换为东八区"""
    utc_dt = datetime.now(timezone.utc)
    return utc_dt.astimezone(CHINA_TZ)


def from_datetime(dt: datetime) -> datetime:
    """将任意时间转换为东八区时间"""
    if dt.tzinfo is None:
        # 如果时间是offset-naive，假设为UTC
        dt = pytz.utc.localize(dt)
    return dt.astimezone(CHINA_TZ)


def to_naive(dt: datetime) -> datetime:
    """将带时区的时间转换为offset-naive的东八区时间"""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(CHINA_TZ).replace(tzinfo=None)


def to_china_time(dt: datetime) -> datetime:
    """将任意时间转换为东八区时间（offset-naive）"""
    if dt.tzinfo is None:
        # 如果时间是offset-naive，假设已经是本地时间（东八区）
        return dt
    else:
        # 如果时间是offset-aware，转换为东八区
        return dt.astimezone(CHINA_TZ).replace(tzinfo=None)


def isoformat(dt: Optional[datetime] = None) -> str:
    """获取ISO格式的东八区时间字符串"""
    if dt is None:
        dt = now()
    return from_datetime(dt).isoformat()


def timestamp() -> float:
    """获取当前东八区时间的时间戳"""
    return now().timestamp()


class ChinaTime:
    """东八区时间工具类"""
    
    @staticmethod
    def now():
        return now()
    
    @staticmethod
    def utcnow():
        return utc_now()
    
    @staticmethod
    def isoformat(dt=None):
        return isoformat(dt)
    
    @staticmethod
    def timestamp():
        return timestamp()