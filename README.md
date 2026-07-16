<p align="center">
  <img src="assets/images/deepxdr-brand-demo.gif" alt="DeepXDR 品牌演示" width="760">
</p>

<p align="center">
  <a href="README_EN.md">English</a> | 中文&nbsp;&nbsp;
  <a href="#项目状态"><img src="https://img.shields.io/badge/status-alpha-orange" alt="Status"></a>
  <a href="ai_agent/pyproject.toml"><img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

DeepXDR 是一个面向实时安全运营的智能威胁分析与调查系统。它接收来自主机、应用和网络遥测源的安全告警与行为事件，先通过基线裁决筛选高价值信号，再由 AI Agent 关联多源证据并生成基于 MITRE ATT&CK 的 TTP 分析。对于需要更长时间跨度研判的事件，系统可以从 Short TTP（跨域关联实时告警） 进一步触发 Long TTP（高级威胁攻击链） 调查，并支持分析师通过人机反馈补充调查方向。DeepXDR 也提供智能体安全分析模式，可接入 nono 包裹的 AI 智能体执行过程，对用户原始意图与最终代码变更进行一致性和风险分析，并支持人工接受变更或执行恢复。

## 项目状态

> **Alpha software - investigation-first mode.** DeepXDR 当前是早期研究与工程实现，仅适用于单用户、单应用的实验与验证场景，尚未支持多用户、多租户或多应用生产部署。系统重点在实时告警接入、异常行为发现、TTP 生成、高级威胁调查，以及面向 AI 智能体变更的意图一致性与风险分析。当前版本的 XDR Response 能力仍不完整：生产级响应编排、审批流、策略校验、跨控制面联动和完整执行审计尚未完成。智能体安全分析模式已经支持基于 nono 的人工确认恢复，但仍应按实验性能力使用。`ai_agent/defense/` 中的 MCP 防御接口属于实验性集成，不应被理解为已经具备完整自动处置能力。

## 系统职责与处理边界

DeepXDR 将待守护应用、遥测源、数据裁决、AI 驱动的威胁分析与调查、智能体安全分析和可视化交互拆分为不同职责边界：待守护应用是被观测对象，遥测源负责产生安全数据，后续链路负责筛选、分析与呈现结果。

| 对象 / 阶段 | 说明 | 对应目录 |
| --- | --- | --- |
| 应用  | 被 DeepXDR 守护和观测的业务系统。应用本身不承担威胁分析职责，但可以集成 OpenRASP/RASP 等遥测源，并按部署要求共享必要工作空间给 MCP Server。| `third_party/dotcms/` |
| 遥测源 | 负责从主机、应用和网络侧产生安全告警与行为事件，并将数据交给数据汇聚与基线裁决链路。| `third_party/falco/`</br>`third_party/openrasp/`</br>`third_party/suricata/` |
| 数据汇聚与基线裁决</br> | 接收 Falco、OpenRASP/RASP、Suricata 等遥测源产生的安全数据。明确告警会直接进入后续分析流程；原始行为数据会先用于构建正常行为基线，未命中基线的异常行为也会进入后续分析流程。| `baseline_adjudication/`  |
| AI 驱动的威胁分析与调查</br> | 对已经过筛选和裁决的高价值安全事件进行聚合分析，生成 Short TTP，并按需触发 Long TTP / 高级持续性威胁调查。| `ai_agent/`  |
| 智能体安全分析 | 接收 nono 包裹的 AI 智能体会话事件，围绕用户原始意图与最终增量变更的一致性进行风险分析，并在 Web UI 中支持人工确认、接受变更和韧性恢复。| `scripts/nono`</br>`ai_agent/agent_guard/` |
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
| 智能体安全分析模式 | 对 AI 智能体执行产生的增量变更进行意图一致性与风险分析，结合用户原始请求、最终变更和规则信号识别偏离请求、越权修改、敏感路径变更和高风险操作；该模式内置人工确认与韧性恢复能力，支持接受变更、执行恢复和删除告警。 |
| API 与仪表板 | FastAPI 提供查询、触发、反馈和统计接口；`web_ui/` 提供 TTP 仪表板。 |

## 支持的遥测源

当前版本仅支持以下输入类型：

