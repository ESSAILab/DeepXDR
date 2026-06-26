"""Utility functions and helpers for the Deep Research agent."""

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
from typing import List, Optional
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    MessageLikeRepresentation,
    SystemMessage,
    ToolMessage,
    filter_messages,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import (
    BaseTool,
    tool,
)
from langchain_mcp_adapters.client import MultiServerMCPClient
from ttp_generator.dx_analyzer.state import ResearchComplete

##########################
# Reflection Tool Utils
##########################

@tool(description="Strategic reflection tool for research planning")
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    When to use:
    - After receiving search results: What key information did I find?
    - Before deciding next steps: Do I have enough to answer comprehensively?
    - When assessing research gaps: What specific information am I still missing?
    - Before concluding research: Can I provide a complete answer now?

    Reflection should address:
    1. Analysis of current findings - What concrete information have I gathered?
    2. Gap assessment - What crucial information is still missing?
    3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
    4. Strategic decision - Should I continue searching or provide my answer?

    Args:
        reflection: Your detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"

##########################
# MCP Utils
##########################

async def load_mcp_tools(
    existing_tool_names: set[str],
    excluded_tools: Optional[List[str]] = None,
) -> list[BaseTool]:
    """Load and configure MCP (Model Context Protocol) tools with authentication.
    
    Args:
        existing_tool_names: Set of tool names already in use to avoid conflicts
        excluded_tools: List of tool names to exclude from loading

    Returns:
        List of configured MCP tools ready for use
    """

    _es_mcp = os.getenv("ELASTICSEARCH_MCP_URL")
    _fs_mcp = os.getenv("FILESYSTEM_MCP_URL")
    _grep_mcp = os.getenv("GREP_MCP_URL")
    if not _es_mcp or not _fs_mcp or not _grep_mcp:
        raise ValueError(
            "MCP服务器地址未配置，请设置环境变量: "
            "ELASTICSEARCH_MCP_URL, FILESYSTEM_MCP_URL, GREP_MCP_URL"
        )

    mcp_server_config = {
        "server_elasticsearch": {
            "url": _es_mcp,
            "transport": "streamable_http"
        },
        "server_filesystem": {
            "url": _fs_mcp,
            "transport": "websocket"
        },
        "server_grep": {
            "url": _grep_mcp,
            "transport": "websocket"
        }
    }
    logger.debug("📋 [load_mcp_tools] 服务器配置")
    for name, server_cfg in mcp_server_config.items():
        logger.debug(f"   - {name}: {server_cfg['url']} ({server_cfg['transport']})")
    
    # Step 4: Load tools from MCP server using MCPClientProvider with auto-reconnect
    available_mcp_tools = []
    try:
        client = MultiServerMCPClient(mcp_server_config)
        available_mcp_tools = await client.get_tools()
        logger.debug(f"✅ [load_mcp_tools] 成功获取 {len(available_mcp_tools)} 个工具")

        # 仅在 debug 日志等级下打印所有获取到的工具
        if available_mcp_tools and logger.isEnabledFor(logging.DEBUG):
            logger.debug("📋 [load_mcp_tools] 获取到的工具:")
            for tool in available_mcp_tools:
                tool_name = getattr(tool, 'name', 'unknown')
                logger.debug(f"   - {tool_name}")
        
    except Exception as e:
        logger.error(f"❌ [load_mcp_tools] MCP服务器连接失败: {type(e).__name__}: {e}")
        return []
    
    # Step 5: Filter and configure tools
    configured_tools = []
    excluded_tools_set = set(excluded_tools or [])
    
    for mcp_tool in available_mcp_tools:
        # Skip tools with conflicting names or excluded tools
        if mcp_tool.name in existing_tool_names or mcp_tool.name in excluded_tools_set:
            continue
        
        configured_tools.append(mcp_tool)
    
    return configured_tools


##########################
# Tool Utils
##########################

