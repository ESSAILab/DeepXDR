"""Main LangGraph implementation for the Deep Research agent."""

import asyncio
import copy
import json
import logging
import os
import re
from typing import Any, Dict, List, Literal
from pprint import pformat
from uuid import uuid4
import traceback

from langchain.chat_models import init_chat_model
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    filter_messages,
    get_buffer_string,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ttp_generator.dx_analyzer.configuration import (
    Configuration,
)
from ttp_generator.dx_analyzer.prompts import (
    clarify_with_user_instructions,
    compress_research_simple_human_message,
    compress_research_system_prompt,
    final_report_generation_prompt,
    final_threathunting_generation_prompt,
    lead_researcher_prompt,
    network_tracing_prompt,
    endpoints_tracing_prompt,
    application_tracing_prompt,
    transform_messages_into_research_topic_prompt,
)
from ttp_generator.dx_analyzer.state import (
    AgentInputState,
    AgentState,
    ClarifyWithUser,
    ConductEndpointsTracing,
    ConductApplicationTracing,
    ConductNetworkTracing,
    ResearchComplete,
    ResearcherOutputState,
    ResearcherState,
    ResearchQuestion,
    SupervisorState,
    AnalysisReport,
    TTP,
    Technique,
)
from ttp_generator.dx_analyzer.utils import (
    execute_tool_safely,
    get_all_tools,
    get_api_key_for_model,
    get_model_token_limit,
    get_notes_from_tool_calls,
    get_today_str,
    is_token_limit_exceeded,
    prefetch_elasticsearch_metadata,
    remove_up_to_last_ai_message,
    think_tool,
    truncate_messages_by_length,
)
from mitre_attck_agent.workflows.graph import create_graph_no_checkpointing, run_investigation
from mitre_attck_agent.workflows.state import create_initial_state

_LANGSMITH_NO_STREAM_TAG = "langsmith:nostream"
# 人机反馈展示常量：控制返回给前端的调查思路最大字符数
HUMAN_FEEDBACK_MAX_THOUGHTS_CHARS = 10000

# sj add logging start ---------------------------------------------------------
# 获取根记录器并配置
logger = logging.getLogger(__name__)
# 屏蔽httpx HTTP请求日志
logging.getLogger("httpx").setLevel(logging.WARNING)
# 屏蔽 httpcore 的 DEBUG 日志
logging.getLogger("httpcore").setLevel(logging.WARNING)
# 屏蔽langchain相关日志
logging.getLogger("langchain").setLevel(logging.WARNING)
# 屏蔽langgraph相关日志
logging.getLogger("langgraph").setLevel(logging.WARNING)
logging.getLogger("langsmith").setLevel(logging.WARNING)
logging.getLogger("langgraph_runtime").setLevel(logging.WARNING)
logging.getLogger("langgraph_runtime_inmem").setLevel(logging.WARNING)
# 屏蔽openai相关日志
logging.getLogger("openai").setLevel(logging.WARNING)
# sj add logging end  ----------------------------------------------------------


# Initialize a configurable model that we will use throughout the agent
# 统一使用 OpenAI 兼容协议，模型配置不再带 provider 前缀
configurable_model = init_chat_model(
    "gpt-4.1",
    model_provider="openai",
    configurable_fields=("model", "max_tokens", "api_key"),
)

async def clarify_with_user(state: AgentState, config: RunnableConfig) -> Command[Literal["write_research_brief", "__end__"]]:
    """Analyze user messages and ask clarifying questions if the research scope is unclear.
    
    This function determines whether the user's request needs clarification before proceeding
    with research. If clarification is disabled or not needed, it proceeds directly to research.
    
    Args:
        state: Current agent state containing user messages
        config: Runtime configuration with model settings and preferences
        
    Returns:
        Command to either end with a clarifying question or proceed to research brief
    """
    # Step 1: Check if clarification is enabled in configuration
    configurable = Configuration.from_runnable_config(config)
    if not configurable.allow_clarification:
        # Skip clarification step and proceed directly to research
        return Command(goto="write_research_brief")
    
    logger.debug("Starting clarification analysis")
    logger.debug(f"configurable is {configurable}")
    # Step 2: Prepare the model for structured clarification analysis
    messages = state["messages"]
    model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": [_LANGSMITH_NO_STREAM_TAG]
    }
    
    # Configure model with structured output and retry logic
    clarification_model = (
        configurable_model
        .with_structured_output(ClarifyWithUser)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(model_config)
    )
    
    # Step 3: Analyze whether clarification is needed
    prompt_content = clarify_with_user_instructions.format(
        messages=get_buffer_string(messages), 
        date=get_today_str()
    )
    logger.debug("Step1 clarify_with_user prompts: %s", prompt_content)
    response = await clarification_model.ainvoke([HumanMessage(content=prompt_content)])
    
    # Step 4: Route based on clarification analysis
    if response.need_clarification:
        # End with clarifying question for user
        logger.debug("Clarification needed, waiting for user's response...")
        return Command(
            goto=END, 
            update={"messages": [AIMessage(content=response.question)]}
        )
    else:
        # Proceed to research with verification message
        logger.debug("No clarification needed, proceeding to write_research_brief...")
        return Command(
            goto="write_research_brief", 
            update={"messages": [AIMessage(content=response.verification)]}
        )


async def write_research_brief(state: AgentState, config: RunnableConfig) -> Command[Literal["research_supervisor"]]:
    """Transform user messages into a structured research brief and initialize supervisor.
    
    This function analyzes the user's messages and generates a focused research brief
    that will guide the research supervisor. It also sets up the initial supervisor
    context with appropriate prompts and instructions.
    
    Args:
        state: Current agent state containing user messages
        config: Runtime configuration with model settings
        
    Returns:
        Command to proceed to research supervisor with initialized context
    """
    # Step 1: Set up the research model for structured output
    configurable = Configuration.from_runnable_config(config)
    research_model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": [_LANGSMITH_NO_STREAM_TAG]
    }
    
    logger.debug(f"research_model_config is {research_model_config}")
    # Configure model for structured research question generation
    research_model = (
        configurable_model
        .with_structured_output(ResearchQuestion)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(research_model_config)
    )
    
    # Step 2: Generate structured research brief from user messages
    prompt_content = transform_messages_into_research_topic_prompt.format(
        messages=get_buffer_string(state.get("messages", [])),
        date=get_today_str()
    )
    logger.debug("Step2 write_research_brief prompts: %s", prompt_content)
    response = await research_model.ainvoke([HumanMessage(content=prompt_content)])
    logger.debug("Research brief response: %s.", response)

    # Step 3: Initialize supervisor with research brief and instructions
    supervisor_system_prompt = lead_researcher_prompt.format(
        date=get_today_str(),
        max_concurrent_research_units=configurable.max_concurrent_research_units,
        max_researcher_iterations=configurable.max_researcher_iterations
    )
    
    logger.info("Research brief generated, initializing supervisor...")    
    return Command(
        goto="research_supervisor", 
        update={
            "research_brief": response.research_brief,
            "supervisor_messages": {
                "type": "override",
                "value": [
                    SystemMessage(content=supervisor_system_prompt),
                    HumanMessage(content=response.research_brief)
                ]
            }
        }
    )


async def construct_shorttp_trigger_longttp_prompt(state: AgentState, config: RunnableConfig) -> Command[Literal["research_supervisor"]]:
    """Transform user messages into a structured research brief and initialize supervisor.
    
    This function analyzes the user's messages and generates a focused research brief
    that will guide the research supervisor. It also sets up the initial supervisor
    context with appropriate prompts and instructions.
    
    Args:
        state: Current agent state containing user messages
        config: Runtime configuration with model settings
        
    Returns:
        Command to proceed to research supervisor with initialized context
    """
    # Step 1: Initialize supervisor with research brief and instructions
    configurable = Configuration.from_runnable_config(config)
    
    supervisor_system_prompt = lead_researcher_prompt.format(
        date=get_today_str(),
        max_concurrent_research_units=configurable.max_concurrent_research_units,
        max_researcher_iterations=configurable.max_researcher_iterations
    )
    
    messages = state.get("messages", [])
    if messages and isinstance(messages, list):
        # 提取第一个消息的内容
        first_msg = messages[0]
        if hasattr(first_msg, 'content'):  # HumanMessage对象
            inst = first_msg.content
        elif isinstance(first_msg, dict) and 'content' in first_msg:  # 字典格式
            inst = first_msg['content']
        else:
            inst = str(first_msg)
    else:
        inst = str(messages)

    logger.debug("initializing supervisor humanmsg: %s", inst)

    return Command(goto="research_supervisor", update={
        "research_brief": inst,
        "supervisor_messages": {
            "type": "override",
            "value": [
                SystemMessage(content=supervisor_system_prompt),
                HumanMessage(content=inst)
            ]
        }
    })