| 遥测源 | 采集事件类型 | 
| --- | --- |
| [Falco](third_party/falco/) | 原生Falco告警（falco_alert类型）；</br>定制化修改Falco，支持全量open_write和execve事件收集（falco_raw类型）。</br>falco_raw类型事件用于构建行为基线 | 
| [OpenRASP](third_party/openrasp/) | 原生OpenRASP告警（openrasp_alert）；</br> 定制化修改OpenRASP，除原生OpenRASP告警外，还会采集sql，readfile，fileUpload，command事件。 </br> 除原生OpenRASP告警以外的事件用于构建行为基线|
| [Suricata](https://github.com/OISF/suricata) | 原生Suricata告警（suricata_alert类型），不参与基线裁决。 |
| [nono](https://github.com/nolabs-ai/nono) | AI 智能体会话事件、用户原始请求和 diff 引用，用于智能体安全分析模式。该输入源可独立使用，不需要同时部署 Falco、OpenRASP、Suricata、dotCMS 等传统网络安全分析组件。 |

非上述类型的数据当前不会进入传统网络安全分析链路。智能体安全分析模式使用独立的 nono 会话事件和 diff 引用，可单独运行，不依赖 Falco、OpenRASP 或 Suricata。后续计划扩展更多主机、网络、应用和云审计遥测源。

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
5. 检测阶段中，未命中基线的原始行为事件被判定为异常并推送到 `Kafka agent`。
6. `ai_agent` 从 `Kafka agent` 消费高价值安全事件。
7. `DynamicEventWindowManager` 将时间上接近的事件聚合为动态窗口。
8. `ShortTTPGenerator` 对关闭窗口并发分析，生成 Short TTP。
9. Short TTP 写入 ElasticSearch。
10. 用户可基于 Short TTP 触发 Long TTP 调查，必要时通过人机反馈补充调查方向。

智能体安全分析模式使用独立链路：

```mermaid
flowchart LR
    Shell["用户 Shell / AI 智能体"] --> Shim["scripts/nono PATH shim"]
    Shim --> RealNono["真实 nono"]
    RealNono --> Diff["nono rollback diff"]
    Shim --> ObjectStore["MinIO / S3: diff object"]
    Shim --> Events["Kafka topic: events"]
    Events --> BaselineAgent["baseline_adjudication"]
    BaselineAgent --> SessionTopic["Kafka topic: agent.session.finished"]
    SessionTopic --> Guard["AgentGuard consumer"]
    Guard --> Risk["变更风险分析"]
    Risk --> PGAgent["PostgreSQL agent sessions"]
    PGAgent --> APIAgent["FastAPI"]
    APIAgent --> AgentUI["Web UI 智能体安全分析模式"]
    AgentUI --> Accept["接受变更"]
    AgentUI --> Rollback["执行回退"]
    Rollback --> Restore["nono rollback restore"]
```

智能体链路处理流程：
1. 将本仓库 `scripts/` 放到 `PATH` 前面后，用户仍然执行 `nono` 命令，但实际先进入 DeepXDR 的 PATH shim。
2. shim 调用真实 nono，并在命令结束后提取 nono rollback session 的 diff。
3. diff 写入 MinIO/S3，事件中只携带 diff URI、原始请求、run id、nono session id 等元数据。
4. `baseline_adjudication` 将智能体会话事件路由到 Kafka `agent.session.finished`。
5. AgentGuard 消费会话事件，按 diff 大小选择全量 diff、单文件摘要或裁剪摘要策略，并生成中文变更风险分析。
6. Web UI 在“智能体安全分析模式”中展示告警，用户可接受变更、执行回退或删除告警。

## 快速开始

DeepXDR 按部署位置划分为 app 侧和 agent 侧，两侧可以部署在同一网络下的不同主机上。

app 侧部署在待守护应用所在主机，包含待守护应用、遥测源，以及 filebeat、logstash 等数据汇聚组件。部分遥测源需要与应用集成，例如 OpenRASP/RASP 需要安装到待守护应用中。

agent 侧部署 DeepXDR 的核心分析与交互组件，包括 AI 驱动的威胁分析与调查服务、API 服务和 `web_ui` 仪表盘。

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
        cd /tmp/rasp-2025-08-05 && java -jar RaspInstall.jar -heartbeat 90 -appid <your-rasp-cloud-appid> -appsecret <your-rasp-cloud-appsecret> -backendurl http://<agent-host-ip>:8086/ -install /srv/dotserver/tomcat-9.0.41
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
      # [Required]logstash.conf文件需替换`<agent-host-ip>`为agent侧kafka服务对应的实际ip地址，例如：172.19.9.192
      - ../third_party/logstash/logstash.conf:/usr/share/logstash/pipeline/logstash.conf:ro
      - ../third_party/logstash/logstash.yml:/usr/share/logstash/config/logstash.yml:ro
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

### 5. 安装agent侧组件

[docker-compose-agent.yml](deploy/docker-compose-agent.yml)

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
  ai-agent:
    image: essaigroup/deepxdr-analysis:v0.3.0-alpha
    container_name: ai-agent
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
      API_BASE_URL: http://ai-agent:8000
      # [Required] 与上文的ai-agent配置相同，Web UI 调用后端 API 时会使用该值。
      BACKEND_API_KEY: <your-random-token>
    networks:
      - security-net
    ports:
      - "30003:30003"
    depends_on:
      - ai-agent
    ...
```

默认访问地址：

```text
http://<agent-host-ip>:30003
```

### 7. 启用智能体安全分析模式（按需）

智能体安全分析模式用于审查 AI 智能体通过 nono 执行后产生的最终代码变更，重点判断用户原始意图与最终增量变更是否一致，并识别偏离请求、越权修改和高风险操作。该模式不依赖 dotCMS、Falco、OpenRASP 或 Suricata；本地完整运行环境会启动 Kafka、PostgreSQL、Redis、MinIO、baseline-adjudication、ai-agent 和 web-ui。

智能体安全分析模式采用简化的部署架构：

<p align="center">
  <img src="assets/images/agent-security-dnalysis-mode-deploy.png" alt="智能体安全分析模式部署图">
</p>


#### 7.1 前置条件

- 已安装 python, Docker 和 docker-compose。
- 已安装真实 [nono](https://github.com/nolabs-ai/nono)，并可通过 `DEEPXDR_REAL_NONO` 指定其路径。
- 如需运行真实智能体样例，需安装 nono 支持的智能体，例如 opencode。
- 准备 OpenAI-compatible LLM 配置，用于变更风险分析和真实智能体运行。

```bash
export OPENAI_MODEL=deepseek-v3-2-251201
export OPENAI_API_KEY=<your-llm-api-key>
export OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
export DEEPXDR_REAL_NONO="<your-nono-path>"
```

回退 worker 还需要访问宿主机上的实际工作区和 nono rollback 状态。请为两类数据选择已存在的绝对根目录：

```bash
sudo mkdir -p /srv/agent-workspaces /var/lib/deepxdr/nono-state
export AGENTGUARD_WORKSPACE_ROOT=/srv/agent-workspaces
export AGENTGUARD_NONO_STATE_ROOT=/var/lib/deepxdr/nono-state
```

`AGENTGUARD_WORKSPACE_ROOT` 是所有受管工作区的共同父目录；每次 nono 命令的 `--allow` 参数指向其中一个具体工作区。`AGENTGUARD_NONO_STATE_ROOT` 保存 nono session、快照和元数据，实际 `DEEPXDR_NONO_STATE_HOME` 必须位于其中。两个根目录必须是不同的已存在绝对目录。启动器会先规范化并验证路径，再让 Compose 以相同绝对路径将两个目录读写挂载到回退 worker，确保快照中的宿主机路径仍然有效。不要将这两个变量设为 `/`，应按最小权限原则选择专用目录。

不要将真实 API key 写入 README、compose 文件或提交记录。`deploy/docker-compose-agentguard.yml` 会从当前 shell 读取上述 LLM 环境变量。必须通过 `scripts/agentguard-compose` 启停本环境；它会在任何 Docker 操作前校验宿主机回退路径，直接执行底层 Compose 文件会因缺少校验标记而失败。

#### 7.2 启动本地完整环境

```bash
./scripts/agentguard-compose up -d
./scripts/agentguard-compose ps
```

默认端口：

| 组件 | 地址 |
| --- | --- |
| Web UI | `http://localhost:30003` |
| ai-agent API | `http://localhost:8000` |
| Kafka external listener | `localhost:29092` |
| PostgreSQL | `localhost:15432` |
| MinIO API | `http://localhost:9000` |
| MinIO Console | `http://localhost:9001` |

#### 7.3 让 shell 中的 nono 命令进入 DeepXDR shim

```bash
export PATH="$PWD/scripts:$PATH"
export DEEPXDR_REAL_NONO="<your-nono-path>"
```

之后用户可以照常在 shell 中执行 `nono`。DeepXDR shim 会调用真实 nono，并在会话结束后将 diff 写入 MinIO/S3，再向 Kafka 发布智能体会话事件。

#### 7.4 准备宿主机 nono shim 依赖

`scripts/nono` 在宿主机执行。该 shim 会将 diff 写入 MinIO/S3，并向 Kafka 发布智能体会话事件，因此宿主机 Python 环境需要安装：

```bash
python3 -m pip install boto3 aiokafka
```

#### 7.5 触发内置测试场景

```bash
export AGENTGUARD_SMOKE_WORKSPACE="$AGENTGUARD_WORKSPACE_ROOT/agentguard-smoke-workspace"
export DEEPXDR_NONO_STATE_HOME="$AGENTGUARD_NONO_STATE_ROOT/agentguard-smoke-nono-state"
mkdir -p  "$AGENTGUARD_SMOKE_WORKSPACE"  "$DEEPXDR_NONO_STATE_HOME"

./scripts/agentguard-compose down -v  
./scripts/agentguard-compose up -d

./scripts/agentguard-smoke-nono.sh small
./scripts/agentguard-smoke-nono.sh medium
./scripts/agentguard-smoke-nono.sh large
./scripts/agentguard-smoke-nono.sh agent
```

四个样例分别覆盖：

| 场景 | 说明 |
| --- | --- |
| `small` | 小 diff，使用完整文件 diff 进行一次性变更风险分析。 |
| `medium` | 多文件中等规模 diff，先生成单文件变更摘要，再汇总分析。 |
| `large` | 大 diff，裁剪高价值片段后生成单文件摘要，再汇总分析。 |
| `agent` | 通过真实 opencode 智能体在 nono 下运行，需要有效 `OPENAI_API_KEY`。 |

#### 7.6 在 Web UI 中处理智能体告警

打开：

```text
http://localhost:30003
```

在页面右上角切换到“智能体安全分析模式”。该模式下 Web UI 会展示待人工处理、已完成回退和总告警数，并列出每条智能体告警的风险等级、状态、摘要、变更风险分析、文件变更和 diff 预览。

可执行操作：

| 操作 | 效果 |
| --- | --- |
| 接受变更 | 将该告警标记为已接收变更，不执行代码回退。 |
| 执行回退 | 调用真实 `nono rollback restore` 回退对应 session。 |
| 删除告警 | 仅删除 DeepXDR 中的告警记录，不回滚代码变更，也不清理 MinIO/S3 对象。 |

#### 7.7 停止和清理

```bash
./scripts/agentguard-compose down
```

如需同时清理 PostgreSQL、Kafka、Redis 和 MinIO 中的本地测试数据：

```bash
./scripts/agentguard-compose down -v
```

#### 7.8 部署注意事项

- 智能体安全分析模式默认通过 MinIO/S3 传递大体积 diff。nono 侧将 diff 写入对象存储，AgentGuard 侧根据事件中的 URI 读取 diff。
- 使用 `AGENT_GUARD_MAX_DIFF_READ_BYTES` 限制单次读取的 diff 大小，避免超大变更影响后续变更风险分析。
- `BACKEND_API_KEY` 必须在 ai-agent 和 web-ui 中保持一致，生产环境应使用随机长字符串。
- `OPENAI_API_KEY`、对象存储凭据和数据库口令应通过环境变量、CI secret 或部署平台密钥管理注入。
- Web UI 的智能体安全分析模式适合人工确认高风险智能体变更；不要在缺少人工确认和审计的情况下自动执行回退。

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
| 智能体安全分析增强 | 在现有 nono 接入基础上，扩展更多 AI 智能体运行时、工具调用、网络访问和执行轨迹的审计能力。 |
| 遥测源生态扩展 | 在 Falco、OpenRASP、Suricata 之外扩展 EDR、WAF、云审计、Kubernetes audit、身份系统和 SaaS 日志。 |
| 基线裁决增强 | 改进行为特征提取、模糊匹配、持续学习、基线版本管理和异常复核机制。 |
| 长期威胁记忆 | 强化跨时间窗口、跨攻击者、跨资产的攻击链聚合和历史相似案例检索。 |
| 证据闭环 | 为每个 tactic/technique/procedure 建立更强的证据链、原始事件跳转、置信度解释和人工复核记录。 |
| 部署硬化 | 完善鉴权、多租户隔离、审计日志、密钥管理、资源限制、高可用和生产部署方案。 |
| 提供可读性更高的文档库| 构建文档库，提供更详细的组件部署流程说明 |

## License

本项目采用 MIT License，详见 [LICENSE](LICENSE)。