async def get_all_tools():
    """Assemble complete toolkit including research and MCP tools.
    Returns:
        List of all configured and available tools for research operations
    """
    # Start with core research tools
    tools = [tool(ResearchComplete), think_tool]

    # Track existing tool names to prevent conflicts
    existing_tool_names = {tool.name for tool in tools}
    
    # Add MCP tools if configured (includes Elasticsearch, Filesystem, Grep, etc.)
    excluded_tools = [
        "get_data_stream",
        "get_cluster_health",
        "get_cluster_stats",
        "list_aliases",
        "get_alias",
        "write_file",
        "create_directory",
        "delete_file",
        "move_file",
        "copy_file",
        "list_directory_with_sizes",
        "edit_file"
    ]
    mcp_tools = await load_mcp_tools(existing_tool_names, excluded_tools)
    tools.extend(mcp_tools)
    
    return tools

def get_notes_from_tool_calls(messages: list[MessageLikeRepresentation]):
    """Extract notes from tool call messages."""
    return [tool_msg.content for tool_msg in filter_messages(messages, include_types="tool")]

##########################
# Token Limit Exceeded Utils
##########################

def is_token_limit_exceeded(exception: Exception, model_name: str = None) -> bool:
    """Determine if an exception indicates a token/context limit was exceeded.
    
    Args:
        exception: The exception to analyze
        model_name: Optional model name to optimize provider detection
        
    Returns:
        True if the exception indicates a token limit was exceeded, False otherwise
    """
    error_str = str(exception).lower()
    
    # Step 1: Determine provider from model name if available
    # 默认按 openai 处理（系统统一使用 OpenAI 兼容协议）
    provider = 'openai'
    if model_name:
        model_str = str(model_name).lower()
        if model_str.startswith('anthropic:'):
            provider = 'anthropic'
        elif model_str.startswith('gemini:') or model_str.startswith('google:'):
            provider = 'gemini'

    # Step 2: Check provider-specific token limit patterns
    if provider == 'openai':
        return _check_openai_token_limit(exception, error_str)
    elif provider == 'anthropic':
        return _check_anthropic_token_limit(exception, error_str)
    elif provider == 'gemini':
        return _check_gemini_token_limit(exception)

    # Step 3: Fallback check all providers
    return (
        _check_openai_token_limit(exception, error_str) or
        _check_anthropic_token_limit(exception, error_str) or
        _check_gemini_token_limit(exception)
    )

def _check_openai_token_limit(exception: Exception, error_str: str) -> bool:
    """Check if exception indicates OpenAI token limit exceeded."""
    # Analyze exception metadata
    exception_type = str(type(exception))
    class_name = exception.__class__.__name__
    module_name = getattr(exception.__class__, '__module__', '')
    
    # Check if this is an OpenAI exception
    is_openai_exception = (
        'openai' in exception_type.lower() or 
        'openai' in module_name.lower()
    )
    
    # Check for typical OpenAI token limit error types
    is_request_error = class_name in ['BadRequestError', 'InvalidRequestError']
    
    if is_openai_exception and is_request_error:
        # Look for token-related keywords in error message
        token_keywords = ['token', 'context', 'length', 'maximum context', 'reduce']
        if any(keyword in error_str for keyword in token_keywords):
            return True
    
    # Check for specific OpenAI error codes
    if hasattr(exception, 'code') and hasattr(exception, 'type'):
        error_code = getattr(exception, 'code', '')
        error_type = getattr(exception, 'type', '')
        
        if (error_code == 'context_length_exceeded' or
            error_type == 'invalid_request_error'):
            return True
    
    return False

def _check_anthropic_token_limit(exception: Exception, error_str: str) -> bool:
    """Check if exception indicates Anthropic token limit exceeded."""
    # Analyze exception metadata
    exception_type = str(type(exception))
    class_name = exception.__class__.__name__
    module_name = getattr(exception.__class__, '__module__', '')
    
    # Check if this is an Anthropic exception
    is_anthropic_exception = (
        'anthropic' in exception_type.lower() or 
        'anthropic' in module_name.lower()
    )
    
    # Check for Anthropic-specific error patterns
    is_bad_request = class_name == 'BadRequestError'
    
    if is_anthropic_exception and is_bad_request:
        # Anthropic uses specific error messages for token limits
        if 'prompt is too long' in error_str:
            return True
    
    return False