async def supervisor(state: SupervisorState, config: RunnableConfig) -> Command[Literal["supervisor_tools"]]:
    """Lead research supervisor that plans research strategy and delegates to researchers.
    
    The supervisor analyzes the research brief and decides how to break down the research
    into manageable tasks. It can use think_tool for strategic planning, ConductApplicationTracing, ConductNetworkTracing, ConductEndpointsTracing
    to delegate tasks to sub-researchers, or ResearchComplete when satisfied with findings.
    
    Args:
        state: Current supervisor state with messages and research context
        config: Runtime configuration with model settings
        
    Returns:
        Command to proceed to supervisor_tools for tool execution
    """
    # Step 1: Configure the supervisor model with available tools
    configurable = Configuration.from_runnable_config(config)
    research_model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": [_LANGSMITH_NO_STREAM_TAG]
    }
    
    # Available tools: research delegation, completion signaling, and strategic thinking
    lead_researcher_tools = [ConductEndpointsTracing, ConductApplicationTracing, ConductNetworkTracing, ResearchComplete, think_tool]
    
    # Configure model with tools, retry logic, and model settings
    research_model = (
        configurable_model
        .bind_tools(lead_researcher_tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(research_model_config)
    )
    
    
    # Step 2: Generate supervisor response based on current context
    supervisor_messages = state.get("supervisor_messages", [])

    # 兜底保护：检查 supervisor_messages 长度，防止超出模型输入限制
    total_chars = sum(len(str(msg.content)) for msg in supervisor_messages if hasattr(msg, 'content'))
    if total_chars > 250000:
        logger.warning(
            "supervisor_messages 长度 %d 超过兜底阈值 250000，执行紧急截断。"
            "这通常说明 human_feedback_node 的重建逻辑未生效或存在异常路径。",
            total_chars
        )
        system_msgs = [m for m in supervisor_messages if isinstance(m, SystemMessage)]
        other_msgs = [m for m in supervisor_messages if not isinstance(m, SystemMessage)]
        # 保留最近 4 条非系统消息，丢弃其余
        kept_other = other_msgs[-4:] if len(other_msgs) > 4 else other_msgs
        supervisor_messages = system_msgs + kept_other
        truncated_chars = sum(len(str(m.content)) for m in supervisor_messages if hasattr(m, 'content'))
        logger.info(
            "supervisor_messages 紧急截断完成: %d 字符 → %d 字符, 保留 %d/%d 条消息",
            total_chars, truncated_chars, len(supervisor_messages), len(state.get("supervisor_messages", []))
        )

    response = await research_model.ainvoke(supervisor_messages)
    if logger.isEnabledFor(logging.DEBUG):
        tool_names = [tc.get("name", "unknown") for tc in response.tool_calls or []]
        logger.debug("Supervisor response going to call tools: %s", pformat(tool_names))
    # Step 3: Update state and proceed to tool execution
    return Command(
        goto="supervisor_tools",
        update={
            "supervisor_messages": [response],
            "research_iterations": state.get("research_iterations", 0) + 1
        }
    )

async def _run_research_calls(all_research_calls, configurable, config):
    """并行执行研究调用，返回 ToolMessage 列表和聚合的 raw_notes。"""
    allowed_calls = all_research_calls[:configurable.max_concurrent_research_units]
    overflow_calls = all_research_calls[configurable.max_concurrent_research_units:]

    logger.debug("Executing %d research tasks concurrently...", len(allowed_calls))
    for i, tool_call in enumerate(allowed_calls):
        logger.debug("Research task %d content: %s", i + 1, tool_call["args"]["research_topic"])
        logger.debug("Research tool : %s", tool_call["name"])

    research_tasks = []
    for tool_call in allowed_calls:
        if tool_call["name"] == "ConductNetworkTracing":
            subgraph = network_researcher_subgraph
        elif tool_call["name"] == "ConductEndpointsTracing":
            subgraph = endpoints_researcher_subgraph
        elif tool_call["name"] == "ConductApplicationTracing":
            subgraph = application_researcher_subgraph
        else:
            subgraph = network_researcher_subgraph

        research_tasks.append(
            subgraph.ainvoke({
                "researcher_messages": [
                    HumanMessage(content=tool_call["args"]["research_topic"])
                ],
                "research_topic": tool_call["args"]["research_topic"]
            }, config)
        )

    tool_results = await asyncio.gather(*research_tasks)

    messages = []
    for observation, tool_call in zip(tool_results, allowed_calls):
        content = observation.get("compressed_research", "Error synthesizing research report: Maximum retries exceeded")
        preview = f"{content[:200]}..." if len(content) > 500 else content
        logger.debug("Research result preview: %s", preview)
        messages.append(ToolMessage(
            content=content,
            name=tool_call["name"],
            tool_call_id=tool_call["id"]
        ))

    for overflow_call in overflow_calls:
        messages.append(ToolMessage(
            content=f"Error: Did not run this research as you have already exceeded the maximum number of concurrent research units. Please try again with {configurable.max_concurrent_research_units} or fewer research units.",
            name=overflow_call["name"],
            tool_call_id=overflow_call["id"]
        ))

    raw_notes_concat = "\n".join([
        "\n".join(observation.get("raw_notes", []))
        for observation in tool_results
    ])

    return messages, raw_notes_concat


async def supervisor_tools(state: SupervisorState, config: RunnableConfig) -> Command[Literal["supervisor", "__end__"]]:
    """Execute tools called by the supervisor, including research delegation and strategic thinking.
    
    This function handles five types of supervisor tool calls:
    1. think_tool - Strategic reflection that continues the conversation
    2. ConductEndpointsTracing - Delegates hunting endpoints threats tasks to sub-researchers
    3. ConductApplicationTracing - Delegates hunting application threats tasks to sub-researchers
    4. ConductNetworkTracing - Delegates hunting network threats tasks to sub-researchers
    5. ResearchComplete - Signals completion of research phase
    
    Args:
        state: Current supervisor state with messages and iteration count
        config: Runtime configuration with research limits and model settings
        
    Returns:
        Command to either continue supervision loop or end research phase
    """
    # Step 1: Extract current state and check exit conditions
    configurable = Configuration.from_runnable_config(config)
    supervisor_messages = state.get("supervisor_messages", [])
    research_iterations = state.get("research_iterations", 0)
    most_recent_message = supervisor_messages[-1]
    
    # Define exit criteria for research phase
    exceeded_allowed_iterations = research_iterations > configurable.max_researcher_iterations
    no_tool_calls = not most_recent_message.tool_calls
    research_complete_tool_call = any(
        tool_call["name"] == "ResearchComplete" 
        for tool_call in most_recent_message.tool_calls
    )
    
    # Exit if any termination condition is met
    if exceeded_allowed_iterations or no_tool_calls or research_complete_tool_call:
        logger.info("Research phase terminated, exiting. Ready to write report.")
        logger.debug("exceeded_allowed_iterations: %s, no_tool_calls: %s, research_complete_tool_call: %s", exceeded_allowed_iterations, no_tool_calls, research_complete_tool_call)
        return Command(
            goto=END,
            update={
                "notes": get_notes_from_tool_calls(supervisor_messages),
                "research_brief": state.get("research_brief", "")
            }
        )
    
    # Step 2: Process all tool calls together (think_tool and ConductApplicationTracing, ConductNetworkTracing, ConductEndpointsTracing)
    all_tool_messages = []
    update_payload = {"supervisor_messages": []}
    
    # Handle think_tool calls (strategic reflection)
    think_tool_calls = [
        tool_call for tool_call in most_recent_message.tool_calls 
        if tool_call["name"] == "think_tool"
    ]
    
    # 收集本轮所有 think_tool 的思考内容
    current_round_thoughts = []
    for tool_call in think_tool_calls:
        reflection_content = tool_call["args"]["reflection"]
        all_tool_messages.append(ToolMessage(
            content=f"Reflection recorded: {reflection_content}",
            name="think_tool",
            tool_call_id=tool_call["id"]
        ))
        current_round_thoughts.append(reflection_content)

    # 打印本次 think_tool 思考内容
    if current_round_thoughts:
        print_thoughts_str = " | ".join(current_round_thoughts)
        if len(print_thoughts_str) > 2000:
            # 长度超过2000时，打印前800和后800，中间用省略号连接
            log_content = f"{print_thoughts_str[:800]} ... {print_thoughts_str[-800:]}"
        else:
            # 长度未超过2000时，直接打印完整内容
            log_content = print_thoughts_str
        logger.info("supervisor think_tool 本次思考: %s", log_content)

    # 使用 override 模式，每轮只保留本轮的思考，避免跨轮次重复累积
    if current_round_thoughts:
        update_payload["research_thoughts"] = {
            "type": "override",
            "value": current_round_thoughts
        }

    
    # Handle specialized research calls
    conduct_network_research_calls = [
        tool_call for tool_call in most_recent_message.tool_calls 
        if tool_call["name"] == "ConductNetworkTracing"
    ]
    
    conduct_endpoints_research_calls = [
        tool_call for tool_call in most_recent_message.tool_calls 
        if tool_call["name"] == "ConductEndpointsTracing"
    ]
    
    conduct_application_research_calls = [
        tool_call for tool_call in most_recent_message.tool_calls 
        if tool_call["name"] == "ConductApplicationTracing"
    ]

    # Combine all research calls
    all_research_calls = (
        conduct_network_research_calls +
        conduct_endpoints_research_calls +
        conduct_application_research_calls
    )
    
    if all_research_calls:
        try:
            extra_messages, raw_notes_concat = await _run_research_calls(
                all_research_calls, configurable, config
            )
            all_tool_messages.extend(extra_messages)
            if raw_notes_concat:
                update_payload["raw_notes"] = [raw_notes_concat]
        except Exception as e:
            if is_token_limit_exceeded(e, configurable.research_model):
                logger.error("Research execution error - token limit exceeded.")
                return Command(
                    goto=END,
                    update={
                        "notes": get_notes_from_tool_calls(supervisor_messages),
                        "research_brief": state.get("research_brief", "")
                    }
                )
            logger.error("Research execution fail, other error: %s", e)
            raise
    
    # Step 3: Return command with all tool results
    update_payload["supervisor_messages"] = all_tool_messages
    logger.info("All supervisor_tools completed. Continuing supervision loop with updated messages...")
    return Command(
        goto="supervisor",
        update=update_payload
    ) 

# Supervisor Subgraph Construction
# Creates the supervisor workflow that manages research delegation and coordination
supervisor_builder = StateGraph(SupervisorState, config_schema=Configuration)

# Add supervisor nodes for research management
supervisor_builder.add_node("supervisor", supervisor)           # Main supervisor logic
supervisor_builder.add_node("supervisor_tools", supervisor_tools)  # Tool execution handler

# Define supervisor workflow edges
supervisor_builder.add_edge(START, "supervisor")  # Entry point to supervisor

# Compile supervisor subgraph for use in main workflow
supervisor_subgraph = supervisor_builder.compile()


async def researcher_tools(state: ResearcherState, config: RunnableConfig) -> Command[Literal["researcher", "compress_research"]]:
    """Execute tools called by the researcher, including search tools and strategic thinking.
    
    This function handles various types of researcher tool calls:
    1. think_tool - Strategic reflection that continues the research conversation
    2. MCP tools - External tool integrations
    3. ResearchComplete - Signals completion of individual research task
    
    Args:
        state: Current researcher state with messages and iteration count
        config: Runtime configuration with research limits and tool settings
        
    Returns:
        Command to either continue research loop or proceed to compression
    """
    # Step 1: Extract current state and check early exit conditions
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    most_recent_message = researcher_messages[-1]
    
    # Early exit if no tool calls were made
    has_tool_calls = bool(most_recent_message.tool_calls)

    if not has_tool_calls:
        return Command(goto="compress_research")
    
    # Step 2: Handle other tool calls (search, MCP tools, etc.)
    tools = await get_all_tools()
    tools_by_name = {
        tool.name if hasattr(tool, "name") else tool.get("name", "web_search"): tool 
        for tool in tools
    }
    
    # Execute all tool calls in parallel
    tool_calls = most_recent_message.tool_calls

    async def _execute_or_missing(tool_name, tool, args, config, available_tools):
        """执行工具调用，若工具不存在则返回友好错误信息"""
        if tool is None:
            return (
                f"Error: Tool '{tool_name}' is not available. "
                f"Available tools: {', '.join(available_tools)}"
            )
        return await execute_tool_safely(tool, args, config)

    tool_execution_tasks = [
        _execute_or_missing(
            tool_call["name"],
            tools_by_name.get(tool_call["name"]),
            tool_call["args"],
            config,
            list(tools_by_name.keys())
        )
        for tool_call in tool_calls
    ]
    observations = await asyncio.gather(*tool_execution_tasks)
    
    # Create tool messages from execution results
    tool_outputs = [
        ToolMessage(
            content=observation,
            name=tool_call["name"],
            tool_call_id=tool_call["id"]
        ) 
        for observation, tool_call in zip(observations, tool_calls)
    ]
    
    # Step 3: Check late exit conditions (after processing tools)
    exceeded_iterations = state.get("tool_call_iterations", 0) >= configurable.max_react_tool_calls
    research_complete_called = any(
        tool_call["name"] == "ResearchComplete" 
        for tool_call in most_recent_message.tool_calls
    )
    
    if exceeded_iterations or research_complete_called:
        # End research and proceed to compression
        return Command(
            goto="compress_research",
            update={"researcher_messages": tool_outputs}
        )
    
    # Continue research loop with tool results
    return Command(
        goto="researcher",  # Default to network_researcher, will be overridden by conditional edges
        update={"researcher_messages": tool_outputs}
    )

async def compress_research(state: ResearcherState, config: RunnableConfig):
    """Compress and synthesize research findings into a concise, structured summary.
    
    This function takes all the research findings, tool outputs, and AI messages from
    a researcher's work and distills them into a clean, comprehensive summary while
    preserving all important information and findings.
    
    Args:
        state: Current researcher state with accumulated research messages
        config: Runtime configuration with compression model settings
        
    Returns:
        Dictionary containing compressed research summary and raw notes
    """
    # Step 1: Configure the compression model
    configurable = Configuration.from_runnable_config(config)
    synthesizer_model = configurable_model.with_config({
        "model": configurable.compression_model,
        "max_tokens": configurable.compression_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.compression_model, config),
        "tags": [_LANGSMITH_NO_STREAM_TAG]
    })
    
    # Step 2: Prepare messages for compression
    researcher_messages = state.get("researcher_messages", [])
    
    # Add instruction to switch from research mode to compression mode
    researcher_messages.append(HumanMessage(content=compress_research_simple_human_message))
    
    # Step 3: Attempt compression with retry logic for token limit issues
    synthesis_attempts = 0
    max_attempts = 3
    
    while synthesis_attempts < max_attempts:
        try:
            # Create system prompt focused on compression task
            compression_prompt = compress_research_system_prompt.format(date=get_today_str())
            messages = [SystemMessage(content=compression_prompt)] + researcher_messages
            
            # Execute compression
            response = await synthesizer_model.ainvoke(messages)
            
            # Extract raw notes from all tool and AI messages
            raw_notes_content = "\n".join([
                str(message.content) 
                for message in filter_messages(researcher_messages, include_types=["tool", "ai"])
            ])
            
            # Return successful compression result
            return {
                "compressed_research": str(response.content),
                "raw_notes": [raw_notes_content]
            }
            
        except Exception as e:
            synthesis_attempts += 1
            
            # Handle token limit exceeded by removing older messages
            if is_token_limit_exceeded(e, configurable.research_model):
                logger.warning("Token limit exceeded, retrying with the last AI message")
                researcher_messages = remove_up_to_last_ai_message(researcher_messages)
                continue
            
            # For other errors, continue retrying
            logger.warning(f"Compressing research fail, other error: {e}")
            continue
    
    # Step 4: Return error result if all attempts failed
    raw_notes_content = "\n".join([
        str(message.content) 
        for message in filter_messages(researcher_messages, include_types=["tool", "ai"])
    ])
    
    return {
        "compressed_research": "Error synthesizing research report: Maximum retries exceeded",
        "raw_notes": [raw_notes_content]
    }

