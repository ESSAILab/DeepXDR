"""
日志配置
"""
import logging
import sys
from typing import Optional


def setup_logging(log_level: str = "INFO", log_format: Optional[str] = None, log_file: Optional[str] = None):
    """设置日志配置"""
    
    # 日志格式
    if log_format is None:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    if log_file is None:
        # 注意是运行程序的当前相对目录
        log_file = "security_analysis.log"        
    
    
    # 清空旧的日志文件（仅在DEBUG模式下或文件为空时）
    try:
        import os
        if os.path.exists(log_file):
            stat = os.stat(log_file)
            # 如果文件小于100字节或DEBUG模式，清空它
            if stat.st_size < 100 or log_level.upper() == "DEBUG":
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write("")
    except Exception:
        pass
    
    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除现有的处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # 创建文件处理器（自动创建父目录）
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    file_handler.setFormatter(logging.Formatter(log_format))
    
    # 添加处理器到根日志器
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # 设置第三方库的日志级别
    logging.getLogger("aiokafka").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("elastic_transport").setLevel(logging.ERROR)
    logging.getLogger("mcp").setLevel(logging.ERROR)    
    logging.getLogger("websockets").setLevel(logging.WARNING)

    
    # FastAPI日志控制开关 - 通过环境变量控制
    fastapi_log_level = os.getenv("FASTAPI_LOG_LEVEL", "INFO").upper()
    if fastapi_log_level == "DISABLED" or os.getenv("DISABLE_FASTAPI_LOGS", "").lower() == "true":
        # 完全禁用api_server.app的日志
        logging.getLogger("api_server.app").setLevel(logging.CRITICAL + 1)  # 设置为比CRITICAL更高的级别
        logging.getLogger("api_server").setLevel(logging.CRITICAL + 1)
    else:
        # 使用指定的级别
        logging.getLogger("api_server.app").setLevel(getattr(logging, fastapi_log_level))
        logging.getLogger("api_server").setLevel(getattr(logging, fastapi_log_level))
    
    # 设置系统日志器
    system_logger = logging.getLogger("security_analysis")
    system_logger.setLevel(getattr(logging, log_level.upper()))

    logging.debug(f"日志已配置，级别: {log_level}, 文件: {log_file}")