def _check_gemini_token_limit(exception: Exception) -> bool:
    """Check if exception indicates Google/Gemini token limit exceeded."""
    # Analyze exception metadata
    exception_type = str(type(exception))
    class_name = exception.__class__.__name__
    module_name = getattr(exception.__class__, '__module__', '')
    
    # Check if this is a Google/Gemini exception
    is_google_exception = (
        'google' in exception_type.lower() or 
        'google' in module_name.lower()
    )
    
    # Check for Google-specific resource exhaustion errors
    is_resource_exhausted = class_name in [
        'ResourceExhausted', 
        'GoogleGenerativeAIFetchError'
    ]
    
    if is_google_exception and is_resource_exhausted:
        return True
    
    # Check for specific Google API resource exhaustion patterns
    if 'google.api_core.exceptions.resourceexhausted' in exception_type.lower():
        return True
    
    return False

# NOTE: This may be out of date or not applicable to your models. Please update this as needed.
# 系统统一使用 OpenAI 兼容协议，OpenAI 系列模型不再带 provider 前缀。
# 保留 anthropic/google/cohere 前缀供潜在扩展使用。
MODEL_TOKEN_LIMITS = {
    "deepseek-v3-2-251201": 98304,
    "gpt-4.1-mini": 1047576,
    "gpt-4.1-nano": 1047576,
    "gpt-4.1": 1047576,
    "gpt-4o-mini": 128000,
    "gpt-4o": 128000,
    "o4-mini": 200000,
    "o3-mini": 200000,
    "o3": 200000,
    "o3-pro": 200000,
    "o1": 200000,
    "o1-pro": 200000,
    "anthropic:claude-opus-4": 200000,
    "anthropic:claude-sonnet-4": 200000,
    "anthropic:claude-3-7-sonnet": 200000,
    "anthropic:claude-3-5-sonnet": 200000,
    "anthropic:claude-3-5-haiku": 200000,
    "google:gemini-1.5-pro": 2097152,
    "google:gemini-1.5-flash": 1048576,
    "google:gemini-pro": 32768,
    "cohere:command-r-plus": 128000,
    "cohere:command-r": 128000,
    "cohere:command-light": 4096,
    "cohere:command": 4096,
    "mistral:mistral-large": 32768,
    "mistral:mistral-medium": 32768,
    "mistral:mistral-small": 32768,
    "mistral:mistral-7b-instruct": 32768,
    "ollama:codellama": 16384,
    "ollama:llama2:70b": 4096,
    "ollama:llama2:13b": 4096,
    "ollama:llama2": 4096,
    "ollama:mistral": 32768,
    "bedrock:us.amazon.nova-premier-v1:0": 1000000,
    "bedrock:us.amazon.nova-pro-v1:0": 300000,
    "bedrock:us.amazon.nova-lite-v1:0": 300000,
    "bedrock:us.amazon.nova-micro-v1:0": 128000,
    "bedrock:us.anthropic.claude-3-7-sonnet-20250219-v1:0": 200000,
    "bedrock:us.anthropic.claude-sonnet-4-20250514-v1:0": 200000,
    "bedrock:us.anthropic.claude-opus-4-20250514-v1:0": 200000,
    "anthropic.claude-opus-4-1-20250805-v1:0": 200000,
}

def get_model_token_limit(model_string):
    """Look up the token limit for a specific model.
    
    Args:
        model_string: The model identifier string to look up
        
    Returns:
        Token limit as integer if found, None if model not in lookup table
    """
    # Search through known model token limits
    for model_key, token_limit in MODEL_TOKEN_LIMITS.items():
        if model_key in model_string:
            return token_limit
    
    # Model not found in lookup table
    return None

