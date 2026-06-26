# AI Agent组件说明

[English](README_EN.md) | 中文

| Short TTP（跨域关联实时告警）生成 | 基于 MITRE ATT&CK 输出战术、技术、过程、置信度、摘要、攻击者 IP 和关联事件 ID。 |
| Long TTP （长跨度高级威胁攻击链）调查 | 从 Short TTP 触发更长时间跨度的高级威胁调查 |

## 运行依赖

运行容器前需要准备以下外部服务：

- Kafka
- Redis
- ElasticSearch 8.x
- PostgreSQL
- OpenAI-compatible LLM endpoint
- DashScope API Key，如果启用 MITRE RAG embedding/rerank 路径

Kafka `KAFKA_TOPIC` 默认是 `agent`。该Topic应接收上游基线裁决服务输出的高价值安全事件。

## 配置说明

集成于deploy\docker-compose-agent.yml

```yaml
services:
  security-analysis:
    image: essaigroup/deepxdr-analysis:v0.3.0-alpha
    container_name: security-analysis
    networks:
      - security-net
      - kafka-net
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_started
      redis:
        condition: service_started
      kafka:
        condition: service_healthy
      baseline-adjudication:
        condition: service_started
    environment:
      DATABASE_URL: postgresql+asyncpg://security_user:security_pass@postgres:5432/security_db
      REDIS_URL: redis://redis:6379/0
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      KAFKA_TOPIC: agent
      KAFKA_GROUP_ID: security-analysis-group
      LOG_LEVEL: DEBUG
      API_PORT: 8000
      
      ELASTICSEARCH_HOST: <app-host-ip>
      ELASTICSEARCH_PORT: 9201

      ELASTICSEARCH_MCP_URL: http://<app-host-ip>:8000/mcp
      FILESYSTEM_MCP_URL: ws://<app-host-ip>:8001/message
      GREP_MCP_URL: ws://<app-host-ip>:8003/message
      
      OPENAI_API_KEY: <your-llm-api-key>
      OPENAI_BASE_URL: <your-llm-api-base-url> 
      # [Required] Short TTP威胁分析及Long TTP主循环所使用的模型    
      OPENAI_MODEL: <your-llm-model-name> 
      # [Required] Long TTP深度研究阶段使用的模型，建议使用较强模型
      RESEARCH_MODEL: <your-llm-model-name> 
      # [Required] 长上下文压缩/截断阶段使用的模型，建议选择成本较低且上下文能力稳定的模型
      COMPRESSION_MODEL: <your-llm-model-name> 
      # [Required] 摘要生成阶段使用的模型
      SUMMARIZATION_MODEL: <your-llm-model-name>
      # [Required] 最终报告生成阶段使用的模型，建议选择输出质量更高的模型
      FINAL_REPORT_MODEL: <your-llm-model-name> 
      # [Required] MITRE RAG 节点中的 LLM 判定模型。
      MITRE_RAG_LLM_MODEL: <your-llm-model-name> 
      # 默认开启即可
      USE_MITRE_INVESTIGATION_SUBGRAPH: true
      # [Required] 人机反馈等待秒数,超时将跳过本轮人工参与继续威胁分析
      HUMAN_FEEDBACK_TIMEOUT_SECONDS: 1800
      # 人机交互的最高次数
      MAX_HUMAN_FEEDBACK_ROUNDS: 4
      # Deep researcher 最大调研迭代次数；增大后会增加模型调用成本和耗时
      MAX_RESEARCHER_ITERATIONS: 3
      # 单轮 ReAct 调研允许的最大工具调用次数
      MAX_REACT_TOOL_CALLS: 9
      # 默认值
      USE_MITRE_INVESTIGATION_SUBGRAPH: true
      # [Optional]用于langsmith调试
      LANGSMITH_API_KEY: <your-langsmith-api-key>
      LANGSMITH_PROJECT: <your-langsmith-api-key>
      LANGSMITH_TRACING: <true or false>
      # 默认值
      LONG_TTP_TRIGGER_SUPPRESSION_SECONDS: 5
      # [Required] 文件系统 MCP 允许访问的根目录,与app侧的<your-app-workspace>一致,如/src/dotcms。
      MCP_FILESYSTEM_ALLOWED_ROOT: <your-app-workspace>
      # [Required] Web UI 调用后端 API 时会使用该值。生产环境请使用随机长字符串，不要使用示例值。
      BACKEND_API_KEY: <your-random-token>

      # [Required]DashScope embedding 的 OpenAI-compatible 接口地址，用于 MITRE RAG 向量化召回。
      DASHSCOPE_EMBEDDING_BASE_URL: <your-embedding-base-url>
      # [Required]DashScope embedding 模型名，需要和账号可用模型保持一致。
      DASHSCOPE_EMBEDDING_MODEL: <your-embedding-model-name>
      # [Required]DashScope rerank 接口地址，用于对 embedding 召回候选进行重排。
      DASHSCOPE_RERANK_BASE_URL: <your-rerank-base-url>
      # [Required]DashScope rerank 模型名，需要确认账号和地域支持该模型。
      DASHSCOPE_RERANK_MODEL: <your-rerank-model-name>
      # [Required]DashScope API Key 用于 MITRE RAG 的 embedding/rerank 路径
      DASHSCOPE_API_KEY: ${your-embedding-rerank-key}
      # [Optional]实验性功能，需配合部署ACL MCP
      MCP_SERVER_URL: <your-acl-mcp-url>
      # 默认值
      GET_API_KEYS_FROM_CONFIG: false
    restart: unless-stopped
```

## 构建镜像

在 `ai_agent` 目录下构建镜像：

```bash
docker build -t security-analysis:latest .
```

## 健康检查

```bash
curl http://localhost:8000/health
```

需要 API Key 的接口请携带请求头：

```bash
curl -H "X-API-Key: $BACKEND_API_KEY" \
  http://localhost:8000/longttp
```
