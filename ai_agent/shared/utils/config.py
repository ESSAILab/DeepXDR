"""
配置管理
"""
import os
from dataclasses import dataclass
from typing import List


@dataclass
class Config:
    """系统配置"""

    # 数据库配置 - PostgreSQL（保留给LTTP使用）
    database_url: str
    redis_url: str  # 不再用于STTP存储，保留给LTTP和缓存

    # Kafka配置
    kafka_bootstrap_servers: str
    kafka_topic: str
    kafka_group_id: str

    # 系统配置
    log_level: str
    log_format: str
    log_file: str
    debug_mode: bool
    short_ttp_window_interval: float
    long_ttp_generation_interval: int
    max_events_per_window: int

    # Web配置
    api_port: int

    # ElasticSearch配置
    elasticsearch_host: str
    elasticsearch_port: int
    elasticsearch_use_ssl: bool

    # API鉴权配置
    backend_api_key: str

    # LLM配置
    openai_api_key: str
    openai_base_url: str
    openai_model: str

    # MCP配置
    mcp_server_url: str


class ConfigError(ValueError):
    """配置错误"""


def _env(name: str, default: str = None) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _required_env(name: str, missing: List[str]) -> str:
    value = _env(name)
    if value is None:
        missing.append(name)
        return ""
    return value


def _parse_bool(name: str, default: bool, errors: List[str]) -> bool:
    raw_value = _env(name)
    if raw_value is None:
        return default

    normalized = raw_value.lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    errors.append(f"{name}={raw_value!r} 不是有效布尔值，请使用 true/false")
    return default


def _parse_int(
    name: str,
    default: int,
    errors: List[str],
    minimum: int = None,
    maximum: int = None,
) -> int:
    raw_value = _env(name)
    if raw_value is None:
        value = default
    else:
        try:
            value = int(raw_value)
        except ValueError:
            errors.append(f"{name}={raw_value!r} 不是有效整数")
            return default

    if minimum is not None and value < minimum:
        errors.append(f"{name}={value} 小于最小值 {minimum}")
    if maximum is not None and value > maximum:
        errors.append(f"{name}={value} 大于最大值 {maximum}")
    return value


def _parse_float(name: str, default: float, errors: List[str], minimum: float = None) -> float:
    raw_value = _env(name)
    if raw_value is None:
        value = default
    else:
        try:
            value = float(raw_value)
        except ValueError:
            errors.append(f"{name}={raw_value!r} 不是有效数字")
            return default

    if minimum is not None and value < minimum:
        errors.append(f"{name}={value} 小于最小值 {minimum}")
    return value


def _raise_if_invalid(missing: List[str], errors: List[str]) -> None:
    if not missing and not errors:
        return

    message_lines = ["配置校验失败，请修正环境变量后重启。"]
    if missing:
        message_lines.append("缺失必填环境变量:")
        message_lines.extend(f"  - {name}" for name in sorted(missing))
    if errors:
        message_lines.append("非法环境变量:")
        message_lines.extend(f"  - {error}" for error in errors)
    raise ConfigError("\n".join(message_lines))


def load_config() -> Config:
    """加载并校验核心启动配置"""
    missing: List[str] = []
    errors: List[str] = []

    log_level = _env("LOG_LEVEL", "INFO").upper()
    valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if log_level not in valid_log_levels:
        errors.append(f"LOG_LEVEL={log_level!r} 无效，可选值: {', '.join(sorted(valid_log_levels))}")

    config = Config(
        # 数据库配置 - PostgreSQL（保留给LTTP使用）
        database_url=_required_env("DATABASE_URL", missing),
        redis_url=_env("REDIS_URL", "redis://localhost:6379/0"),

        # Kafka配置
        kafka_bootstrap_servers=_required_env("KAFKA_BOOTSTRAP_SERVERS", missing),
        kafka_topic=_env("KAFKA_TOPIC", "agent"),
        kafka_group_id=_env("KAFKA_GROUP_ID", "security-analysis-group"),

        # 系统配置
        log_level=log_level,
        log_format=_env("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        log_file=_env("LOG_FILE", "/app/logs/security_analysis.log"),
        debug_mode=_parse_bool("DEBUG_MODE", False, errors),
        short_ttp_window_interval=_parse_float("SHORT_TTP_WINDOW_INTERVAL", 1.0, errors, minimum=0.1),
        long_ttp_generation_interval=_parse_int("LONG_TTP_GENERATION_INTERVAL", 1800, errors, minimum=1),
        max_events_per_window=_parse_int("MAX_EVENTS_PER_WINDOW", 1000, errors, minimum=1),

        # Web配置
        api_port=_parse_int("API_PORT", 8000, errors, minimum=1, maximum=65535),

        # ElasticSearch配置
        elasticsearch_host=_required_env("ELASTICSEARCH_HOST", missing),
        elasticsearch_port=_parse_int("ELASTICSEARCH_PORT", 9200, errors, minimum=1, maximum=65535),
        elasticsearch_use_ssl=_parse_bool("ELASTICSEARCH_USE_SSL", False, errors),

        # API鉴权配置
        backend_api_key=_required_env("BACKEND_API_KEY", missing),

        # LLM配置
        openai_api_key=_required_env("OPENAI_API_KEY", missing),
        openai_base_url=_env("OPENAI_BASE_URL", ""),
        openai_model=_env("OPENAI_MODEL", "deepseek-v3-2-251201"),

        # MCP配置
        mcp_server_url=_env("MCP_SERVER_URL", "http://localhost:5000"),
    )

    _raise_if_invalid(missing, errors)
    return config