def remove_up_to_last_ai_message(messages: list[MessageLikeRepresentation]) -> list[MessageLikeRepresentation]:
    """Truncate message history by removing up to the last AI message.
    
    This is useful for handling token limit exceeded errors by removing recent context.
    
    Args:
        messages: List of message objects to truncate
        
    Returns:
        Truncated message list up to (but not including) the last AI message
    """
    # Search backwards through messages to find the last AI message
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], AIMessage):
            # Return everything up to (but not including) the last AI message
            return messages[:i]
    
    # No AI messages found, return original list
    return messages

def _try_split_at_message(msg, messages, i, cumulative, target_chars, last_split):
    """判断当前消息是否是合适的压缩分割点，返回 (split_idx, new_last_split) 或 (None, new_last_split)。"""
    if isinstance(msg, AIMessage):
        if cumulative >= target_chars:
            return i, last_split
        return None, i

    if isinstance(msg, ToolMessage):
        # ToolMessage 之后是自然的分割点（工具调用完成）
        if i + 1 < len(messages) and not isinstance(messages[i + 1], ToolMessage):
            next_idx = i + 1
            if cumulative >= target_chars:
                return next_idx, last_split
            return None, next_idx

    return None, last_split


def find_compress_split_point(messages: list[MessageLikeRepresentation], fraction: float) -> int:
    """Find smart split point based on character count and message types."""
    logging.debug("[find_compress_split_point] Finding split point with fraction: %s, total messages: %d", fraction, len(messages))

    if fraction <= 0 or fraction >= 1:
        return 0

    char_counts = [len(str(msg.content)) if hasattr(msg, 'content') else 0 for msg in messages]
    total_chars = sum(char_counts)
    target_chars = total_chars * fraction

    logging.debug("[find_compress_split_point] Total chars: %d, target chars: %d", total_chars, target_chars)

    last_split = 0
    cumulative = 0

    for i, msg in enumerate(messages):
        split_idx, last_split = _try_split_at_message(msg, messages, i, cumulative, target_chars, last_split)
        if split_idx is not None:
            return split_idx
        cumulative += char_counts[i]

    # Can compress everything if ends with AI message
    return len(messages) if messages and isinstance(messages[-1], AIMessage) else last_split

async def truncate_messages_by_length(messages: list[MessageLikeRepresentation], max_total_chars: int = 393216, model: Optional[BaseChatModel] = None) -> list[MessageLikeRepresentation]:
    """Truncate messages by character count without promoting untrusted history.

    The optional ``model`` argument is retained for API compatibility but is
    deliberately unused. Older non-system messages may contain untrusted user,
    telemetry, or tool output, so they must not be summarized by an LLM and
    reintroduced as a new SystemMessage.
    """
    if not messages:
        return messages
    
    # Calculate total character count
    total_chars = sum(len(str(msg.content)) for msg in messages if hasattr(msg, 'content'))
    
    # Debug logging
    logging.debug(f"[truncate_messages_by_length] Total chars: {total_chars}, limit: {max_total_chars}, model: {model}")
    
    # If within limits, return as-is
    if total_chars <= max_total_chars:
        return messages
    
    # Smart split - omit older history at a natural boundary, keep recent context.
    split_idx = find_compress_split_point(messages, 0.7)
    logging.debug(f"[truncate_messages_by_length] Split point: {split_idx}, total messages: {len(messages)}")
    older, recent = messages[:split_idx], messages[split_idx:]
    
    # Calculate character counts for debugging
    older_chars = sum(len(str(msg.content)) for msg in older if hasattr(msg, 'content'))
    recent_chars = sum(len(str(msg.content)) for msg in recent if hasattr(msg, 'content'))
    logging.debug(f"[truncate_messages_by_length] Older messages: {len(older)} messages, {older_chars} chars")
    logging.debug(f"[truncate_messages_by_length] Recent messages: {len(recent)} messages, {recent_chars} chars")
    
    # Protect system messages from older messages.
    protected = [m for m in older if isinstance(m, SystemMessage)]
    omitted_non_system_messages = [m for m in older if not isinstance(m, SystemMessage)]
    
    if model is not None:
        logging.debug("[truncate_messages_by_length] Ignoring compression model to avoid promoting untrusted history")

    omission_marker = SystemMessage(
        content=(
            "[... 截断：较早的非系统历史消息已省略，未进行模型摘要以避免提升不可信内容 ...]"
        )
    )

    # Build result: protected system messages + safe omission marker + recent messages.
    # Older non-system content is intentionally discarded instead of summarized.
    result = protected + ([omission_marker] if omitted_non_system_messages else []) + recent
    
    # Truncate individual long messages if still over limit
    final_chars = sum(len(str(m.content)) for m in result if hasattr(m, 'content'))
    logging.debug(f"[truncate_messages_by_length] Final result chars: {final_chars}, limit: {max_total_chars}")
    
    if final_chars > max_total_chars:
        logging.debug("[truncate_messages_by_length] Still over limit, truncating first 50 percent of recent messages...")
        
        # Use find_compress_split_point to split recent messages (keep last 50%)
        recent_split_idx = find_compress_split_point(recent, 0.5)  # Split recent in half
        recent_keep = recent[recent_split_idx:]  # Keep last 50% of recent
       
        # Build final result with only protected system messages, safe markers, and recent context.
        truncation_marker = SystemMessage(content="[... 截断：部分最近历史消息已省略 ...]")
        final = protected + ([omission_marker] if omitted_non_system_messages else []) + [truncation_marker] + recent_keep
        
        final_truncated_chars = sum(len(str(m.content)) for m in final if hasattr(m, 'content'))
        logging.debug(f"[truncate_messages_by_length] Truncated result chars: {final_truncated_chars}")
        return final
    
    return result

