# MITRE Investigation 子图使用指南

## 概述

现在系统支持使用 `mitre_threat_investigation` 的完整调查流程作为子图来生成报告。这提供了比原有 `final_threathunting_generation` 更准确的技术映射和更丰富的上下文信息。

## 两种方式对比

| 特性 | 原有方式 (final_threathunting_generation) | MITRE 子图方式 (mitre_investigation) |
|------|------------------------------------------|-------------------------------------|
| **技术识别** | 基于 LLM 直接提取 TTP | 使用 triage + mapping agent，更精确 |
| **技术验证** | 无 | 通过 MCP 查询真实 MITRE 数据库验证 |
| **威胁情报** | 依赖 LLM 知识 | 查询真实 APT 组织和软件关联 |
| **检测建议** | LLM 生成 | 基于 STIX 数据组件 + LLM 增强 |
| **缓解措施** | LLM 生成 | 查询真实 MITRE 缓解措施 |
| **执行时间** | 较快 (~10-30s) | 较慢 (~30-80s) |

## 工作流对比

### 原有方式
```
research_supervisor → final_threathunting_generation → END
```

### MITRE 子图方式
```
research_supervisor → mitre_investigation (子图) → END
                    ↓
            [triage → mapping → intel/detection/mitigation(这三个并行)
             → detection_reasoning → report]
```

## 使用方法

### 1. 通过配置启用

```python
from ttp_generator.dx_analyzer.deep_researcher import create_shorttp_triger_longttp_builder

# 方式1: 使用 MITRE 子图（推荐用于需要精确 TTP 映射的场景）
builder = create_shorttp_triger_longttp_builder(
    enable_human_feedback=False,
)
workflow = builder.compile()

# 方式2: 使用原有方式（推荐用于快速生成报告）
builder = create_shorttp_triger_longttp_builder(
    enable_human_feedback=False,
)
workflow = builder.compile()
```

### 2. 通过环境变量切换

```bash
# 启用 MITRE 调查子图
export USE_MITRE_INVESTIGATION_SUBGRAPH=true

# 禁用（使用原有方式）
export USE_MITRE_INVESTIGATION_SUBGRAPH=false
```

## 输出差异

### 原有方式输出
```python
{
    "final_report": "Markdown 格式的报告",
    "ttps": "[{\"id\": \"TA0002\", \"techniques\": [...]}]",  # JSON 字符串
    "mitre_enrichment": None
}
```

### MITRE 子图方式输出
```python
{
    "final_report": "包含 MITRE 详情的 Markdown 报告",
    "ttps": "[{\"id\": \"TA0002\", \"techniques\": [...]}]",  # 从确认技术生成
    "mitre_enrichment": {
        "confirmed_techniques": [...],  # 经过验证的技术
        "intel": {"groups": [...], "software": [...]},  # 威胁情报
        "detections": {...},  # 检测建议
        "mitigations": {...},  # 缓解措施
        "completed_agents": [...],  # 完成的代理
        "timings": {...},  # 执行时间
    }
}
```

## 状态转换

### 输入状态转换

```python
# AgentState 中的数据转换为 InvestigationState
{
    "research_brief": "...",  # → incident_text 的一部分
    "notes": [...],           # → incident_text 的一部分
    "messages": [...],        # → 如果以上为空，提取用户消息
}
```

### 输出状态转换

```python
# InvestigationState 转换回 AgentState
{
    "report_markdown": "...",     # → final_report
    "confirmed_techniques": [...], # → ttps (转换格式)
    "intel/detections/mitigations": # → mitre_enrichment
}
```

## 完整示例

```python
import asyncio
from ttp_generator.dx_analyzer.deep_researcher import create_shorttp_triger_longttp_builder

async def main():
    # 创建使用 MITRE 子图的工作流
    builder = create_shorttp_triger_longttp_builder(
        enable_human_feedback=False,
    )
    workflow = builder.compile()

    # 运行
    result = await workflow.ainvoke({
        "messages": [{"role": "user", "content": "分析以下威胁：发现 PowerShell 执行可疑命令..."}]
    })

    # 获取结果
    print("=== 最终报告 ===")
    print(result["final_report"][:1000])

    print("\n=== TTPs ===")
    print(result.get("ttps", "N/A")[:500])

    print("\n=== MITRE 增强信息 ===")
    enrichment = result.get("mitre_enrichment", {})
    print(f"确认技术数: {len(enrichment.get('confirmed_techniques', []))}")
    print(f"威胁情报: {list(enrichment.get('intel', {}).keys())}")

asyncio.run(main())
```

## 故障排除

### 问题: MITRE 子图执行失败

**检查:**
1. `mitre_threat_investigation` 模块是否可导入
2. MCP 服务器是否可访问
3. 查看日志中的具体错误

**解决:**
```python
# 回退到原有方式
import os
os.environ["USE_MITRE_INVESTIGATION_SUBGRAPH"] = "false"
```

### 问题: 执行时间过长

MITRE 子图需要执行多个 agent：
- triage (~2-5s)
- mapping (~3-8s)
- intel/detection/mitigation 并行 (~5-10s)
- detection_reasoning (条件, ~5-15s)
- report (~10-30s)

总计约 30-80 秒，如果超时请：
1. 增加超时设置
2. 使用原有方式
3. 减少研究笔记量

### 问题: 技术识别不准确

MITRE 子图的 triage agent 使用专门优化的提示词提取技术，如果仍不准确：
1. 在研究简报中明确提及技术ID
2. 在笔记中包含更多技术相关上下文
3. 检查 LLM 模型设置

## 性能优化建议

1. **复用 RAG 缓存**: 保留 ATT&CK catalog 和 embedding 缓存以减少首次映射耗时
2. **并行执行**: intel/detection/mitigation 已并行执行
3. **选择性启用**: 只在需要精确 TTP 映射时启用子图
4. **预加载数据**: 预加载常用技术数据到内存

## 相关文件

| 文件 | 说明 |
|------|------|
| `mitre_attck_agent/attack_rag.py` | 本地 ATT&CK RAG、映射和增强实现 |
| `mitre_attck_agent/workflows/nodes.py` | MITRE 子图节点实现 |
| `ttp_generator/dx_analyzer/deep_researcher.py` | Long TTP 工作流接入 |

## 迁移指南

从原有方式迁移到 MITRE 子图：

1. 设置环境变量 `USE_MITRE_INVESTIGATION_SUBGRAPH=true`
2. 检查输出格式（`mitre_enrichment` 结构更丰富）
3. 调整超时设置（子图执行时间更长）
4. 测试验证（比较两种方式的输出质量）

如果需要回退：
1. 设置 `USE_MITRE_INVESTIGATION_SUBGRAPH=false`
2. 或移除环境变量（默认使用原有方式）
