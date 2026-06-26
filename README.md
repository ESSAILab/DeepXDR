# DeepXDR

[English](README_EN.md) | 中文

[![Status](https://img.shields.io/badge/status-alpha-orange)](#项目状态)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](ai_agent/pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

DeepXDR 是一个面向实时安全运营的智能威胁分析与调查系统。它接收来自主机、应用和网络遥测源的安全告警与行为事件，先通过基线裁决筛选高价值信号，再由 AI Agent 关联多源证据并生成基于 MITRE ATT&CK 的 TTP 分析。对于需要更长时间跨度研判的事件，系统可以从 Short TTP（跨域关联实时告警） 进一步触发 Long TTP（高级威胁攻击链） 调查，并支持分析师通过人机反馈补充调查方向。面向新兴 AI 智能体运行行为、工具调用和执行轨迹的安全分析与响应能力正在适配中。

## 项目状态

> **Alpha software - investigation-first mode.** DeepXDR 当前是早期研究与工程实现，仅适用于单用户、单应用的实验与验证场景，尚未支持多用户、多租户或多应用生产部署。系统重点在实时告警接入、异常行为发现、TTP 生成和高级威胁调查。当前版本的 XDR Response 能力仍不完整：生产级响应编排、审批流、回滚、策略校验、跨控制面联动和完整执行审计尚未完成。`ai_agent/defense/` 中的 MCP 防御接口属于实验性集成，不应被理解为已经具备完整自动处置能力。

## 系统职责与处理边界

DeepXDR 将待守护应用、遥测源、数据裁决、AI 分析和可视化交互拆分为不同职责边界：待守护应用是被观测对象，遥测源负责产生安全数据，后续链路负责筛选、分析与呈现结果。

| 对象 / 阶段 | 说明 | 对应目录 |
| --- | --- | --- |
| 应用  | 被 DeepXDR 守护和观测的业务系统。应用本身不承担威胁分析职责，但可以集成 OpenRASP/RASP 等遥测源，并按部署要求共享必要工作空间给 MCP Server。| `third_party/dotcms/` |
| 遥测源 | 负责从主机、应用和网络侧产生安全告警与行为事件，并将数据交给数据汇聚与基线裁决链路。| `third_party/falco/`</br>`third_party/openrasp/`</br>`third_party/suricata/` |
| 数据汇聚与基线裁决</br> | 接收 Falco、OpenRASP/RASP、Suricata 等遥测源产生的安全数据。明确告警会直接进入后续分析流程；原始行为数据会先用于构建正常行为基线，未命中基线的异常行为也会进入后续分析流程。| `baseline_adjudication/`  |
| AI 威胁分析与调查</br> | 对已经过筛选和裁决的高价值安全事件进行聚合分析，生成 Short TTP，并按需触发 Long TTP / 高级持续性威胁调查。| `ai_agent/`  |
| 可视化与交互 | 面向分析师展示 TTP、调查结果和反馈入口 | `web_ui/` |


## 核心能力

| 能力 | 说明 |
| --- | --- |
| 多维遥测源接入 | 对 Falco、OpenRASP/RASP、Suricata 的明确告警和基线行为进行实时分析和透传。 |
| 行为基线裁决 | 对原始行为事件提取稳定字段、生成 SHA-256 哈希、构建 Redis 行为基线，并识别超出基线的异常行为。 |
| 多源证据关联 | 将主机、应用、网络侧事件聚合到动态事件窗口中，形成一次短期攻击动作的证据集合。 |
| Short TTP（跨域关联实时告警）生成 | 基于 MITRE ATT&CK 输出战术、技术、过程、置信度、摘要、攻击者 IP 和关联事件 ID。 |
| Long TTP （高级威胁攻击链）调查 | 从 Short TTP 触发更长时间跨度的高级威胁调查 |
| 人机反馈 | Long TTP 调查支持 LangGraph interrupt，允许人类分析师补充调查方向、继续或结束调查。 |
| API 与仪表板 | FastAPI 提供查询、触发、反馈和统计接口；`web_ui/` 提供 TTP 仪表板。 |

## 支持的遥测源

当前版本仅支持以下输入类型：

| 遥测源 | 采集事件类型 | 
| --- | --- |
| Falco | 定制化修改Falco，除原生Falco告警外，还会采集全量open_write和execve事件用于构建行为基线。 | 
| OpenRASP | 定制化修改OpenRASP，除原生OpenRASP告警外，还会采集sql，readfile, fileUpload，command事件用于构建行为基线。 |
| Suricata | 未修改，仅采集原生Sruicata告警，不参与基线裁决。 |

非上述类型的数据当前不会进入 AI Agent 分析链路。后续计划扩展更多主机、网络、应用、云审计和 AI 智能体遥测源。

## 架构

```mermaid
flowchart LR
    Sensors["Falco / OpenRASP / Suricata"] --> SourceTopic["Kafka topic: events"]
    SourceTopic --> Baseline["baseline_adjudication"]
    Baseline --> Redis["Redis behavior baseline"]
    Baseline --> BaselineFile["baseline.json"]
    Baseline --> AgentTopic["Kafka topic: agent"]
    AgentTopic --> Consumer["KafkaEventConsumer"]
    Consumer --> Window["DynamicEventWindowManager"]
    Window --> STTP["ShortTTPGenerator"]
    STTP --> MITREShort["MITRE ATT&CK mapping / RAG for Short TTP"]
    MITREShort --> ES["ElasticSearch: sttp-*"]
    STTP --> LTTP["Long TTP investigation"]
    LTTP --> Research["Deep researcher / domain tracing"]
    Research --> HITL["Human feedback"]
    HITL --> Research
    Research --> FinalReport["Final threat-hunting report"]
    HITL --> FinalReport
    Research -. optional MITRE subgraph .-> MITRELong["MITRE RAG triage -> mapping -> intel / detection / mitigation -> report"]
    HITL -. optional MITRE subgraph .-> MITRELong
    FinalReport --> PG["PostgreSQL checkpoints and records"]
    MITRELong --> PG
    HITL --> RedisSession["Redis feedback sessions"]
    ES --> API["FastAPI"]
    PG --> API
    RedisSession --> API
    API --> UI["web_ui dashboard"]
```

数据处理流程：
1. 遥测数据进入 Kafka `events`。
2. `baseline_adjudication` 消费 `events`。
3. 确切告警直接推送到 Kafka `agent`。
4. 原始行为事件在基线阶段用于构建 Redis 行为基线。
5. 检测阶段中，未命中基线的原始行为事件被判定为异常并推送到 `agent`。
6. `ai_agent` 从 `agent` 消费高价值安全事件。
7. `DynamicEventWindowManager` 将时间上接近的事件聚合为动态窗口。
8. `ShortTTPGenerator` 对关闭窗口并发分析，生成 Short TTP。
9. Short TTP 写入 ElasticSearch。
10. 用户可基于 Short TTP 触发 Long TTP 调查，必要时通过人机反馈补充调查方向。

## Quickstart

DeepXDR 按部署位置划分为 app 侧和 agent 侧，两侧可以部署在同一网络下的不同主机上。

app 侧部署在待守护应用所在主机，包含待守护应用、遥测源，以及 filebeat、logstash 等数据汇聚组件。部分遥测源需要与应用集成，例如 OpenRASP/RASP 需要安装到待守护应用中。

agent 侧部署 DeepXDR 的核心分析与交互组件，包括 AI 威胁分析与调查服务、API 服务和 `web_ui` 仪表盘。

docker compose 中各组件的关系如下：

<p align="center">
  <img src="assets/images/deploy.png" alt="部署图">
</p>

注意：Suricata为非容器形态部署，docker compose中不体现。OpenRASP以探针形式集成在待守护应用容器中。

**app侧安装部署：**
  
### 1. 按需启动遥测源

Falco参考：[点击查看README](third_party/falco/README.md)
OpenRASP参考：[点击查看README](third_party/openrasp/README.md)
Suricata参考：[点击查看README](third_party/suricata/README.md)

注意：为支持基线构建、异常裁决功能，我们对Falco配置文件、OpenRASP源码做了定制化修改。

### 2. 安装应用

以dotcms为例，启动方式参考：[点击查看README](third_party/dotcms/README.md)

### 3. 安装MCP Server

以dotcms为例，该应用工作空间为/src/dotcms，为保证AI威胁分析智能体查看、检索该工作空间的文件内容，需将该工作空间通过共享卷的方式与filesystem-mcp-server服务、grep-mcp-server服务共享。配置方法见第4节。

### 4. 安装app侧组件

[docker-compose-app.yml](deploy/docker-compose-app.yml)

启动方法：

```
cd deploy
docker-compose -f docker-compose-app.yml up -d
```

docker-compose-app.yml配置说明：
[Required]为必须配置项，[Optional]为可选配置项，未做标记的保持默认值即可。
注意：以下为关键配置片段，不是完整 compose 文件，完整配置以deploy目录为准。

```yaml
services:
  elasticsearch-mcp-server:
    image: essaigroup/deepxdr-es-mcp-server:v0.3.0-alpha
    container_name: app-elasticsearch-mcp-server
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9201
      - VERIFY_CERTS=false
      - DISABLE_HIGH_RISK_OPERATIONS=true
      # [Optional]限制查询返回结果中单个字符串的最大长度，超出部分将被截断并以 `"..."` 后缀标识。设置为 `0` 表示禁用长度截断
      - EQL_MAX_FIELD_LENGTH=1000
      # [Optional]限制查询返回结果中字符串列表保留的最大长度，超出部分将被截断。设置为 `0` 表示禁用列表截断
      - EQL_MAX_LIST_ITEMS=5
    ...
  
  filesystem-mcp-server:
    image: essaigroup/deepxdr-filesystem-mcp-server:v0.3.0-alpha
    container_name: app-filesystem-mcp-server
    volumes:
      # [Required]cms-shared由dotcms应用共享出来，此处值应填入dotcms服务相同字段
      - cms-shared:[your-app-workspace]
    ...

  grep-mcp-server:
    image: essaigroup/deepxdr-grep-mcp-server:v0.3.0-alpha
    container_name: app-grep-mcp-server
    environment:
      # [Optional]配置单词grep最多返回结果，保持默认即可
      MCP_GREP_MAX_RESULTS: 10
    volumes:
      # [Required]cms-shared由dotcms应用共享出来，此处值应填入dotcms服务相同字段
      - cms-shared:[your-app-workspace]
    ...

  #[Required]示例应用依赖的服务,用户可配置为自己的应用
  dotcms-elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:7.9.1
    container_name: app-elasticsearch
    ...

  #[Required]示例应用，由dotcms、dotcms-elasticsearch、dotcms-db三个服务组成，用户可配置为自己的应用
  dotcms:
    image: essaigroup/deepxdr-dotcms:v0.3.0
    container_name: app-dotcms
    depends_on:
      dotcms-elasticsearch:
        condition: service_started
      dotcms-db:
        condition: service_started
    entrypoint: ["sh"]
    command:
      - -c
      - |
        # [Required]执行 RASP 安装，如用户自行编译rasp安装包，则需在构建应用镜像时替换该包
        cd /tmp/rasp-2025-08-05 && java -jar RaspInstall.jar -heartbeat 90 -appid <your-rasp-cloud-appid> -appsecret <your-rasp-cloud-appsecret> -backendurl http://<agent-ip>:8086/ -install /srv/dotserver/tomcat-9.0.41
        cd /tmp && rm -rf rasp-2025-08-05 && rm -rf rasp-java.tar.gz
        exec /srv/entrypoint.sh
    volumes:
      # [Required]将应用容器内的工作目录通过cms-shared卷共享出来，便于filesystem、grep等mcp操作该目录
      - cms-shared:[your-app-workspace]
    ...

  # [Required]示例应用依赖的服务，用户可配置为自己的应用
  dotcms-db:
    image: postgres:13
    container_name: app-db
  ...

  falco:
    image: falcosecurity/falco:0.35.1
    container_name: falco
    privileged: true
    volumes:
      # [Required]自定义规则文件挂载，定义需要监控的容器和事件
      - ../third_party/falco/falco_rules.local.yaml:/etc/falco/falco_rules.local.yaml
      - ../third_party/falco/falco.yaml:/etc/falco/falco.yaml
      - /var/run/docker.sock:/host/var/run/docker.sock
      - /dev:/host/dev
      - /proc:/host/proc:ro
      - /boot:/host/boot:ro
      - /lib/modules:/host/lib/modules:ro
      - /usr:/host/usr:ro
      - /etc:/host/etc:ro
      - falco-logs-volume:/var/log/falco
    networks:
      - logging_net

  logstash:
    image: docker.elastic.co/logstash/logstash:8.19.5
    container_name: app-logstash
    ports:
      - "5044:5044"
    volumes:
      # [Required]挂载 Logstash 的管道配置文件 `logstash.conf` 和主配置文件 `logstash.yml`。
      # [Required]logstash.conf文件需替换`<agent-ip>`为agent侧kafka服务对应的实际ip地址，例如：172.19.9.192
      - ../third_party/logstash/logstash.conf:/usr/share/logstash/pipeline/logstash.conf:ro
      - ../third_party/logstash.yml:/usr/share/logstash/config/logstash.yml:ro
    ...

  filebeat:
    image: docker.elastic.co/beats/filebeat:8.19.5
    container_name: app-filebeat
    user: root
    volumes:
      # [Required]通过共享卷形式抓取三类遥测源数据，分别为：`cms-shared` 卷（OpenRASP 日志）、`falco-logs-volume` 卷（Falco 日志）、以及宿主机 `/var/log/suricata` 目录（Suricata 日志）,具体路径名称需与三类遥测源在docker-compose.yaml中定义的volumes一致。
      - ../third_party/filebeat/filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - cms-shared:/var/log/dotcms-shared:ro 
      - falco-logs-volume:/var/log/falco:ro
      - /var/log/suricata:/var/log/suricata:ro
    ...
```



**agent侧安装部署：**

agent侧配置说明:
[docker-compose-agent.yml](deploy/docker-compose-agent.yml)

### 5. 安装agent侧组件

启动方法：

```
cd deploy
docker-compose -f docker-compose-agent.yml up -d
```

docker-compose-agent.yml配置说明：

```yaml
services:
  # rasp-cloud的配置方法参考third_party/openrasp/README.md
  rasp-cloud:
    image: essaigroup/deepxdr-rasp-cloud:v0.3.0-alpha
    container_name: rasp-cloud
    ports:
      - "8086:8086"
    depends_on: 
      rasp-mongodb:
        condition: service_started
      rasp-elasticsearch:
        condition: service_healthy 
    volumes:
      - ../third_party/openrasp/rasp-cloud-docker/conf/app.conf:/app/conf/app.conf
    ...
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
      # [Required] 填写app-host-ip
      ELASTICSEARCH_HOST: <app-host-ip>
      ELASTICSEARCH_PORT: 9201
      # [Required] 填写app-host-ip
      ELASTICSEARCH_MCP_URL: http://<app-host-ip>:8000/mcp
      # [Required] 填写app-host-ip
      FILESYSTEM_MCP_URL: ws://<app-host-ip>:8001/message
      # [Required] 填写app-host-ip
      GREP_MCP_URL: ws://<app-host-ip>:8003/message
      # [Required] LLM供应商url及key 
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
      ...
  baseline-adjudication:
    image: essaigroup/deepxdr-baseline:v0.3.0-alpha
    container_name: baseline-adjudication
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      KAFKA_SOURCE_TOPIC: events
      KAFKA_AGENT_TOPIC: agent
      KAFKA_CONSUMER_GROUP_ID: anomaly-detector-group
      KAFKA_SECURITY_PROTOCOL: PLAINTEXT
      KAFKA_SASL_MECHANISM: PLAIN
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_DB: 1
      # [Required] 基线训练时长，单位：秒
      BASELINE_DURATION: 7200
      # [Optional] 基线模型文件名称
      BASELINE_FILE_PATH: baseline.json
      DEBUG: True
      REDIS_VALUE_TYPE: key_fields
      CONTINUOUS_BASELINE_ENABLED: false
      BASELINE_SAVE_INTERVAL: 180
      ENABLE_FILEPATH_NUM_FUZZY_MATCH: false
      ENABLE_THREAD_NAME_FUZZY_MATCH: true
      FALCO_SKIP_FILE_TYPES: .tmp,.tmp.jpg,.dat,.so,.log,.log.gz
    # [Optional]支持挂载已知基线模型，如未提供，则将收集BASELINE_DURATION秒内所有事件构建新的基线模型
    #volumes:
    #  - ./resources/baseline-adjudication/baseline202511031700.json:/app/baseline.json
    networks:
      - kafka-net
    depends_on:
      kafka:
        condition: service_healthy
    restart: unless-stopped

```

### 6. 启动仪表盘

部署于agent侧，docker compose yaml配置如下：

```yaml
  web-ui:
    image: essaigroup/deepxdr-web-ui:v0.3.0-alpha
    container_name: web-ui
    environment:
      API_BASE_URL: http://security-analysis:8000
    networks:
      - security-net
    ports:
      - "30003:30003"
    depends_on:
      - security-analysis
    ...
```

默认访问地址：

```text
http://<your-agent-host-ip>:30003
```

## FAST API 概览

Agent提供必要的API查询、设置接口，详见[web_ui-API说明章节](web_ui/README.md)

## MITRE ATT&CK 与 RAG

DeepXDR 内置 ATT&CK v18.1 数据，位于 `ai_agent/data/v18.1/`。MITRE RAG 路径用于从报告或 TTP 中抽取原子攻击行为，并通过 embedding 召回、rerank 重排和 LLM 判定映射到 ATT&CK technique。

默认缓存目录：

```text
ai_agent/.cache/mitre_attack/
```

缓存包含 technique catalog 和 embedding 矩阵。当前仓库可能包含预构建缓存以降低首次运行成本；生产环境可按需要删除并重新生成。新增或重新生成的大体积缓存不建议提交。

## 测试

```bash
python -m pytest tests -q
```

部分集成路径依赖 Kafka、ElasticSearch、PostgreSQL、Redis 和外部模型 API。

## 安全说明

- DeepXDR 是防御性安全监控、分析和调查工具。
- Long TTP、删除、反馈等操作接口必须通过 `BACKEND_API_KEY` 保护。
- 不要提交 `.env`、API Key、模型凭据、运行日志或生成缓存。
- 当前 Response 能力尚不完整，自动防御接口需要人工审核和灰度验证。
- 生成的 TTP 和调查报告应用于辅助分析，关键处置动作仍需安全分析师确认。

## 未来演进

| 方向 | 说明 |
| --- | --- |
| Response 能力补齐 | 补齐响应编排、审批、回滚、执行审计、策略验证和多控制面联动。 |
| AI智能体遥测源 | 适配 AI agent 专用遥测源，例如 [always-further/nono](https://github.com/always-further/nono)，用于观测智能体行为、工具调用、网络访问和执行轨迹。 |
| 遥测源生态扩展 | 在 Falco、OpenRASP、Suricata 之外扩展 EDR、WAF、云审计、Kubernetes audit、身份系统和 SaaS 日志。 |
| 基线裁决增强 | 改进行为特征提取、模糊匹配、持续学习、基线版本管理和异常复核机制。 |
| 长期威胁记忆 | 强化跨时间窗口、跨攻击者、跨资产的攻击链聚合和历史相似案例检索。 |
| 证据闭环 | 为每个 tactic/technique/procedure 建立更强的证据链、原始事件跳转、置信度解释和人工复核记录。 |
| 部署硬化 | 完善鉴权、多租户隔离、审计日志、密钥管理、资源限制、高可用和生产部署方案。 |
| 提供可读性更高的文档库| 构建文档库，提供更详细的组件部署流程说明 |

## License

本项目采用 MIT License，详见 [LICENSE](LICENSE)。