def estimate_token_count(text: str) -> int:
    """Estimate token count from character count (rough approximation).
    
    Args:
        text: Text to estimate tokens for
        
    Returns:
        Estimated token count
    """
    # Rough approximation: 1 token ≈ 4 characters for English text
    # Use more conservative estimate for safety
    return len(text) // 3

def _split_paragraph(paragraph, chunks, current_chunk, max_chunk_size):
    """处理单个超长段落的分割，按句子切分后返回新的 current_chunk。"""
    sentences = paragraph.split('. ')
    for sentence in sentences:
        if len(current_chunk) + len(sentence) > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                # Single sentence is too long, force split
                chunks.append(sentence[:max_chunk_size])
                remaining = sentence[max_chunk_size:]
                if remaining:
                    current_chunk = remaining
        else:
            current_chunk += ('. ' + sentence if current_chunk else sentence)
    return current_chunk


def split_long_content(content: str, max_chunk_size: int = 80000) -> List[str]:
    """Split very long content into manageable chunks.

    Args:
        content: Long content to split
        max_chunk_size: Maximum characters per chunk (default: 80000)

    Returns:
        List of content chunks
    """
    if len(content) <= max_chunk_size:
        return [content]

    chunks = []
    current_chunk = ""

    # Split by sentences or paragraphs to maintain coherence
    paragraphs = content.split('\n\n')

    for paragraph in paragraphs:
        if len(current_chunk) + len(paragraph) > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = paragraph
            else:
                current_chunk = _split_paragraph(paragraph, chunks, current_chunk, max_chunk_size)
        else:
            current_chunk += ('\n\n' + paragraph if current_chunk else paragraph)

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


async def execute_tool_safely(tool, args, config):
    """Safely execute a tool with error handling."""
    try:
        result = await tool.ainvoke(args, config)
        # Ensure result is always a string, not an array or other format
        if isinstance(result, list):
            # Convert list to formatted string
            return "\n".join(str(item) for item in result)
        elif not isinstance(result, str):
            # Convert non-string results to string
            return str(result)
        return result
    except Exception as e:
        return f"Error executing tool: {str(e)}"


def _parse_indices_result(indices_result: str) -> list:
    """解析索引结果字符串为行列表，处理转义字符。"""
    if not indices_result:
        return []
    if "\\n" in indices_result:
        indices_result = indices_result.replace("\\n", "\n")
    return [line.strip() for line in indices_result.strip().split("\n") if line.strip()]


