import asyncio
import logging
import signal
import sys
import argparse
import os

import uvicorn
from dotenv import load_dotenv

from data_consumer import KafkaEventConsumer
from ttp_generator import DynamicEventWindowManager, ShortTTPGenerator
from shared.database.connection import init_db_manager
from shared.database.bootstrap import init_database
from api_server import create_app
from shared.utils.config import ConfigError, load_config
from shared.utils.logger import setup_logging

logger = logging.getLogger(__name__)


class SecurityAnalysisSystem:
    """安全分析系统主类"""
    
    def __init__(self):
        self.config = load_config()
        setup_logging(self.config.log_level, self.config.log_format, self.config.log_file)
        
        # 检查是否启用debug模式
        self.debug_mode = self.config.debug_mode
        logger.info(f"调试模式: {'启用' if self.debug_mode else '禁用'}")
        
        # 初始化组件
        self.window_manager = None
        self.short_ttp_generator = None
        self.long_ttp_generator = None
        self.kafka_consumer = None
        self.api_app = None
        
        self.running = False
        self._shutdown_event = asyncio.Event()
    
    async def initialize(self):
        """初始化系统"""
        try:
            logger.info("开始初始化安全分析系统...")
            
            # 初始化数据库
            await init_database(self.config.database_url, self.config.redis_url)
            
            # 初始化数据库管理器
            db_manager = init_db_manager(
                self.config.database_url,
                self.config.redis_url
            )
            await db_manager.initialize()
            
            # 初始化事件窗口管理器
            self.window_manager = DynamicEventWindowManager(
                max_window_size=self.config.max_events_per_window,
                window_timeout=self.config.short_ttp_window_interval,
                cleanup_interval=self.config.long_ttp_generation_interval / 2
            )
            await self.window_manager.start()
            
            # 初始化短期TTP生成器
            self.short_ttp_generator = ShortTTPGenerator(
                window_manager=self.window_manager,
                min_events_per_window=1,
                max_analysis_interval=5.0,
                confidence_threshold=0.5
            )
            await self.short_ttp_generator.start()
            
            # 初始化Kafka消费者
            self.kafka_consumer = KafkaEventConsumer(
                bootstrap_servers=self.config.kafka_bootstrap_servers,
                topic=self.config.kafka_topic,
                group_id=self.config.kafka_group_id,
                event_callback=self._handle_new_event,
                max_poll_records=500,
            )
            await self.kafka_consumer.start()
            
            # 初始化API服务器
            self.api_app = create_app(
                window_manager=self.window_manager,
                short_ttp_generator=self.short_ttp_generator
            )
            
            logger.info("安全分析系统初始化完成")
            
        except Exception as e:
            logger.error(f"系统初始化失败: {e}")
            raise
    
    async def start(self):
        """启动系统"""
        try:
            logger.info("启动安全分析系统...")
            await self.initialize()
            
            # 启动API服务器
            server_config = uvicorn.Config(
                self.api_app,
                host="0.0.0.0",
                port=self.config.api_port,
                log_level=self.config.log_level.lower(),
                access_log=False
            )
            server = uvicorn.Server(server_config)
            
            # 设置信号处理器
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self._signal_handler)
            
            logger.info(f"API服务器启动在端口 {self.config.api_port}")
            
            # 运行服务器
            await server.serve()
            
        except Exception as e:
            logger.error(f"系统启动失败: {e}")
            raise
    
    async def shutdown(self):
        """优雅关闭系统"""
        logger.info("开始关闭安全分析系统...")
        
        try:
            # 停止Kafka消费者
            if self.kafka_consumer:
                await self.kafka_consumer.stop()
                logger.info("Kafka消费者已停止")
            
            # 停止短期TTP生成器
            if self.short_ttp_generator:
                await self.short_ttp_generator.stop()
                logger.info("短期TTP生成器已停止")
            
            # 停止窗口管理器
            if self.window_manager:
                await self.window_manager.stop()
                logger.info("窗口管理器已停止")
            
            logger.info("安全分析系统已完全关闭")
            
        except Exception as e:
            logger.error(f"系统关闭时发生错误: {e}")
    
    async def _handle_new_event(self, event):
        """处理新事件"""
        try:
            # 添加到窗口管理器
            await self.window_manager.add_event(event)

            logger.debug(f"处理新事件: {event.get_unique_id()}")
            
        except Exception as e:
            logger.error(f"处理新事件失败: {e}")

    def _signal_handler(self, signum, _frame):
        """信号处理器"""
        logger.info(f"接收到信号 {signum}，开始优雅关闭...")
        self._shutdown_event.set()
        
        # 创建新的事件循环来处理关闭
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.shutdown())
            else:
                asyncio.run(self.shutdown())
        except Exception as e:
            logger.error(f"信号处理失败: {e}")

        sys.exit(0)


async def main():
    """主函数"""
    load_dotenv()
    
    # 处理命令行参数
    parser = argparse.ArgumentParser(description="安全分析系统")
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="启用调试模式"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="设置日志级别"
    )
    
    args = parser.parse_args()
    
    # 设置环境变量
    if args.debug:
        os.environ["DEBUG_MODE"] = "true"
        os.environ["LOG_LEVEL"] = "DEBUG"
    
    if args.log_level:
        os.environ["LOG_LEVEL"] = args.log_level
    
    system = None
    try:
        system = SecurityAnalysisSystem()
        await system.start()
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        return
    except KeyboardInterrupt:
        logger.info("接收到键盘中断")
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"系统运行错误: {e}")
    finally:
        if system:
            await system.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
