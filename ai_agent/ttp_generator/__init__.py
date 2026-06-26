"""TTP生成器模块"""

from .window_manager import DynamicEventWindowManager
from .short_ttp_generator import ShortTTPGenerator

__all__ = [
    "DynamicEventWindowManager",
    "ShortTTPGenerator"
]