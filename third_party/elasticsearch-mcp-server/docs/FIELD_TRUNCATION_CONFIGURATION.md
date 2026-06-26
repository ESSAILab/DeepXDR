# 字段长度截断配置文档

## 概述

EQL查询工具现在支持通过环境变量控制返回字段的最大长度和列表中字符串项目的数量，特别适用于处理`stack`、`plugin_message`等长文本字段，可以减少网络传输量并保护敏感信息。

## 新功能：字符串列表项目数限制

除了字符串长度截断外，系统现在支持对字符串列表（`list[str]`）进行项目数限制。当列表中的字符串数量超过指定数量时，系统将只保留前N个项目，并在列表末尾添加项目数截断指示符。

**示例：**
```json
// 原始数据
{
  "stack": [
    "line1: org.postgresql.jdbc.PgStatement.executeQuery",
    "line2: com.zaxxer.hikari.pool.ProxyStatement.executeQuery",
    "line3: com.dotmarketing.common.db.DotConnect.executeQuery",
    // ... 更多行
  ]
}

// 截断后（EQL_MAX_LIST_ITEMS=3）
{
  "stack": [
    "line1: org.postgresql.jdbc.PgStatement.executeQuery",
    "line2: com.zaxxer.hikari.pool.ProxyStatement.executeQuery",
    "line3: com.dotmarketing.common.db.DotConnect.executeQuery",
    "...50 more items truncated"
  ]
}
```

## 配置方法

### 环境变量设置

通过设置环境变量`EQL_MAX_FIELD_LENGTH`来控制字段截断的最大长度：

```bash
# 设置为500字符（例如处理较大的stack字段）
export EQL_MAX_FIELD_LENGTH=500

# 设置为200字符（更严格的长度控制）
export EQL_MAX_FIELD_LENGTH=200

# 设置为0来禁用截断功能（默认行为）
export EQL_MAX_FIELD_LENGTH=0

# 设置为1000字符（默认值）
export EQL_MAX_FIELD_LENGTH=1000
```

### 在不同操作系统中设置

**Linux/MacOS：**
```bash
# 临时设置（当前会话）
export EQL_MAX_FIELD_LENGTH=500

# 永久设置（添加到 ~/.bashrc 或 ~/.bash_profile）
echo 'export EQL_MAX_FIELD_LENGTH=500' >> ~/.bashrc
source ~/.bashrc
```

**Windows：**
```cmd
# 临时设置（当前会话）
set EQL_MAX_FIELD_LENGTH=500

# 永久设置
setx EQL_MAX_FIELD_LENGTH 500
```

**Docker容器中：**
**字符串列表项目数限制：**

通过设置环境变量`EQL_MAX_LIST_ITEMS`来控制字符串列表中保留的最大项目数：

```bash
# 设置为5个项目（默认）
export EQL_MAX_LIST_ITEMS=5

# 设置为10个项目
export EQL_MAX_LIST_ITEMS=10

# 设置为0来禁用列表项目数限制
export EQL_MAX_LIST_ITEMS=0
```

**在不同操作系统中设置：**

**Linux/MacOS：**
```bash
# 临时设置（当前会话）
export EQL_MAX_LIST_ITEMS=3

# 永久设置（添加到 ~/.bashrc 或 ~/.bash_profile）
echo 'export EQL_MAX_LIST_ITEMS=3' >> ~/.bashrc
source ~/.bashrc
```

**Windows：**
```cmd
# 临时设置（当前会话）
set EQL_MAX_LIST_ITEMS=3

# 永久设置
setx EQL_MAX_LIST_ITEMS 3
```

**Docker容器中：**
```dockerfile
ENV EQL_MAX_LIST_ITEMS=3
```

## 使用示例

### 1. 基本查询（自动截断）

```python
# 设置环境变量
import os
os.environ["EQL_MAX_FIELD_LENGTH"] = "500"

# 所有返回的字符串字段超过500字符将被截断
search_documents(
    index="openrasp-alerts-*",
    query='openrasp where attack_type == "sql"',
    event_category_field="type",
    size=3
)
```

### 2. 不同环境变量的效果对比

