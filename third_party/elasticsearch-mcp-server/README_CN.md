# Elasticsearch MCP 二次开发说明



## 原始项目

本项目基于开源项目  [cr7258/elasticsearch-mcp-server](https://github.com/cr7258/elasticsearch-mcp-server/tree/main) 进行二次开发。 

原始项目的完整功能说明请参阅 [README_origin.md](README_origin.md)。 

原始项目实现了基于模型上下文协议（MCP）的 Elasticsearch/OpenSearch 交互服务器，提供文档搜索、索引分析、集群管理等功能。本项目在原始代码基础上，针对 EQL 查询场景、AI 模型适配及容器化部署进行了扩展与增强。

---

## 镜像启动

该服务部署在app侧所在服务器上,为ai-agent威胁分析智能体提供ES查询工具。

### 1. Docker Compose 配置示例

docker-compose中该镜像配置示例展示如下 ：

```yaml
elasticsearch-mcp-server:
  image: essaigroup/deepxdr-es-mcp-server:v0.3.0-alpha
  container_name: app-elasticsearch-mcp-server
  environment:
    - ELASTICSEARCH_HOSTS=http://es-log-ip:port
    - VERIFY_CERTS=false
    - DISABLE_HIGH_RISK_OPERATIONS=true
    - EQL_MAX_FIELD_LENGTH=1000
    - EQL_MAX_LIST_ITEMS=5
  user: root
  ports:
    - "8000:8000"
  networks:
    - logging_net
  restart: always
  deploy:
    resources:
      limits:
        memory: 512M
      reservations:
        memory: 128M
```

### 2. 环境变量参数说明

| 环境变量 | 必填 | 默认值 | 说明 |
|----------|------|--------|------|
| `ELASTICSEARCH_HOSTS` | 是 | — |  app侧Elasticsearch数据库地址 。其中es-log-ip:port需要用实际地址替换|
| `VERIFY_CERTS` | 否 | `false` | 是否验证 SSL 证书。内网环境建议设置为 `false` |
| `DISABLE_HIGH_RISK_OPERATIONS` | 否 | `true` | 是否禁用高风险写操作。生产环境建议保持 `true` |
| `EQL_MAX_FIELD_LENGTH` | 否 | `1000` | 限制查询返回结果中单个字符串的最大长度，超出部分将被截断并以 `"..."` 后缀标识。设置为 `0` 表示禁用长度截断 |
| `EQL_MAX_LIST_ITEMS` | 否 | `5` | 限制查询返回结果中字符串列表保留的最大长度，超出部分将被截断。设置为 `0` 表示禁用列表截断，超出部分将被截断。 |


### 3. 启动与验证

启动服务：

```bash
docker-compose up -d elasticsearch-mcp-server
```

查看日志：

```bash
docker logs -f app-elasticsearch-mcp-server
```

验证服务可用性：

```bash
curl http://localhost:8000/mcp/
```

---


## 镜像构建


```bash
docker build -f Dockerfile -t essaigroup/deepxdr-es-mcp-server:v0.3.0-alpha .
```
若docker-hub中已有该镜像，则可跳过此步骤。

---

## 二次开发功能说明

### 1. EQL 查询模式重构

对 `search_documents` 工具进行了重构，将原始通用的 `body` 传参方式升级为面向 **EQL（Event Query Language）** 的专用查询模式。客户端新增 EQL 搜索参数构建逻辑，直接调用 Elasticsearch 的 `eql.search` API，适配 Elasticsearch 7.9+ 的 EQL 查询能力。

**核心变更：**
- 底层调用由 `client.search()` 切换为 `client.eql.search()`
- 默认集成 `@timestamp` 时间戳字段处理
- 支持通过 `event_category_field` 参数自定义事件类别映射字段

### 2. EQL 全量参数支持

扩展了 `search_documents` 工具的参数列表，新增支持 EQL API 的完整参数集

### 3. AI 模型提示词优化

在 `search_documents` 工具的文档字符串（docstring）中注入了面向 AI 模型的结构化使用指导，以降低大语言模型调用时的参数误用率。提示词内容涵盖：

- **`fields` 参数格式规范**：明确必须使用 `dict` 列表格式，禁止误用 DSL 语法（如 `["*", "-field"]`）
- **嵌套字段访问方式**：如 `{"field": "attack_params.query"}`
- **事件类别映射说明**：针对云安全探针数据，指出应配置 `event_category_field="type"`
- **`filter_path` 过滤技巧**：支持通过负号前缀排除路径，如 `filter_path="-hits.events"`
- **EQL 查询语法参考**：涵盖基础查询、序列查询（`sequence`）、跨度约束（`maxspan`）、关联键绑定（`by`）、截止条件（`until`）、缺失事件查询（`!`）、无序样本匹配（`sample`）、管道操作（`|`）等 15 项核心语法规则

### 4. 字段截断通用处理

新增 `src/utils/field_truncate.py` 模块，对 Elasticsearch 返回结果中的字符串字段进行递归截断处理，防止超长字段导致 AI 模型上下文窗口（Context Window）溢出。

**功能特性：**
- 递归遍历嵌套字典、列表及字符串字段
- 同时适配 EQL 响应格式（`hits.events._source`）和 DSL 响应格式（`hits.hits._source`）
- 字符串列表支持按项目数截断，在末尾追加截断指示符
- 截断操作日志输出，便于调试追踪

**环境变量配置：**

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `EQL_MAX_FIELD_LENGTH` | `1000` | 限制查询返回结果中单个字符串的最大长度，超出部分将被截断并以 `"..."` 后缀标识。设置为 `0` 表示禁用长度截断 |
| `EQL_MAX_LIST_ITEMS` | `5` | 限制查询返回结果中字符串列表保留的最大长度，超出部分将被截断。设置为 `0` 表示禁用列表截断。 |
| `EQL_TRUNCATION_SUFFIX` | `"..."` | 截断后附加的后缀字符串 |

详细配置说明请参阅 [docs/FIELD_TRUNCATION_CONFIGURATION.md](docs/FIELD_TRUNCATION_CONFIGURATION.md)。

### 5. Bug 修复

- **`filter_path` 参数类型修复**：修复了 `filter_path` 传入 `str` 类型时触发的类型兼容性问题
- **提示词位置修正**：修复了 `search_documents` docstring 中部分提示词语段位置错误的问题

---

## 许可证

本项目继承原始项目的 [Apache License 2.0](LICENSE) 开源协议。
