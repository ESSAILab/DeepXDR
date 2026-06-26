"""
字段截断工具模块
用于根据配置的最大长度截断Elasticsearch返回结果中的字符串字段
"""

import os
from typing import Any, Dict, List, Union, Optional


def truncate_nested_fields(data: Any, max_length: int, truncation_suffix: str = "...", path: str = "", list_max_items: Optional[int] = None) -> Any:
    """
    递归截断嵌嵌数据结构中的字符串字段

    Args:
        data: 要处理的数据结构（可以是字典、列表、字符串等）
        max_length: 最大字符长度，超过将被截断
        truncation_suffix: 截断后添加的后缀，默认为"..."
        path: 当前处理路径（用于日志记录）
        list_max_items: 列表中最多保留的项目数（字符串列表专用）

    Returns:
        处理后的数据结构
    """
    # 如果未指定list_max_items，从环境变量读取
    if list_max_items is None:
        try:
            list_max_items = int(os.getenv("EQL_MAX_LIST_ITEMS", "5"))
        except ValueError:
            list_max_items = 5

    if max_length <= 0 and list_max_items <= 0:
        # 如果最大长度和小于等于0，不进行截断
        return data

    if isinstance(data, str):
        # 如果是字符串，检查是否需要截断
        if max_length > 0 and len(data) > max_length:
            if path:
                print(f"[TRUNCATE] 截断字段 {path}: {len(data)} -> {max_length}")
            return data[:max_length] + truncation_suffix
        return data

    elif isinstance(data, dict):
        # 如果是字典，递归处理每个键值对
        result = {}
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            result[key] = truncate_nested_fields(value, max_length, truncation_suffix, new_path, list_max_items)
        return result

    elif isinstance(data, list):
        # 如果是列表，有两种处理方式：
        # 1. 如果列表只包含字符串，保留前list_max_items个元素，在末尾添加截断指示符
        # 2. 如果列表包含其他类型，递归处理每个元素
        if not data:
            return data

        # 检查列表是否只包含字符串且需要按项目数截断
        if all(isinstance(item, str) for item in data):
            # 检查是否需要按项目数截断
            if list_max_items > 0 and len(data) > list_max_items:
                if path:
                    print(f"[TRUNCATE] 截断字符串列表 {path}: {len(data)} -> {list_max_items}")
                # 保留前list_max_items个元素，末尾添加截断指示符
                result = data[:list_max_items]
                result.append(f"...{len(data) - list_max_items} more items truncated")
                return result
            else:
                # 只对单个字符串元素进行长度截断
                result = []
                for item in data:
                    if max_length > 0 and len(item) > max_length:
                        result.append(item[:max_length] + truncation_suffix)
                    else:
                        result.append(item)
                return result
        else:
            # 列表中包含非字符串元素，递归处理每个元素
            result = []
            for i, item in enumerate(data):
                new_path = f"{path}[{i}]"
                result.append(truncate_nested_fields(item, max_length, truncation_suffix, new_path, list_max_items))
            return result

    else:
        # 其他类型（数字、布尔值、null等），保持原样
        return data


def apply_field_truncation(es_response: Dict, max_length: Optional[Union[int, str]] = None, list_max_items: Optional[int] = None) -> Dict:
    """
    对Elasticsearch响应应用字段截断

    Args:
        es_response: Elasticsearch原始响应
        max_length: 最大长度，可以是从环境变量读取的字符串或整数
        list_max_items: 字符串列表中最多保留的项目数

    Returns:
        处理后的响应
    """
    # 确定最大长度
    if max_length is None:
        max_length = os.getenv("EQL_MAX_FIELD_LENGTH", "1000")

    # 转换为整数
    try:
        if isinstance(max_length, str):
            max_length = int(max_length)
    except ValueError:
        max_length = 1000
        print(f"[WARNING] 无效的最大长度值，使用默认值 1000")

    # 确定列表最大项目数
    if list_max_items is None:
        try:
            list_max_items = int(os.getenv("EQL_MAX_LIST_ITEMS", "5"))
        except ValueError:
            list_max_items = 5

    if max_length <= 0 and list_max_items <= 0:
        # 禁用截断
        return es_response

    # 检查响应结构，确定是EQL还是DSL响应
    if "hits" in es_response:
        hits = es_response["hits"]

        # 处理EQL响应格式: hits.events[*]._source
        if "events" in hits:
            for event in hits["events"]:
                if "_source" in event:
                    event["_source"] = truncate_nested_fields(event["_source"], max_length, "...", "", list_max_items)

        # 处理DSL响应格式: hits.hits[*]._source
        elif "hits" in hits:
            for hit in hits["hits"]:
                if "_source" in hit:
                    hit["_source"] = truncate_nested_fields(hit["_source"], max_length, "...", "", list_max_items)

    elif "_source" in es_response:
        # 单文档获取
        es_response["_source"] = truncate_nested_fields(es_response["_source"], max_length, "...", "", list_max_items)

    return es_response


def get_truncation_config() -> Dict[str, Any]:
    """
    获取截断配置

    Returns:
        包含截断配置的字典
    """
    try:
        max_length = int(os.getenv("EQL_MAX_FIELD_LENGTH", "1000"))
    except ValueError:
        max_length = 1000

    return {
        "max_length": max_length if max_length > 0 else 0,
        "enabled": max_length > 0,
        "suffix": os.getenv("EQL_TRUNCATION_SUFFIX", "...") or "...",
        "source": "environment_variable"
    }