```python
import os

# 测试不同的截断长度
for max_length in [0, 100, 500]:
    os.environ["EQL_MAX_FIELD_LENGTH"] = str(max_length)

    print(f"\n=== 最大长度设置为 {max_length} ===")

    results = search_documents(
        index="openrasp-alerts-*",
        query='openrasp where true',
        event_category_field="type",
        size=1
    )

    # 检查stack字段长度
    if results and 'hits' in results:
        # 处理不同的响应结构格式
        if 'events' in results.get('hits', {}):
            for event in results['hits']['events']:
                if '_source' in event and 'attack_params' in event['_source']:
                    stack = event['_source']['attack_params'].get('stack', [])
                    stack_str = '\n'.join(stack) if isinstance(stack, list) else str(stack)
                    print(f"stack字段长度: {len(stack_str)} 字符")
                    if max_length > 0 and len(stack_str) > max_length:
                        print(f"stack字段被截断为: {stack_str[:50]}...")
```

### 3. 与服务端字段选择结合使用

```python
# 先用fields选择需要的字段，再用长度截断
search_documents(
    index="openrasp-alerts-*",
    query='openrasp where attack_type == "sql"',
    event_category_field="type",
    fields=[
        {"field": "target"},
        {"field": "attack_type"},
        {"field": "attack_params.query"},
        {"field": "attack_params.server"},
        {"field": "plugin_message"}
        # 注意：stack字段被排除，减少了数据传输
    ],
    size=5
)
# 结果中plugin_message和query字段会被截断到指定长度
```

### 3. 字符串列表项目截断示例

```python
import os

# 设置环境变量
os.environ["EQL_MAX_LIST_ITEMS"] = "5"

# 查询包含长stack信息的数据（只保留前5个栈帧）
results = search_documents(
    index="openrasp-alerts-*",
    query='openrasp where attack_type == "sql"',
    event_category_field="type",
    size=1
)

# 查看stack列表截断情况
if results and 'hits' in results:
    if 'events' in results.get('hits', {}):
        for event in results['hits']['events']:
            if '_source' in event and 'attack_params' in event['_source']:
                stack = event['_source']['attack_params'].get('stack', [])
                print(f"stack列表截断后: {len(stack)} 个项目")
                if len(stack) > 0 and 'truncated' in stack[-1]:
                    print(f"截断指示: {stack[-1]}")
```

### 4. 组合使用字符串长度和列表项目数限制

```python
import os

# 同时设置字符串长度和列表项目数限制
os.environ["EQL_MAX_FIELD_LENGTH"] = "200"    # 单字符串最大200字符
os.environ["EQL_MAX_LIST_ITEMS"] = "3"        # 字符串列表最多3个项目

# 执行查询
results = search_documents(
    index="falco-alerts-*",
    query='falco where priority == "Error"',
    size=5
)
# 结果中：
# - 单个字符串字段超过200字符会被截断，添加"..."
# - 字符串列表超过3个项目会被截断，保留前3个，末尾添加项目数截断信息
```

## 字段截断行为

### 截断规则

1. **只截断字符串类型**
   - 数字、布尔值、null不受影响
   - 列表中的字符串也会被截断

2. **截断指示符**
   - 在截断处添加 "..." 指示符
   - 保持JSON格式兼容性

3. **嵌套处理**
   - 递归处理所有嵌套层级
   - 字典、列表层层截断

### 截断示例

```json
{
  "attack_params": {
    "stack": [
      "org.postgresql.jdbc.PgStatement.executeQuery",
      "com.zaxxer.hikari.pool.ProxyStatement.executeQuery",
      "com.dotmarketing.common.db.DotConnect.executeQuery",
      "...约200行被截断...",
      "java.base/java.lang.Thread.run..."
    ],
    "query": "select cr1.id as childId, cr1.role_name as roleName, cr2.id as parentId  from cms_role cr1, cms_role cr2 where cr1.parent in ('...') and cr1.parent = cr2.id..."
  },
  "plugin_message": "SQL请求监控 - 执行SQL: select cr1.id as childId, cr1.role_name as roleName, cr2.id as parentId  from cms_role cr1, cms_role cr2 where cr1.parent in ('...'"
}
```

