#!/usr/bin/env python3
"""
简化Web服务启动脚本
"""

import sys
import os
import logging

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from src.web.dashboard import app
import uvicorn

if __name__ == "__main__":
    logger.info("启动TTP分析仪表板...")
    uvicorn.run(
        "src.web.dashboard:app",
        host="0.0.0.0",
        port=30003,
        reload=False,
        log_level="info"
    )