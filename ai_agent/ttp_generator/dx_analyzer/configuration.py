"""Configuration management for the Open Deep Research system."""

import os
from typing import Any, List, Optional

_DEFAULT_RESEARCH_MODEL = "gpt-4.1"
_DEFAULT_SUMMARIZATION_MODEL = "gpt-4.1-mini"

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field


class MCPConfig(BaseModel):
    """Configuration for Model Context Protocol (MCP) servers."""
    
    url: Optional[str] = Field(
        default=None,
        optional=True,
    )
    """The URL of the MCP server"""
    tools: Optional[List[str]] = Field(
        default=None,
        optional=True,
    )
    """The tools to make available to the LLM"""
    auth_required: Optional[bool] = Field(
        default=False,
        optional=True,
    )
    """Whether the MCP server requires authentication"""

class Configuration(BaseModel):
    """Main configuration class for the Deep Research agent."""
    
    # General Configuration
    max_structured_output_retries: int = Field(
        default=3,
        metadata={
            "x_oap_ui_config": {
                "type": "number",
                "default": 3,
                "min": 1,
                "max": 10,
                "description": "Maximum number of retries for structured output calls from models"
            }
        }
    )
    allow_clarification: bool = Field(
        default=True,
        metadata={
            "x_oap_ui_config": {
                "type": "boolean",
                "default": True,
                "description": "Whether to allow the researcher to ask the user clarifying questions before starting research"
            }
        }
    )
    max_concurrent_research_units: int = Field(
        default=5,
        metadata={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 5,
                "min": 1,
                "max": 20,
                "step": 1,
                "description": "Maximum number of research units to run concurrently. This will allow the researcher to use multiple sub-agents to conduct research. Note: with more concurrency, you may run into rate limits."
            }
        }
    )
    max_researcher_iterations: int = Field(
        default=6,
        metadata={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 6,
                "min": 1,
                "max": 10,
                "step": 1,
                "description": "Maximum number of research iterations for the Research Supervisor. This is the number of times the Research Supervisor will reflect on the research and ask follow-up questions."
            }
        }
    )
    max_human_feedback_rounds: int = Field(
        default=2,
        metadata={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 2,
                "min": 1,
                "max": 5,
                "step": 1,
                "description": "Maximum number of human feedback rounds in the human-in-the-loop node. When reached, the system skips interrupt and generates the report directly."
            }
        }
    )
    max_react_tool_calls: int = Field(
        default=10,
        metadata={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 10,
                "min": 1,
                "max": 30,
                "step": 1,
                "description": "Maximum number of tool calling iterations to make in a single researcher step."
            }
        }
    )
    # Model Configuration
    summarization_model: str = Field(
        default=_DEFAULT_SUMMARIZATION_MODEL,
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "default": _DEFAULT_SUMMARIZATION_MODEL,
                "description": "Model for summarizing research results from Tavily search results"
            }
        }
    )
    summarization_model_max_tokens: int = Field(
        default=8192,
        metadata={
            "x_oap_ui_config": {
                "type": "number",
                "default": 8192,
                "description": "Maximum output tokens for summarization model"
            }
        }
    )
    max_content_length: int = Field(
        default=50000,
        metadata={
            "x_oap_ui_config": {
                "type": "number",
                "default": 50000,
                "min": 1000,
                "max": 200000,
                "description": "Maximum character length for webpage content before summarization"
            }
        }
    )
    research_model: str = Field(
        default=_DEFAULT_RESEARCH_MODEL,
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "default": _DEFAULT_RESEARCH_MODEL,
                "description": "Model for conducting research. NOTE: Make sure your Researcher Model supports the selected search API."
            }
        }
    )
    research_model_max_tokens: int = Field(
        default=10000,
        metadata={
            "x_oap_ui_config": {
                "type": "number",
                "default": 10000,
                "description": "Maximum output tokens for research model"
            }
        }
    )
    compression_model: str = Field(
        default=_DEFAULT_RESEARCH_MODEL,
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "default": _DEFAULT_RESEARCH_MODEL,
                "description": "Model for compressing research findings from sub-agents. NOTE: Make sure your Compression Model supports the selected search API."
            }
        }
    )
    compression_model_max_tokens: int = Field(
        default=8192,
        metadata={
            "x_oap_ui_config": {
                "type": "number",
                "default": 8192,
                "description": "Maximum output tokens for compression model"
            }
        }
    )
    final_report_model: str = Field(
        default=_DEFAULT_RESEARCH_MODEL,
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "default": _DEFAULT_RESEARCH_MODEL,
                "description": "Model for writing the final report from all research findings"
            }
        }
    )
    final_report_model_max_tokens: int = Field(
        default=10000,
        metadata={
            "x_oap_ui_config": {
                "type": "number",
                "default": 10000,
                "description": "Maximum output tokens for final report model"
            }
        }
    )
    # 人机反馈展示用字段
    short_ttp_summary: Optional[str] = Field(
        default=None,
        description="Short TTP 摘要，用于 human_feedback 节点展示原始需求",
    )

    # MCP server configuration
    mcp_config: Optional[MCPConfig] = Field(
        default=None,
        optional=True,
        metadata={
            "x_oap_ui_config": {
                "type": "mcp",
                "description": "MCP server configuration"
            }
        }
    )
    mcp_prompt: Optional[str] = Field(
        default=None,
        optional=True,
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "description": "Any additional instructions to pass along to the Agent regarding the MCP tools that are available to it."
            }
        }
    )
    # langsmith configuration
    langsmith_tracing: Optional[bool] = Field(
        default=False,
        optional=True,
        metadata={
            "x_oap_ui_config": {
                "type": "boolean",
                "description": "Whether to enable LangSmith tracing for the agent"
            }
        }
    )
    langsmith_endpoint: Optional[str] = Field(
        default="https://api.smith.langchain.com",
        optional=True,
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "default": "https://api.smith.langchain.com",
                "description": "The LangSmith endpoint URL"
            }
        }   
    )
    langsmith_api_key: Optional[str] = Field(
        default=None,
        optional=True,
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "description": "The LangSmith API key"
            }
        }   
    )
    langsmith_project: Optional[str] = Field(
        default=None,
        optional=True,
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "description": "The LangSmith project ID"
            }
        }   
    )
    # MITRE ATT&CK 集成配置
    enable_mitre_enrichment: bool = Field(
        default=True,
        metadata={
            "x_oap_ui_config": {
                "type": "boolean",
                "default": True,
                "description": "是否启用 MITRE ATT&CK 增强功能。启用后，系统会自动查询技术详情、生成可视化图层并增强报告。"
            }
        }
    )
    mitre_output_dir: str = Field(
        default="./mitre_output",
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "default": "./mitre_output",
                "description": "MITRE ATT&CK 可视化图层和增强报告的输出目录"
            }
        }
    )
    mitre_layer_name: str = Field(
        default="Threat Hunting Coverage",
        metadata={
            "x_oap_ui_config": {
                "type": "text",
                "default": "Threat Hunting Coverage",
                "description": "生成的 ATT&CK Navigator 图层名称"
            }
        }
    )
    mitre_domain: str = Field(
        default="enterprise",
        metadata={
            "x_oap_ui_config": {
                "type": "select",
                "default": "enterprise",
                "description": "MITRE ATT&CK 域",
                "options": [
                    {"label": "Enterprise", "value": "enterprise"},
                    {"label": "Mobile", "value": "mobile"},
                    {"label": "ICS", "value": "ics"}
                ]
            }
        }
    )
    use_mitre_investigation_subgraph: bool = Field(
        default=False,
        metadata={
            "x_oap_ui_config": {
                "type": "boolean",
                "default": False,
                "description": "是否使用 MITRE investigation 子图替代原有的 final_threathunting_generation。启用后，将使用 mitre_threat_investigation 的完整调查流程（triage→mapping→intel→detection→mitigation→report）生成报告和TTP映射，提供更准确的结果。"
            }
        }
    )

    @classmethod
    def from_runnable_config(
        cls, config: Optional[RunnableConfig] = None
    ) -> "Configuration":
        """Create a Configuration instance from a RunnableConfig."""
        configurable = config.get("configurable", {}) if config else {}
        field_names = list(cls.model_fields.keys())
        values: dict[str, Any] = {
            field_name: os.environ.get(field_name.upper(), configurable.get(field_name))
            for field_name in field_names
        }
        return cls(**{k: v for k, v in values.items() if v is not None})

    class Config:
        """Pydantic configuration."""
        
        arbitrary_types_allowed = True