async def network_researcher(state: ResearcherState, config: RunnableConfig) -> Command[Literal["researcher_tools"]]:
    """Network researcher that conducts focused research on network-related topics.
    
    This researcher specializes in network infrastructure, protocols, and security analysis.
    It uses network-specific tools and knowledge to gather comprehensive information.
    
    Args:
        state: Current researcher state with messages and topic context
        config: Runtime configuration with model settings and tool availability
        
    Returns:
        Command to proceed to researcher_tools for tool execution
    """
    # Step 1: Load configuration and validate tool availability
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    
    # Get all research tools (including Elasticsearch MCP tools)
    tools = await get_all_tools()
    
    if len(tools) == 0:
        raise ValueError(
            "No network tools found to conduct research: Please configure network-specific "
            "research tools or add relevant MCP tools to your configuration."
        )
    
    # Step 2: Check cache first, then prefetch Elasticsearch metadata for network-specific indices
    es_metadata = next((m["metadata"] for m in state.get("mappings", []) if m.get("type") == "suricata-alerts"), None)
    if not es_metadata:
        es_metadata = await prefetch_elasticsearch_metadata(tools, config, index_patterns=["suricata-alerts"])
    
    # Step 3: Configure the researcher model with network-specific tools
    research_model_config = {
        "model": configurable.research_model,
        "model_provider": "openai",
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": [_LANGSMITH_NO_STREAM_TAG]
    }
    
    # 使用新的字段名展示metadata，提供更清晰的信息
    metadata_display = f"""
    Elasticsearch Indices (全部相关索引):
    {chr(10).join(es_metadata.get('list_indices', []))}

    Elasticsearch Mapping (索引结构):
    {es_metadata.get('get_index', {})}
    """
    
    # Prepare network-specific system prompt with prefetched metadata
    mcp_prompt_with_metadata = f"{configurable.mcp_prompt or ''}\n\n{metadata_display}"
    researcher_prompt = network_tracing_prompt.format(
        mcp_prompt=mcp_prompt_with_metadata,
        date=get_today_str(),
        filesystem_allowed_root=os.environ["MCP_FILESYSTEM_ALLOWED_ROOT"]
    )
    
    # Configure model with tools, retry logic, and settings
    research_model = (
        init_chat_model(**research_model_config)
        .bind_tools(tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
    )
    
    # Step 3: Generate researcher response with network-specific context
    messages = [SystemMessage(content=researcher_prompt)] + researcher_messages
    
    # Pre-check message length and truncate if necessary
    total_chars = sum(len(str(msg.content)) for msg in messages if hasattr(msg, 'content'))
    if total_chars > 393216:
        logger.warning(f"Message length {total_chars} exceeds safe limit, applying pre-truncation")
        messages = await truncate_messages_by_length(messages, max_total_chars=360000)
    
    response = await research_model.ainvoke(messages)
    
    # Step 4: Update state and proceed to tool execution
    return Command(
        goto="researcher_tools",
        update={
            "researcher_messages": [response],
            "tool_call_iterations": state.get("tool_call_iterations", 0) + 1,
            "mappings": [{"type": "suricata-alerts", "metadata": es_metadata}]
        }
    )

async def endpoints_researcher(state: ResearcherState, config: RunnableConfig) -> Command[Literal["researcher_tools"]]:
    """Endpoints researcher that conducts focused research on endpoints related topics.
    
    This researcher specializes in endpoint security, including devices, servers, and applications.
    It uses endpoint-specific tools and knowledge to gather comprehensive information.
    
    Args:
        state: Current researcher state with messages and topic context
        config: Runtime configuration with model settings and tool availability
        
    Returns:
        Command to proceed to researcher_tools for tool execution
    """
    # Step 1: Load configuration and validate tool availability
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    
    # Get all research tools (including Elasticsearch MCP tools)
    tools = await get_all_tools()
    
    if len(tools) == 0:
        raise ValueError(
            "No endpoints tools found to conduct research: Please configure endpoints-specific "
            "research tools or add relevant MCP tools to your configuration."
        )
    
    # Step 2: Check cache first, then prefetch Elasticsearch metadata for endpoints-specific indices
    es_metadata = next((m["metadata"] for m in state.get("mappings", []) if m.get("type") == "falco-alerts"), None)
    if not es_metadata:
        es_metadata = await prefetch_elasticsearch_metadata(tools, config, index_patterns=["falco-alerts"])
    
    # Step 3: Configure the researcher model with endpoints-specific tools
    research_model_config = {
        "model": configurable.research_model,
        "model_provider": "openai",
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": [_LANGSMITH_NO_STREAM_TAG]
    }
    
    # 使用新的字段名展示metadata，提供更清晰的信息
    metadata_display = f"""
    Elasticsearch Indices (全部相关索引):
    {chr(10).join(es_metadata.get('list_indices', []))}

    Elasticsearch Mapping (索引结构):
    {es_metadata.get('get_index', {})}
    """
    
    # Prepare endpoints-specific system prompt with prefetched metadata
    mcp_prompt_with_metadata = f"{configurable.mcp_prompt or ''}\n\n{metadata_display}"
    researcher_prompt = endpoints_tracing_prompt.format(
        mcp_prompt=mcp_prompt_with_metadata,
        date=get_today_str(),
        filesystem_allowed_root=os.environ["MCP_FILESYSTEM_ALLOWED_ROOT"]
    )
    
    # Configure model with tools, retry logic, and settings
    research_model = (
        init_chat_model(**research_model_config)
        .bind_tools(tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
    )
    
    # Step 3: Generate researcher response with endpoints-specific context
    messages = [SystemMessage(content=researcher_prompt)] + researcher_messages
    
    # Pre-check message length and truncate if necessary
    total_chars = sum(len(str(msg.content)) for msg in messages if hasattr(msg, 'content'))
    if total_chars > 393216:
        logger.warning(f"Message length {total_chars} exceeds safe limit, applying pre-truncation")
        messages = await truncate_messages_by_length(messages, max_total_chars=360000)
    
    response = await research_model.ainvoke(messages)
    
    # Step 4: Update state and proceed to tool execution
    return Command(
        goto="researcher_tools",
        update={
            "researcher_messages": [response],
            "tool_call_iterations": state.get("tool_call_iterations", 0) + 1,
            "mappings": [{"type": "falco-alerts", "metadata": es_metadata}]
        }
    )

async def application_researcher(state: ResearcherState, config: RunnableConfig) -> Command[Literal["researcher_tools"]]:
    """Application researcher that conducts focused research on application security topics.
    
    This researcher specializes in web application security, API vulnerabilities, and application-level threats.
    It uses application-specific tools and knowledge to gather comprehensive information.
    
    Args:
        state: Current researcher state with messages and topic context
        config: Runtime configuration with model settings and tool availability
        
    Returns:
        Command to proceed to researcher_tools for tool execution
    """
    # Step 1: Load configuration and validate tool availability
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    
    # Get all research tools (including Elasticsearch MCP tools)
    tools = await get_all_tools()
    
    if len(tools) == 0:
        raise ValueError(
            "No application tools found to conduct research: Please configure application-specific "
            "research tools or add relevant MCP tools to your configuration."
        )
    
    # Step 2: Check cache first, then prefetch Elasticsearch metadata for application-specific indices
    es_metadata = next((m["metadata"] for m in state.get("mappings", []) if m.get("type") == "openrasp-alerts"), None)
    if not es_metadata:
        es_metadata = await prefetch_elasticsearch_metadata(tools, config, index_patterns=["openrasp-alerts"])
    
    # Step 3: Configure the researcher model with application-specific tools
    research_model_config = {
        "model": configurable.research_model,
        "model_provider": "openai",
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": [_LANGSMITH_NO_STREAM_TAG]
    }
    
    # 使用新的字段名展示metadata，提供更清晰的信息
    metadata_display = f"""
    Elasticsearch Indices (全部相关索引):
    {chr(10).join(es_metadata.get('list_indices', []))}

    Elasticsearch Mapping (索引结构):
    {es_metadata.get('get_index', {})}
    """
    
    # Prepare application-specific system prompt with prefetched metadata
    mcp_prompt_with_metadata = f"{configurable.mcp_prompt or ''}\n\n{metadata_display}"
    researcher_prompt = application_tracing_prompt.format(
        mcp_prompt=mcp_prompt_with_metadata,
        date=get_today_str(),
        filesystem_allowed_root=os.environ["MCP_FILESYSTEM_ALLOWED_ROOT"]
    )
    
    # Configure model with tools, retry logic, and settings
    research_model = (
        init_chat_model(**research_model_config)
        .bind_tools(tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
    )
    
    # Step 3: Generate researcher response with application-specific context
    messages = [SystemMessage(content=researcher_prompt)] + researcher_messages
    
    # Pre-check message length and truncate if necessary
    total_chars = sum(len(str(msg.content)) for msg in messages if hasattr(msg, 'content'))
    if total_chars > 393216:
        logger.warning(f"Message length {total_chars} exceeds safe limit, applying pre-truncation")
        messages = await truncate_messages_by_length(messages, max_total_chars=360000)
    
    response = await research_model.ainvoke(messages)
    
    # Step 4: Update state and proceed to tool execution
    return Command(
        goto="researcher_tools",
        update={
            "researcher_messages": [response],
            "tool_call_iterations": state.get("tool_call_iterations", 0) + 1,
            "mappings": [{"type": "openrasp-alerts", "metadata": es_metadata}]
        }
    )

# Network Researcher Subgraph Construction
network_researcher_builder = StateGraph(
    ResearcherState, 
    output=ResearcherOutputState, 
    config_schema=Configuration
)

network_researcher_builder.add_node("researcher", network_researcher)
network_researcher_builder.add_node("researcher_tools", researcher_tools)
network_researcher_builder.add_node("compress_research", compress_research)

network_researcher_builder.add_edge(START, "researcher")
network_researcher_builder.add_edge("compress_research", END)

network_researcher_subgraph = network_researcher_builder.compile()

# Endpoints Researcher Subgraph Construction
endpoints_researcher_builder = StateGraph(
    ResearcherState, 
    output=ResearcherOutputState, 
    config_schema=Configuration
)

endpoints_researcher_builder.add_node("researcher", endpoints_researcher)
endpoints_researcher_builder.add_node("researcher_tools", researcher_tools)
endpoints_researcher_builder.add_node("compress_research", compress_research)

endpoints_researcher_builder.add_edge(START, "researcher")
endpoints_researcher_builder.add_edge("compress_research", END)


endpoints_researcher_subgraph = endpoints_researcher_builder.compile()

# Application Researcher Subgraph Construction
application_researcher_builder = StateGraph(
    ResearcherState, 
    output=ResearcherOutputState, 
    config_schema=Configuration
)

application_researcher_builder.add_node("researcher", application_researcher)
application_researcher_builder.add_node("researcher_tools", researcher_tools)
application_researcher_builder.add_node("compress_research", compress_research)

application_researcher_builder.add_edge(START, "researcher")
application_researcher_builder.add_edge("compress_research", END)

# Add conditional edge from researcher_tools back to researcher for research loop
#application_researcher_builder.add_edge("researcher_tools", "researcher")

application_researcher_subgraph = application_researcher_builder.compile()

def _calc_truncated_findings(e, current_retry, configurable, findings, findings_token_limit):
    """如果是 token limit 错误，计算并返回截断后的 findings 和新的 limit；
    如果无法确定模型限制，返回错误字典；否则返回 None 表示不是 token limit 错误。"""
    if not is_token_limit_exceeded(e, configurable.final_report_model):
        return None
    if current_retry == 0:
        model_token_limit = get_model_token_limit(configurable.final_report_model)
        if not model_token_limit:
            return {
                "final_report": f"Error generating final report: Token limit exceeded, however, we could not determine the model's maximum context length. Please update the model map in deep_researcher/utils.py with this information. {e}",
                "messages": [AIMessage(content="Report generation failed due to token limits")],
            }
        return findings[:model_token_limit * 4], model_token_limit * 4
    return findings[:int(findings_token_limit * 0.9)], int(findings_token_limit * 0.9)


async def final_report_generation(state: AgentState, config: RunnableConfig):
    """Generate the final comprehensive research report with retry logic for token limits.
    
    This function takes all collected research findings and synthesizes them into a 
    well-structured, comprehensive final report using the configured report generation model.
    
    Args:
        state: Agent state containing research findings and context
        config: Runtime configuration with model settings and API keys
        
    Returns:
        Dictionary containing the final report and cleared state
    """
    # Step 1: Extract research findings and prepare state cleanup
    notes = state.get("notes", [])
    cleared_state = {"notes": {"type": "override", "value": []}}
    findings = "\n".join(notes)
    
    # Step 2: Configure the final report generation model
    configurable = Configuration.from_runnable_config(config)
    writer_model_config = {
        "model": configurable.final_report_model,
        "max_tokens": configurable.final_report_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.final_report_model, config),
        "tags": [_LANGSMITH_NO_STREAM_TAG]
    }
    

    # Step 3: Attempt report generation with token limit retry logic
    max_retries = 3
    current_retry = 0
    findings_token_limit = None
    
    while current_retry <= max_retries:
        try:
            # Create comprehensive prompt with all research context
            final_report_prompt = final_report_generation_prompt.format(
                research_brief=state.get("research_brief", ""),
                messages=get_buffer_string(state.get("messages", [])),
                findings=findings,
                date=get_today_str()
            )
            
            logger.debug("Final report generation attempt %d prompts: %s", current_retry + 1, final_report_prompt)
            # Generate the final report
            final_report = await configurable_model.with_config(writer_model_config).ainvoke([
                HumanMessage(content=final_report_prompt)
            ])
            
            # Return successful report generation
            return {
                "final_report": final_report.content, 
                "messages": [final_report],
                **cleared_state
            }
            
        except Exception as e:
            result = _calc_truncated_findings(
                e, current_retry, configurable, findings, findings_token_limit
            )
            if isinstance(result, dict):
                return {**result, **cleared_state}
            if result is not None:
                findings, findings_token_limit = result
                current_retry += 1
                continue
            return {
                "final_report": f"Error generating final report: {e}",
                "messages": [AIMessage(content="Report generation failed due to an error")],
                **cleared_state
            }
    
    # Step 4: Return failure result if all retries exhausted
    return {
        "final_report": "Error generating final report: Maximum retries exceeded",
        "messages": [AIMessage(content="Report generation failed after maximum retries")],
        **cleared_state
    }

async def _run_mitre_investigation_isolated(graph: Any, initial_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    隔离运行 MITRE 调查，确保返回的数据不包含不可序列化的对象。

    这个函数在一个隔离的上下文中运行调查图，使用深拷贝提取所有需要的数据。
    """

    # 运行调查图
    final_state = await run_investigation(graph, initial_state)

    # 使用深拷贝提取所有需要的数据
    # 这确保我们不会持有对原始 state 中任何对象的引用
    confirmed_techniques = copy.deepcopy(final_state.get("confirmed_techniques", []) or [])
    triage_summary = copy.deepcopy(final_state.get("triage_summary", "") or "")
    intel = copy.deepcopy(final_state.get("intel", {}) or {})
    detections = copy.deepcopy(final_state.get("detections", {}) or {})
    mitigations = copy.deepcopy(final_state.get("mitigations", {}) or {})
    detection_reasoning = copy.deepcopy(final_state.get("detection_reasoning", {}) or {})
    technique_candidates = copy.deepcopy(final_state.get("technique_candidates", {}) or {})
    technique_events = copy.deepcopy(final_state.get("technique_events", {}) or {})
    report = copy.deepcopy(final_state.get("report", {}) or {})

    # 重要：清除 final_state 和 initial_state 引用
    del final_state
    del initial_state

    return {
        "confirmed_techniques": confirmed_techniques,
        "triage_summary": triage_summary,
        "intel": intel,
        "detections": detections,
        "mitigations": mitigations,
        "detection_reasoning": detection_reasoning,
        "technique_candidates": technique_candidates,
        "technique_events": technique_events,
        "report": report,
    }


def _find_section(text: str, keywords: List[str]) -> int:
    """查找章节位置，先精确匹配 markdown 标题，再模糊匹配行内关键词。"""
    for kw in keywords:
        for prefix in ("## ", "### "):
            idx = text.find(prefix + kw)
            if idx != -1:
                return idx
    for kw in keywords:
        pattern = re.compile(rf"^[\s\d\.]*{re.escape(kw)}", re.MULTILINE)
        match = pattern.search(text)
        if match:
            return match.start()
    return -1


def _build_appendix_and_insert(report: Dict, final_report: str) -> str:
    """构建附录内容并插入到报告合适位置"""
    appendix_parts = []
    if report.get("notable_groups_software") and "威胁组织" not in final_report:
        appendix_parts.append(
            "## 相关威胁组织与软件\n"
            + "".join(f"- {item}\n" for item in report["notable_groups_software"])
        )
    if report.get("detection_recommendations") and "检测建议" not in final_report:
        appendix_parts.append(
            "## 检测建议\n"
            + "".join(f"- {rec}\n" for rec in report["detection_recommendations"])
        )

    if not appendix_parts:
        return final_report

    appendix = "\n\n" + "\n\n".join(appendix_parts)
    inserted = False

    idx = _find_section(
        final_report,
        ["结论", "总结", "调查结论", "分析结论", "综述", "最终结论"],
    )
    if idx != -1:
        final_report = final_report[:idx] + appendix + "\n\n" + final_report[idx:]
        inserted = True
        logger.info('在"结论"、"总结"等章节之前插入"威胁组织"和"检测建议"')

    if not inserted:
        idx = _find_section(
            final_report,
            ["来源", "数据来源", "证据来源", "参考来源", "数据参考"],
        )
        if idx != -1:
            final_report = final_report[:idx] + appendix + "\n\n" + final_report[idx:]
            inserted = True
            logger.info('未找到结论类章节，尝试在"来源"类章节之前插入"威胁组织"和"检测建议"')

    if not inserted:
        final_report += appendix

    return final_report


def _parse_procedure_items(value) -> List[str]:
    """解析 procedure/evidence 字段为字符串列表，兼容多种数据类型"""
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        nested = value.get("procedure", value.get("procedures", value.get("evidence", [])))
        return _parse_procedure_items(nested)
    return []


def _combine_behavior_evidence_procedures(behaviors, evidences) -> List[str]:
    """将归一化 behavior 与原始 evidence 拼成可读、可追溯的 procedure。"""
    behavior_items = _parse_procedure_items(behaviors)
    evidence_items = _parse_procedure_items(evidences)

    combined: List[str] = []
    for index in range(max(len(behavior_items), len(evidence_items))):
        behavior = behavior_items[index] if index < len(behavior_items) else ""
        evidence = evidence_items[index] if index < len(evidence_items) else ""
        if behavior and evidence and behavior != evidence:
            item = f"行为: {behavior}；证据: {evidence}"
        else:
            item = behavior or evidence
        if item and item not in combined:
            combined.append(item)
    return combined


def _group_techniques_by_tactic(
    confirmed_techniques: List[Dict],
    technique_candidates: Dict,
) -> Dict[str, List[Dict]]:
    """将确认的技术按战术分组"""
    tactic_groups: Dict[str, List[Dict]] = {}
    for tech in confirmed_techniques:
        tech_id = tech.get("id", "")
        tech_name = tech.get("name", "")
        tactics = tech.get("tactics", [])

        procedures = _combine_behavior_evidence_procedures(
            tech.get("procedures", []),
            technique_candidates.get(tech_id, tech.get("evidence", [])),
        )

        for tactic_info in tactics:
            tactic_name = (
                tactic_info.get("tactic", "Unknown")
                if isinstance(tactic_info, dict)
                else str(tactic_info)
            )
            if tactic_name not in tactic_groups:
                tactic_groups[tactic_name] = []
            tactic_groups[tactic_name].append({
                "tech_id": tech_id,
                "tech_name": tech_name,
                "procedures": procedures,
            })

    return tactic_groups


def _build_mitre_result(
    confirmed_techniques: List[Dict],
    technique_candidates: Dict,
    technique_events: Dict,
    report: Dict,
) -> Dict[str, Any]:
    """根据 MITRE 调查结果构建最终报告和 TTP 数据。"""
    final_report = _build_appendix_and_insert(report, report.get("markdown", ""))

    # 将 MITRE 技术转换为 TTP 格式（与 ShortTTP 相同结构）
    tactic_groups = _group_techniques_by_tactic(confirmed_techniques, technique_candidates)

    ttps_list = []
    for tactic_name, techniques in tactic_groups.items():
        tech_objects = []
        tactic_event_ids = set()
        for t in techniques:
            current_tech_event_ids = technique_events.get(t["tech_id"], [])
            if isinstance(current_tech_event_ids, list):
                tactic_event_ids.update(current_tech_event_ids)
            else:
                logger.warning(
                    "技术 %s 的事件ID格式不正确，预期为列表，但收到: %s, 未添加到战术事件ID集合中",
                    t["tech_id"],
                    current_tech_event_ids,
                )

            tech_obj = Technique(
                tech_id=t["tech_id"],
                tech_name=t["tech_name"],
                description="",
                procedures=t["procedures"],
                event_ids=current_tech_event_ids
                if isinstance(current_tech_event_ids, list)
                else [],
            )
            tech_objects.append(tech_obj)

        ttp = TTP(
            id=str(uuid4()),
            name=tactic_name,
            description=f"战术: {tactic_name}",
            techniques=tech_objects,
            event_ids=list(tactic_event_ids),
        )
        ttps_list.append(ttp)

    logger.info("MITRE 调查报告生成完成，包含 %d 个战术", len(ttps_list))
    ttps_json = json.dumps(
        [ttp.model_dump() for ttp in ttps_list], ensure_ascii=False
    )

    return {
        "final_report": final_report,
        "messages": [AIMessage(content=final_report)],
        "ttps": ttps_json,
        "notes": {"type": "override", "value": []},
    }


async def mitre_investigation_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """MITRE ATT&CK 调查节点

    使用 mitre_threat_investigation 模块进行完整的 MITRE ATT&CK 调查，
    包括技术映射、情报收集、检测建议和缓解措施。
    直接生成最终报告，返回与 final_threathunting_generation 相同的格式。

    Args:
        state: Agent state containing research findings
        config: Runtime configuration

    Returns:
        Dictionary containing final report in the same format as final_threathunting_generation
    """
    try:

        logger.info("开始 MITRE ATT&CK 调查...")

        # 获取调研笔记作为 incident_text
        notes = state.get("notes", [])
        findings = "\n".join(notes) if notes else "No research findings available"

        # 截断 findings 避免超出模型输入限制（triage agent 的 prompt 会额外附加 system prompt + JSON template）
        MAX_FINDINGS_CHARS = 50000
        if len(findings) > MAX_FINDINGS_CHARS:
            original_len = len(findings)
            findings = findings[-MAX_FINDINGS_CHARS:]
            # 截断到下一个完整行，避免断在半句话
            first_newline = findings.find("\n")
            if first_newline != -1:
                findings = findings[first_newline + 1:]
            findings = f"...（前面笔记已截断，保留最新内容）\n\n{findings}"
            logger.warning(f"[MITRE] 调研笔记超长已截断: {original_len} -> {len(findings)} 字符")

        # 获取模型配置（兼容旧配置中带 provider 前缀的格式）
        model = os.getenv("OPENAI_MODEL", "deepseek-v3-2-251201")
        if ":" in model:
            model = model.split(":", 1)[1]

        # 创建调查图（无 checkpointing）
        graph = create_graph_no_checkpointing()

        # 创建初始状态
        initial_state = create_initial_state(
            incident_text=findings,
            domain="enterprise",
            llm_model=model,
        )

        # 运行调查，在单独的函数中执行以隔离状态
        investigation_data = await _run_mitre_investigation_isolated(
            graph=graph,
            initial_state=initial_state
        )

        confirmed_techniques = investigation_data.get("confirmed_techniques", [])
        technique_candidates = investigation_data.get("technique_candidates", {})
        technique_events = investigation_data.get("technique_events", {})

        report = investigation_data.get("report", {})
        logger.info("MITRE 调查完成，识别技术数: %d", len(confirmed_techniques))

        return _build_mitre_result(
            confirmed_techniques=confirmed_techniques,
            technique_candidates=technique_candidates,
            technique_events=technique_events,
            report=report,
        )

    except Exception as e:
        logger.error(f"MITRE 调查执行失败: {e}")
        # 返回错误报告，与 final_threathunting_generation 错误处理一致
        return {
            "final_report": f"MITRE 调查执行失败: {str(e)}",
            "messages": [AIMessage(content=f"MITRE 调查执行失败: {str(e)}")],
            "ttps": "[]",
            "notes": {"type": "override", "value": []}
        }

# Main Deep Researcher Graph Construction
# Creates the complete deep research workflow from user input to final report
deep_researcher_builder = StateGraph(
    AgentState,
    input=AgentInputState,
    config_schema=Configuration
)

# Add main workflow nodes for the complete research process
deep_researcher_builder.add_node("clarify_with_user", clarify_with_user)           # User clarification phase
deep_researcher_builder.add_node("write_research_brief", write_research_brief)     # Research planning phase
deep_researcher_builder.add_node("research_supervisor", supervisor_subgraph)       # Research execution phase
deep_researcher_builder.add_node("final_report_generation", final_report_generation)  # Report generation phase

# Define main workflow edges for sequential execution
deep_researcher_builder.add_edge(START, "clarify_with_user")                       # Entry point

# 根据环境变量决定是否使用 MITRE 调查子图
USE_MITRE_INVESTIGATION = os.getenv("USE_MITRE_INVESTIGATION_SUBGRAPH", "false").lower() == "true"

if USE_MITRE_INVESTIGATION:    
    deep_researcher_builder.add_node("mitre_investigation", mitre_investigation_node)    
    deep_researcher_builder.add_edge("research_supervisor", "mitre_investigation")
    deep_researcher_builder.add_edge("mitre_investigation", END)
    logger.info("MITRE 调查子图已启用，将直接生成报告并结束")
else:
    # 原有连接: research_supervisor -> final_report_generation -> END
    deep_researcher_builder.add_edge("research_supervisor", "final_report_generation")
    deep_researcher_builder.add_edge("final_report_generation", END)                   # Final exit point

# Compile the complete deep researcher workflow
deep_researcher = deep_researcher_builder.compile()


async def _try_fallback_json_parse(final_report_prompt: str, writer_model_config: dict) -> tuple:
    """备选 JSON 解析方案：使用非结构化模型调用并手动清理 markdown 代码块。"""
    fallback_model = configurable_model.with_config(writer_model_config)
    fallback_response = await fallback_model.ainvoke([
        HumanMessage(content=final_report_prompt + "\n\nIMPORTANT: Return ONLY raw JSON, no markdown code blocks!")
    ])

    content = fallback_response.content
    if not isinstance(content, str):
        raise ValueError("Fallback response content is not a string")

    # 移除 markdown 代码块，匹配 ```json ... ``` 或 ``` ... ```
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        content = json_match.group(1).strip()
    else:
        content = content.strip()

    # 解析 JSON
    parsed_data = json.loads(content)
    ttps_list = parsed_data.get("ttps", [])
    final_report = parsed_data.get("final_report", "")

    # 验证和修复每个 TTP 的结构
    for ttp in ttps_list:
        if "event_ids" not in ttp:
            ttp["event_ids"] = []
        if "techniques" not in ttp:
            ttp["techniques"] = []
        for tech in ttp.get("techniques", []):
            if "related_event_ids" in tech:
                del tech["related_event_ids"]

    ttps_json = json.dumps(ttps_list, ensure_ascii=False)
    return final_report, ttps_json


async def final_threathunting_generation(state: AgentState, config: RunnableConfig):
    """Generate the final comprehensive threat hunting report with retry logic for token limits.
    
    This function takes all collected threat hunting findings and synthesizes them into a 
    well-structured, comprehensive final report using the configured report generation model.
    
    Args:
        state: Agent state containing research findings and context
        config: Runtime configuration with model settings and API keys
        
    Returns:
        Dictionary containing the final report and cleared state
    """
    # Step 1: Extract research findings and prepare state cleanup
    notes = state.get("notes", [])
    cleared_state = {"notes": {"type": "override", "value": []}}
    findings = "\n".join(notes)
    
    # Step 2: Configure the final report generation model
    configurable = Configuration.from_runnable_config(config)
    writer_model_config = {
        "model": configurable.final_report_model,
        "max_tokens": configurable.final_report_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.final_report_model, config),
        "tags": [_LANGSMITH_NO_STREAM_TAG]
    }
    

    # Step 3: Attempt report generation with token limit retry logic
    max_retries = 3
    current_retry = 0
    findings_token_limit = None
    
    while current_retry <= max_retries:
        try:
            # Create comprehensive prompt with all research context
            final_report_prompt = final_threathunting_generation_prompt.format(
                research_brief=state.get("research_brief", ""),
                messages=get_buffer_string(state.get("messages", [])),
                findings=findings,
                date=get_today_str()
            )
            
            logger.debug("Final report generation attempt %d prompts: %s", current_retry + 1, final_report_prompt)
            # Generate the final report with structured output
            logger.info("开始调用大模型生成结构化报告...")
            structured_model = (
                configurable_model
                .with_structured_output(AnalysisReport)
                .with_config(writer_model_config)
            )
            logger.debug("结构化模型配置完成")
            response = await structured_model.ainvoke([
                HumanMessage(content=final_report_prompt)
            ])
            logger.debug("大模型调用完成，响应类型: %s", type(response))
            logger.debug("响应内容: %s", response)

            # Return successful report generation with structured TTP list
            try:
                logger.debug("Raw response ttps type: %s", type(response.ttps))
                logger.debug("Raw response ttps: %s", response.ttps)
                ttps_list = [ttp.model_dump() for ttp in response.ttps]
                ttps_json = json.dumps(ttps_list, ensure_ascii=False)
                logger.debug("Generated ttps_json length: %d", len(ttps_json))
            except Exception as json_error:
                if isinstance(json_error, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.error("JSON serialization error: %s", json_error)
                logger.error("response.ttps content: %s", response.ttps)
                raise json_error
            return {
                "final_report": response.final_report,
                "messages": [AIMessage(content=response.final_report)],
                "ttps": ttps_json,
                **cleared_state
            }

        except Exception as e:
            logger.error("Final report generation error: %s", e)
            logger.error("Error type: %s", type(e))
            logger.error("Traceback: %s", traceback.format_exc())

            # 处理 JSON 解析错误（如 markdown 代码块问题）
            error_str = str(e)
            if "json_invalid" in error_str or "Invalid JSON" in error_str or "validation error" in error_str.lower():
                logger.warning("检测到 JSON 解析错误，尝试使用备选方案重新生成...")
                try:
                    final_report, ttps_json = await _try_fallback_json_parse(final_report_prompt, writer_model_config)
                    logger.info("备选方案解析成功")
                    return {
                        "final_report": final_report,
                        "messages": [AIMessage(content=final_report)],
                        "ttps": ttps_json,
                        **cleared_state
                    }
                except Exception as fallback_error:
                    if isinstance(fallback_error, (KeyboardInterrupt, SystemExit)):
                        raise
                    logger.error("备选解析方案也失败: %s", fallback_error)
                    # 继续到正常错误处理流程

            # Handle token limit exceeded errors with progressive truncation
            if is_token_limit_exceeded(e, configurable.final_report_model):
                current_retry += 1
                
                if current_retry == 1:
                    # First retry: determine initial truncation limit
                    model_token_limit = get_model_token_limit(configurable.final_report_model)
                    if not model_token_limit:
                        return {
                            "final_report": f"Error generating final report: Token limit exceeded, however, we could not determine the model's maximum context length. Please update the model map in deep_researcher/utils.py with this information. {e}",
                            "messages": [AIMessage(content="Report generation failed due to token limits")],
                            **cleared_state
                        }
                    # Use 4x token limit as character approximation for truncation
                    findings_token_limit = model_token_limit * 4
                else:
                    # Subsequent retries: reduce by 10% each time
                    findings_token_limit = int(findings_token_limit * 0.9)
                
                # Truncate findings and retry
                findings = findings[:findings_token_limit]
                continue
            else:
                # Non-token-limit error: return error immediately
                return {
                    "final_report": f"Error generating final report: {e}",
                    "messages": [AIMessage(content="Report generation failed due to an error")],
                    **cleared_state
                }
    
    # Step 4: Return failure result if all retries exhausted
    return {
        "final_report": "Error generating final report: Maximum retries exceeded",
        "messages": [AIMessage(content="Report generation failed after maximum retries")],
        **cleared_state
    }


def _validate_message_chain(recent_msgs):
    """确保消息链完整合法：去除开头孤立 ToolMessage 和末尾未完成 AIMessage。"""
    while recent_msgs and isinstance(recent_msgs[0], ToolMessage):
        logger.debug("重建时丢弃开头孤立 ToolMessage")
        recent_msgs = recent_msgs[1:]
    if recent_msgs and hasattr(recent_msgs[-1], 'tool_calls') and recent_msgs[-1].tool_calls:
        logger.debug("重建时丢弃末尾未完成的 AIMessage（带有 tool_calls 但无后续 ToolMessage）")
        recent_msgs = recent_msgs[:-1]
        while recent_msgs and isinstance(recent_msgs[0], ToolMessage):
            logger.debug("重建时再次丢弃开头孤立 ToolMessage")
            recent_msgs = recent_msgs[1:]
    return recent_msgs


def _rebuild_supervisor_messages(
    current_msgs,
    research_brief: str,
    notes: list,
    research_thoughts: list,
    follow_up_content: str = "",
    max_recent_msgs: int = 4,
    max_brief_chars: int = 1500,
    max_notes_chars: int = 2000,
    max_thoughts_chars: int = 800,
):
    """重建 supervisor_messages，用摘要替代旧历史，防止多轮人机反馈后消息无限膨胀。

    策略：
    1. 保留原始 SystemMessage（角色定义），丢弃之前轮次插入的摘要标记
    2. 保留最近 N 条 AI/Tool 消息（保持对话连贯性），过滤 HumanMessage 避免连续 user 角色
    3. 用 notes + research_thoughts + follow_up 构建上下文摘要消息替代被丢弃的旧历史
    4. 上下文摘要用 HumanMessage 而非 SystemMessage，避免某些 API 对 system 角色的限制
    """
    if not current_msgs or len(current_msgs) <= max_recent_msgs + 2:
        # 消息量不大，无需重建，直接返回
        return list(current_msgs)

    # 1. 保留原始 SystemMessage，过滤掉之前轮次插入的摘要/压缩标记
    original_system_msgs = []
    for m in current_msgs:
        if isinstance(m, SystemMessage):
            content = str(m.content) if hasattr(m, 'content') else ''
            # 过滤掉之前轮次插入的上下文重建消息，防止重复累积
            if '[上下文摘要]' in content or '[Compressed history]' in content:
                logger.debug("重建时过滤掉旧的上下文摘要 SystemMessage")
                continue
            original_system_msgs.append(m)

    # 2. 保留最近 N 条非 SystemMessage，同时过滤掉旧摘要 HumanMessage 和普通 HumanMessage
    #    避免产生连续 user 角色消息导致 API 报 Invalid messages
    non_system = []
    for m in current_msgs:
        if isinstance(m, SystemMessage):
            continue
        content = str(m.content) if hasattr(m, 'content') else ''
        # 过滤掉之前轮次插入的上下文摘要 HumanMessage，防止重复累积
        if '[上下文摘要]' in content or '[Compressed history]' in content:
            logger.debug("重建时过滤掉旧的上下文摘要 HumanMessage")
            continue
        # 只保留 AIMessage 和 ToolMessage，丢弃所有 HumanMessage
        # 因为上下文摘要已经包含了所有必要的用户输入信息
        if isinstance(m, HumanMessage):
            logger.debug("重建时过滤掉旧 HumanMessage，避免连续 user 角色")
            continue
        non_system.append(m)

    recent_msgs = non_system[-max_recent_msgs:] if len(non_system) > max_recent_msgs else non_system
    recent_msgs = _validate_message_chain(recent_msgs)

    # 3. 压缩原始调研需求（research_brief 可能包含完整的 Short TTP JSON，非常长）
    brief_text = ""
    if research_brief:
        if len(research_brief) > max_brief_chars:
            brief_text = research_brief[:max_brief_chars] + "\n...（需求已截断）"
        else:
            brief_text = research_brief

    # 4. 压缩调研摘要（取最近 20 条笔记，限制字符数）
    notes_text = ""
    if notes:
        notes_str = "\n\n".join(str(n) for n in notes[-20:])
        if len(notes_str) > max_notes_chars:
            notes_str = "...（前面笔记已省略）\n\n" + notes_str[-max_notes_chars:]
        notes_text = notes_str

    # 5. 压缩思考摘要（取最近 3 条 think_tool 思考记录）
    thoughts_text = ""
    if research_thoughts:
        recent_thoughts = research_thoughts[-3:]
        thoughts_str = "\n".join(f"- {t}" for t in recent_thoughts)
        if len(thoughts_str) > max_thoughts_chars:
            thoughts_str = "...（前面思考已省略）\n\n" + thoughts_str[-max_thoughts_chars:]
        thoughts_text = thoughts_str

    # 6. 用 HumanMessage 构建上下文摘要（避免 SystemMessage 在某些 API 中报 Invalid messages）
    summary_parts = ["[上下文摘要] 以下是你之前调研的进展，请基于这些信息继续决策："]
    if brief_text:
        summary_parts.append(f"【原始需求摘要】\n{brief_text}")
    if notes_text:
        summary_parts.append(f"【调研发现摘要】\n{notes_text}")
    if thoughts_text:
        summary_parts.append(f"【最近思考】\n{thoughts_text}")
    if follow_up_content:
        summary_parts.append(f"【用户补充反馈】\n{follow_up_content}")
    summary_parts.append("[上下文摘要结束]")

    context_msg = HumanMessage(content="\n\n".join(summary_parts))

    # 7. 组装最终消息链：原始系统提示 → 上下文摘要 → 最近原始消息
    #    确保消息链合法：System → Human → AI → Tool → AI → Tool ...
    result = list(original_system_msgs)
    result.append(context_msg)
    result.extend(recent_msgs)

    # 记录重建前后的变化及消息角色分布
    old_chars = sum(len(str(m.content)) for m in current_msgs if hasattr(m, 'content'))
    new_chars = sum(len(str(m.content)) for m in result if hasattr(m, 'content'))
    old_roles = []
    new_roles = []
    for m in current_msgs:
        if hasattr(m, 'type'):
            old_roles.append(m.type)
        elif hasattr(m, '__class__'):
            old_roles.append(m.__class__.__name__.replace('Message', '').lower())
    for m in result:
        if hasattr(m, 'type'):
            new_roles.append(m.type)
        elif hasattr(m, '__class__'):
            new_roles.append(m.__class__.__name__.replace('Message', '').lower())
    logger.info(
        "supervisor_messages 重建: %d 条 → %d 条, %d 字符 → %d 字符, 角色分布: %s → %s",
        len(current_msgs), len(result), old_chars, new_chars, old_roles, new_roles
    )

    return result


def _build_feedback_update(state, research_brief, notes, research_thoughts, follow_up_content, feedback_round):
    """构建继续/补充调研时返回 supervisor 的 update payload。"""
    current_supervisor_msgs = state.get("supervisor_messages", [])
    if isinstance(current_supervisor_msgs, dict) and current_supervisor_msgs.get("type") == "override":
        current_supervisor_msgs = current_supervisor_msgs.get("value", [])

    rebuilt_msgs = _rebuild_supervisor_messages(
        current_msgs=current_supervisor_msgs,
        research_brief=research_brief,
        notes=notes,
        research_thoughts=research_thoughts,
        follow_up_content=follow_up_content,
    )

    return {
        "supervisor_messages": {
            "type": "override",
            "value": rebuilt_msgs,
        },
        "feedback_round": feedback_round + 1,
    }


async def human_feedback_node(state: AgentState, config: RunnableConfig) -> Command[Literal["research_supervisor", "final_threathunting_generation", "mitre_investigation"]]:
    """人机反馈节点，用于展示调研结果并获取用户反馈以决定是否继续调研或生成报告。

    该节点使用 LangGraph 的 interrupt 机制暂停图执行，等待用户输入。根据用户反馈：
    - 如果用户接受结果，继续到报告生成阶段
    - 如果用户要求补充调研，返回到 supervisor 进行额外研究

    Args:
        state: 当前 Agent 状态，包含调研笔记和消息历史
        config: 运行时配置

    Returns:
        Command 指令，路由到 research_supervisor 或报告生成节点
    """
    # 获取当前的调研笔记和 supervisor 思考记录
    notes = state.get("notes", [])
    research_thoughts = state.get("research_thoughts", [])
    research_brief = state.get("research_brief", "")

    # 检查人机交互轮次上限
    feedback_round = state.get("feedback_round", 0)
    configurable = Configuration.from_runnable_config(config)
    # 人机反馈轮次独立配置，硬上限为 5 次
    max_rounds = min(configurable.max_human_feedback_rounds, 5)

    # 根据环境变量决定是否使用 MITRE 调查子图
    use_mitre_investigation = os.getenv("USE_MITRE_INVESTIGATION_SUBGRAPH", "false").lower() == "true"
    next_node = "mitre_investigation" if use_mitre_investigation else "final_threathunting_generation"

    if feedback_round >= max_rounds:
        logger.info("人机交互轮次已达上限 (%d/%d max_human_feedback_rounds)，跳过中断直接生成报告", feedback_round, max_rounds)
        return Command(goto=next_node)

    # 从 config 读取 short_ttp_summary（config 可穿透子图）
    short_ttp_summary = ""
    if hasattr(config, "configurable") and isinstance(config.configurable, dict):
        short_ttp_summary = config.configurable.get("short_ttp_summary", "")
    elif isinstance(config, dict) and "configurable" in config:
        short_ttp_summary = config["configurable"].get("short_ttp_summary", "")
    if not short_ttp_summary and hasattr(config, "short_ttp_summary"):
        short_ttp_summary = getattr(config, "short_ttp_summary") or ""
    if not short_ttp_summary:
        short_ttp_summary = state.get("short_ttp_summary", "")

    # 构建原始调研笔记摘要（用于 notes_preview 辅助展示）
    findings_summary = "\n\n".join(notes) if notes else "暂无调研结果"

    # 构建展示给用户的反馈请求内容：全量返回思考，由前端决定展示策略
    if research_thoughts:
        thoughts_summary = "\n\n".join(
            f"【思考 {i+1}】{t}" for i, t in enumerate(research_thoughts)
        )
    else:
        thoughts_summary = "暂无调查思路记录"

    # 优先使用 short_ttp_summary 作为原始需求展示，更友好简洁
    display_original_request = short_ttp_summary if short_ttp_summary else research_brief


    feedback_request = f"""
## 原始需求
请根据以下Short TTP告警信息从网络安全、主机安全和应用安全三个维度综合进行威胁狩猎分析：
{display_original_request}

## 当前调查思路
{thoughts_summary[:HUMAN_FEEDBACK_MAX_THOUGHTS_CHARS]}{"..." if len(thoughts_summary) > HUMAN_FEEDBACK_MAX_THOUGHTS_CHARS else ""}

"""
#---
#请审核以上调查思路，您的选择：
#1. **点击结束** - 接受当前思路不再中断，进行调研并生成最终威胁狩猎报告
#2. **输入具体补充需求并点击发送** - 例如 "请补充关于XXX的调研" 或 "需要更多关于网络层面的信息"，将继续深入调研

    # 使用 interrupt 暂停执行并等待用户输入
    logger.info("等待用户反馈，当前调研笔记数量: %d, think_tool 思考记录数: %d", len(notes), len(research_thoughts))
    user_feedback = interrupt({
        "question": feedback_request,
        "notes_preview": findings_summary[:1000] if findings_summary else "",
        "research_brief": display_original_request
    })

    logger.info("收到用户反馈: %s", user_feedback)

    # 解析用户反馈
    if user_feedback is None:
        # 用户未提供反馈，默认继续到报告生成
        logger.info("用户未提供反馈，继续生成报告")
        return Command(goto=next_node)

    # 标准化用户输入
    feedback_str = str(user_feedback).strip().lower()

    # 判断用户意图
    accept_keywords = ["/finish"]
    continue_keywords = ["/continue"]

    if any(keyword in feedback_str for keyword in accept_keywords):
        # 用户接受，继续到 MITRE 调查或报告生成
        if use_mitre_investigation:
            logger.info("用户接受调研结果，进入 MITRE 调查阶段（调查后直接生成最终报告）")
        else:
            logger.info("用户接受调研结果，进入报告生成阶段")
        return Command(goto=next_node)
    elif any(keyword in feedback_str for keyword in continue_keywords):
        # 用户（或超时自动机制）要求继续调研，使用通用文案返回 supervisor
        logger.info("用户要求继续调研，返回 supervisor 阶段，当前轮次: %d/%d(max_human_feedback_rounds)", feedback_round, max_rounds)
        return Command(
            goto="research_supervisor",
            update=_build_feedback_update(
                state, research_brief, notes, research_thoughts,
                "请基于当前已有的调研结果继续深入研究，补充更多细节信息。",
                feedback_round,
            ),
        )
    else:
        # 用户要求补充调研，将反馈添加到消息中并返回 supervisor
        logger.info("用户要求补充调研，返回 supervisor 阶段，当前轮次: %d/%d(humaninloop rounds/max_human_feedback_rounds)", feedback_round, max_rounds)
        update = _build_feedback_update(
            state, research_brief, notes, research_thoughts,
            f"用户要求补充调研，请根据以下反馈继续深入研究：\n\n用户反馈：{user_feedback}\n\n请基于当前已有的调研结果，针对用户的补充需求进行额外研究。",
            feedback_round,
        )
        update["messages"] = state.get("messages", []) + [HumanMessage(content=f"[补充需求] {user_feedback}")]
        return Command(goto="research_supervisor", update=update)

def create_shorttp_triger_longttp_builder(
    enable_human_feedback: bool = False
) -> StateGraph:
    """创建 shortTTP 触发 longTTP 的图构建器

    Args:
        enable_human_feedback: 是否启用人工反馈节点。如果为 True，workflow 会在调研后
                              暂停等待用户反馈；如果为 False，直接生成最终报告。

    Returns:
        配置好的 StateGraph 实例
    """
    builder = StateGraph(
        AgentState,
        input=AgentInputState,
        config_schema=Configuration
    )
    builder.add_node("construct_prompt", construct_shorttp_trigger_longttp_prompt)
    builder.add_node("research_supervisor", supervisor_subgraph)
    builder.add_node("final_threathunting_generation", final_threathunting_generation)

    # 根据环境变量决定是否使用 MITRE 调查子图
    use_mitre_investigation = os.getenv("USE_MITRE_INVESTIGATION_SUBGRAPH", "false").lower() == "true"
    if use_mitre_investigation:
        builder.add_node("mitre_investigation", mitre_investigation_node)
        logger.info("MITRE 调查子图已创建")

    # Define main workflow edges for sequential execution
    builder.add_edge(START, "construct_prompt")
    builder.add_edge("construct_prompt", "research_supervisor")

    if enable_human_feedback:
        # 启用 human_feedback：research_supervisor -> human_feedback -> [mitre_investigation 或 final_threathunting_generation] -> END
        builder.add_node("human_feedback", human_feedback_node)
        builder.add_edge("research_supervisor", "human_feedback")
        # human_feedback 节点使用 Command 进行条件路由
        # 如果 use_mitre_investigation 为 True，human_feedback_node 返回 "mitre_investigation"
        # 如果为 False，返回 "final_threathunting_generation"
        # 两种情况下都需要连接到 END
        if use_mitre_investigation:
            builder.add_edge("mitre_investigation", END)
        else:
            builder.add_edge("final_threathunting_generation", END)
    else:
        # 禁用 human_feedback
        if use_mitre_investigation:
            # research_supervisor -> mitre_investigation -> END
            builder.add_edge("research_supervisor", "mitre_investigation")
            builder.add_edge("mitre_investigation", END)
        else:
            # research_supervisor 直接到 final_threathunting_generation
            builder.add_edge("research_supervisor", "final_threathunting_generation")
            builder.add_edge("final_threathunting_generation", END)

    return builder


# 默认构建（兼容旧代码，不启用 human_feedback）
shorttp_triger_longttp_builder = create_shorttp_triger_longttp_builder(
    enable_human_feedback=False
)