async def _try_get_mapping(line, tools_by_name, config, mapping):
    """尝试从单行获取索引 mapping，如果成功则返回新的 mapping。"""
    if "get_index" not in tools_by_name or mapping is not None:
        return mapping
    try:
        index_name = line.split()[2] if len(line.split()) >= 3 else line
        new_mapping = await execute_tool_safely(
            tools_by_name["get_index"], {"index": index_name}, config
        )
        logging.info("[ES Metadata] 成功获取索引 '%s' 的mapping信息", index_name)
        return new_mapping
    except Exception:
        return mapping


async def prefetch_elasticsearch_metadata(tools: List, config: RunnableConfig, index_patterns: List[str]) -> dict:
    """预获取Elasticsearch索引和mapping信息，按指定索引名称过滤

    Args:
        tools: 可用工具列表
        config: 运行时配置
        index_patterns: 必需参数，索引名称列表，如 ["suricata-alerts"]

    Returns:
        包含索引和mapping信息的字典
    """
    try:
        # 获取工具
        tools_by_name = {
            tool.name if hasattr(tool, "name") else tool.get("name"): tool
            for tool in tools
        }

        list_indices_tool = tools_by_name.get("list_indices")
        if not list_indices_tool:
            return {}

        # 获取索引列表
        indices_result = await execute_tool_safely(list_indices_tool, {}, config)
        result_lines = _parse_indices_result(indices_result)

        logging.info("[ES Metadata] 获取到 %d 个索引", len(result_lines))
        for i, line in enumerate(result_lines):
            logging.debug("  [%d] %s", i + 1, line)

        relevant_indices = []
        mapping = None
        pattern = index_patterns[0] if index_patterns else ""

        # 遍历索引列表，筛选匹配的索引
        for line in result_lines:
            if pattern and f" {pattern}" in line:
                relevant_indices.append(line)
                mapping = await _try_get_mapping(line, tools_by_name, config, mapping)

        logging.info("[ES Metadata] 筛选完成，找到 %d 个相关索引", len(relevant_indices))
        return {
            "list_indices": relevant_indices,
            "get_index": mapping if mapping else {},
        }

    except Exception as e:
        logging.warning("[ES Metadata] 预获取失败: %s", e)
        return {}

def get_today_str() -> str:
    """Get current date formatted as ISO 8601 with microseconds and timezone offset.
    
    Returns:
        String in format like '2026-03-04T17:01:42.587000+08:00'
    """
    # 1. 定义东八区时区 (UTC+8)
    tz = timezone(timedelta(hours=8))
    
    # 2. 获取当前时间并附加时区信息
    # 如果直接使用 datetime.now() 而不传时区，得到的对象是 "naive" 的，无法输出 +08:00
    now = datetime.now(tz)
    
    # 3. 使用 isoformat() 生成标准格式
    # isoformat() 会自动处理微秒 (.587000) 和时区 (+08:00)
    return now.isoformat()

def get_api_key_for_model(model_name: str, config: RunnableConfig):
    """Get API key for a specific model from environment or config."""
    should_get_from_config = os.getenv("GET_API_KEYS_FROM_CONFIG", "false")
    model_name = model_name.lower()
    # 系统统一使用 OpenAI 兼容协议，无 provider 前缀时默认返回 OPENAI_API_KEY
    if should_get_from_config.lower() == "true":
        api_keys = config.get("configurable", {}).get("apiKeys", {})
        if not api_keys:
            return None
        if model_name.startswith("anthropic:"):
            return api_keys.get("ANTHROPIC_API_KEY")
        elif model_name.startswith("google"):
            return api_keys.get("GOOGLE_API_KEY")
        return api_keys.get("OPENAI_API_KEY")
    else:
        if model_name.startswith("anthropic:"):
            return os.getenv("ANTHROPIC_API_KEY")
        elif model_name.startswith("google"):
            return os.getenv("GOOGLE_API_KEY")
        return os.getenv("OPENAI_API_KEY")