## 性能考量

### 优势

1. **减少网络传输**
   - 截断长字段减少数据传输量
   - 特别适用于大型stack trace

2. **保护敏感信息**
   - 自动截断可能包含敏感信息的长字段

3. **提高响应速度**
   - 减少序列化/反序列化时间
   - 降低内存使用

### 注意事项

1. **截断不可逆**
   - 被截断的数据无法恢复原始内容
   - 需要完整数据时，请设置EQL_MAX_FIELD_LENGTH=0

2. **处理开销**
   - 会在结果返回前执行截断处理
   - 对于极大量数据可能有轻微性能影响

3. **只对返回数据生效**
   - 不影响Elasticsearch中的原始数据
   - 只在查询结果被截断

## 高级用法

### 1. 动态调整长度限制

```python
# 根据实际需求动态调整
if guessing_senstive_data:
    os.environ["EQL_MAX_FIELD_LENGTH"] = "100"  # 更严格
else:
    os.environ["EQL_MAX_FIELD_LENGTH"] = "2000"  # 更宽松

# 执行查询
results = search_documents(...)
```

### 2. 日志监控截断事件

```python
# 监控截断情况
os.environ["EQL_MAX_FIELD_LENGTH"] = "500"

results = search_documents(...)
# 查看截断相关的TRACE日志输出
```

### 3. 禁用特定字段截断

```python
# 通过fields参数排除长字段，与截断功能配合使用
search_documents(
    index="openrasp-alerts-*",
    query='openrasp where true',
    event_category_field="type",
    # 排除长字段，避免截断
    filter_path=[
        "hits.hits._source.target",
        "hits.hits._source.attack_type",
        # 注意：不包含攻击参数等长字段
    ],
    size=10
)
```

## 故障排除

### 1. 截断不生效

检查环境变量是否正确设置：
```python
import os
print(f"EQL_MAX_FIELD_LENGTH = {os.getenv('EQL_MAX_FIELD_LENGTH', '未设置')}")
```

### 2. 性能问题

如果截断处理耗时过长：
- 增大EQL_MAX_FIELD_LENGTH值
- 或使用fields参数提前过滤字段
- 或使用filter_path只返回必要字段

### 3. 特殊字符处理

某些包含特殊字符的字段可能被提前过滤，可以尝试：
- 调整filter_path路径
- 或使用fields参数精确控制返回字段

## 版本兼容性

- Elasticsearch 7.9+：完全支持
- 截断功能不改变底层API调用
- 与现有代码完全兼容（向后兼容）

## 总结

通过环境变量`EQL_MAX_FIELD_LENGTH`可以灵活控制返回数据的文本字段长度，特别适用于处理长stack trace、复杂查询语句等大文本字段。结合filter_path和fields参数使用，可以进一步优化数据传输和响应性能。"

## 环境变量参考

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| EQL_MAX_FIELD_LENGTH | 1000 | 字符串字段最大长度（字符数）|
| EQL_ENABLE_TRUNCATION | 1 | 是否启用截断（1启用，0禁用）|
| EQL_TRUNCATION_SUFFIX | "..." | 截断后添加的后缀|
| EQL_MAX_LIST_ITEMS | 5 | 字符串列表最大保留项目数|"}，"，true,"略""}，"","true""}，"","true",""}，"","true",""}，"","true",""}，"","true",""}，"","true",""}，"","true",""]"，,""}，"]"，,""}，"]"，,""}，"]"，,""}，"]"，,""}，"]"，,""}，"]","true"}，true "}，"",true,"【"}，"","true"{}，"","","true"{}，"","","true"{}，"","","true"{}，"","","true"{}，"","","true"{}，"",""，true,"【",""}，"]"，,""}，"]"，,""}，"]"，,""}，"]"，,""}，，""]"，,""}，"]"，,""}，"]"，,""}，"]"，,""}，"]"，,""}，"]""}，","true"}，""}，"","true"{}，"","","","","true"{}，"","","","","true"{}，"","","","","true"{}，""}，",
","true"{}，"","","","true"{}，"",,”","true"{}，""，","","true"{}，""，","","true"{}，,""","","true"{}，,""","","true"{}，,""","",true,"一篇"}，"]",""} ，",} ，","} ，","} ，","} ，","} ，","} ，","} ，","} ，","} ，",""}",,""}，"",,""}，"",,""}，"",,""}，"",,""}，"",,""}，"",,""}，"",,""}，"",,""}，"",,""}，"]",""}，"
true"}，"]"",""}，"","true"} ，"]","","true"} ，"]":"","true"} ，"":","","true"} ，"":"","","true"} ，"",:","","true"} ，""::","","true"} ，"","::","","true"{”,,","”":{”，“”",:","”，”，”’,:","”,":","”,":"<tool_call>lit function(file_path):0{"content":"#!/usr/bin/env python3\n\"\"\"\n演示字段长度截断功能的使用\n\"\"\"\n\nimport os\n\ndef demonstrate_field_truncation():\n    \"\"\"演示字段截断功能\"\"\"\n\n    print(\"=== 字段长度截断功能演示 ===\\n\")\n\n    # 设置环境变量\n    print(\"1. 通过环境变量控制字段长度截断:\")\n    print(\"   export EQL_MAX_FIELD_LENGTH=100    # 设置为100字符\")\n    print(\"   export EQL_MAX_FIELD_LENGTH=0      # 禁用截断\")\n    print(\"   export EQL_MAX_FIELD_LENGTH=50     # 设置为50字符（更短）\\n\")\n\n    # 默认行为示例\n    os.environ[\"EQL_MAX_FIELD_LENGTH\"] = \"100\"\n    max_length = int(os.getenv(\"EQL_MAX_FIELD_LENGTH\", \"1000\"))\n\n    print(f\"当前设置: EQL_MAX_FIELD_LENGTH={max_length}\\n\")\n\n    # 示例1：OpenRASP stack字段截断\n    print(\"2. OpenRASP stack字段截断示例:\")\n    original_stack = [\n        \"org.postgresql.jdbc.PgStatement.executeQuery\",\n        \"com.zaxxer.hikari.pool.ProxyStatement.executeQuery\",\n        \"com.dotmarketing.common.db.DotConnect.executeQuery\",\n        \"com.dotmarketing.business.RoleAPIImpl.loadBackEndUserRole\",\n        # ... 省略更多栈帧\n    ]\n\n    stack_str = '\\n'.join(original_stack) if isinstance(original_stack, list) else str(original_stack)\n    print(f\"   原始stack长度: {len(stack_str)}字符\")\n\n    if len(stack_str) \u003e max_length:\n        truncated = stack_str[:max_length] + \"...\"\n        print(f\"   截断后长度: {len(truncated)}字符\")\n        print(f\"   截断结果: {truncated[:100]}...\")\n\n    # 示例2：Suricata长字段截断\n    print(\"\\n3. Suricata长签名截断示例:\")\n    long_signature = \"SURICATA HTTP unable to match response to request in flow with app_proto http and transaction with method POST and status_code 200 and response_body_len 5678\" * 10\n\n    if len(long_signature) \u003e max_length:\n        truncated = long_signature[:max_length] + \"...\"\n        print(f\"   长签名字段被截断\")\n        print(f\"   截断后: {truncated[:150]}...\")\n\ndef show_eql_query_examples():\n    \"\"\"展示如何在EQL查询中使用字段截断\"\"\"\n\n    print(\"\\n=== EQL查询中使用示例 ===\\n\")\n\n    print(\"设置环境变量并执行查询:\")\n    print(\"\"\"\n# 设置stack字段截断为500字符\nexport EQL_MAX_FIELD_LENGTH=500\n\n# 查询OpenRASP SQL攻击（stack字段会被自动截断）\nsearch_documents(\n    index=\"openrasp-alerts-*\",\n    query='openrasp where attack_type == \"sql\"',\n    event_category_field=\"type\",\n    size=3\n)\n\n# 查询Suricata告警（长签名字段会被截断）\nsearch_documents(\n    index=\"suricata-alerts-*\",\n    query='suricata where alert.severity \u003c= 3',\n    event_category_field=\"type\",\n    size=3\n)\n\"\"\")"} <tool_call>西<tool_call>能 via python<tool_call>{"content":"#!/usr/bin/env python3\n\"\"\"\n演示字段长度截断功能的使用\n\"\"\"\n\nimport os\n\ndef demonstrate_field_truncation():\n    \"\"\"演示字段截断功能\"\"\"\n\n    print(\"=== 字段长度截断功能演示 ===\\n\")\n\n    # 设置环境变量\n    print(\"1. 通过环境变量控制字段长度截断:\")\n    print(\"   export EQL_MAX_FIELD_LENGTH=100    # 设置为100字符\")\n    print(\"   export EQL_MAX_FIELD_LENGTH=0      # 禁用截断\")\n    print(\"   export EQL_MAX_FIELD_LENGTH=50     # 设置为50字符（更短）\\n\")\n\n    # 默认行为示例\n    os.environ[\"EQL_MAX_FIELD_LENGTH\"] = \"100\"\n    max_length = int(os.getenv(\"EQL_MAX_FIELD_LENGTH\", \"1000\"))\n\n    print(f\"当前设置: EQL_MAX_FIELD_LENGTH={max_length}\\n\")\n\n    # 示例1：OpenRASP stack字段截断\n    print(\"2. OpenRASP stack字段截断示例:\")\n    original_stack = [\n        \"org.postgresql.jdbc.PgStatement.executeQuery\",\n        \"com.zaxxer.hikari.pool.ProxyStatement.executeQuery\",\n        \"com.dotmarketing.common.db.DotConnect.executeQuery\",\n        \"com.dotmarketing.business.RoleAPIImpl.loadBackEndUserRole\",\n        # ... 省略更多栈帧\n    ]\n\n    stack_str = '\\n'.join(original_stack) if isinstance(original_stack, list) else str(original_stack)\n    print(f\"   原始stack长度: {len(stack_str)}字符\")\n\n    if len(stack_str) \u003e max_length:\n        truncated = stack_str[:max_length] + \"...\"\n        print(f\"   截断后长度: {len(truncated)}字符\")\n        print(f\"   截断结果: {truncated[:100]}...\")\n\ndef show_eql_query_examples():
    \"\"\"展示如何在EQL查询中使用字段截断\"\"\"\n\n    print(\"\\n=== EQL查询中使用示例 ===\\n\")\n\n    print(\"设置环境变量并执行查询:\")\n    print(\"\"\"\n# 设置stack字段截断为500字符\nexport EQL_MAX_FIELD_LENGTH=500\n\n# 查询OpenRASP SQL攻击（stack字段会被自动截断）\nsearch_documents(\n    index=\"openrasp-alerts-*\",\n    query='openrasp where attack_type == \"sql\"',\n    event_category_field=\"type\",\n    size=3\n)\n\n# 查询Suricata告警（长签名字段会被截断）\nsearch_documents(\n    index=\"suricata-alerts-*\",\n    query='suricata where alert.severity \u003c= 3',\n    event_category_field=\"type\",\n    size=3\n)\n\"\"\")\n\ndef show_customization_options():\n    \"\"\"显示定制化选项\"\"\"\n\n    print(\"\\n=== 定制化选项 ===\\n\")\n\n    print(\"1. 不同字段不同的截断长度:\")\n    print(\"   当前实现对所有字符串字段统一截断\")\n    print(\"   未来可以通过额外参数实现字段特定长度控制\\n\")\n\n    print(\"2. 截断指示符:\")\n    print(\"   当前在截断后添加 '...' 指示符\")\n    print(\"   这对于JSON兼容性很好\\n\")\n\n    print(\"3. 性能考量:\")\n    print(\"   - 只在返回前进行截断\")\n    print(\"   - 不影响查询性能\")\n    print(\"   - 减少网络传输量\\n\")\n\nif __name__ == \"__main__\":\n    demonstrate_field_truncation()\n    show_eql_query_examples()\n    show_customization_options()"} ,0} f"开启了么？开启了呢！"} 0 { "quote":"用户","isComplete":false,<tool_call>id":"test_field_truncation.py:0","error":"Partial content provided"}}