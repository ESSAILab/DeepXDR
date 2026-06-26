# 数据汇聚与基线裁决组件

[中文](README.md) | [English](README_EN.md)

## 项目概述
数据汇聚与基线裁决组件通过构建正常行为基线，实时监控并识别异常事件，保障系统安全。系统从Kafka集群消费事件数据，使用Redis存储正常行为基线，并将检测到的异常事件发送至指定Kafka Topic。

## 功能特点
- **基线构建**：从Kafka `event-source` 主题收集事件，构建正常行为基线
- **异常检测**：对比实时事件与基线，识别异常并发送至Kafka `agent` 主题
- **持久化存储**：基线数据自动保存至文件，支持程序重启后恢复
- **服务化部署**：支持Docker容器化部署- **调试模式**：详细日志输出，便于问题定位与系统优化

## 环境要求
- Python 3.11+
- Kafka 2.0+
- Redis 4.0+
- 系统依赖：`python3-dev`, `libsasl2-dev`, `libsasl2-modules`

## Docker镜像构建说明

### 1. docker镜像构建命令

```bash
docker build -t baseline-adjudication:latest .
```


## 实现原理
### 数据流程
1. **基线构建阶段**：
   - 从Kafka `event-source` 主题消费事件
   - 提取事件关键字段（排除时间戳等易变信息）
   - 计算事件哈希并存储到Redis
   - 构建完成后自动保存基线到JSON文件

2. **异常检测阶段**：
   - 实时消费事件并计算哈希
   - 对比Redis基线，未匹配则判定为异常
   - 异常事件发送至Kafka `agent` 主题

### 环境变量配置

除基础配置外，系统支持以下高级配置：

| 环境变量名 | 可选值 | 默认值 | 说明 |
|------------|--------|--------|------|
| REDIS_VALUE_TYPE | timestamp, key_fields | timestamp | 控制Redis中存储的value类型：timestamp存储事件时间戳，key_fields存储用于构建key的关键字段内容 |

### 关键字段提取
系统从SourceEvent中提取以下核心字段生成哈希：
```python
key_fields = [
    # 原始事件字段
    'attack_type', 'request_method', 'server_version', 'path', 'event_type',
    'attack_params',
    {'context': ['server', 'method', 'path']},
    # 新增syscall事件字段
    {'output_fields': ['proc.name', 'proc.cmdline', 'fd.name', 'evt.type']},
    'rule', 'source'
]
```

## 配置说明
| 参数名 | 描述 | 默认值 |
|--------|------|--------|
| KAFKA_BOOTSTRAP_SERVERS | Kafka集群地址 | localhost:9092 |
| KAFKA_SOURCE_TOPIC | 源事件主题 | event-source |
| KAFKA_AGENT_TOPIC | 异常事件输出主题 | agent |
| KAFKA_CONSUMER_GROUP_ID | Kafka消费者组ID | anomaly-detector-group |
| REDIS_HOST | Redis服务器地址 | localhost |
| REDIS_PORT | Redis端口 | 6379 |
| REDIS_DB | Redis数据库编号 | 0 |
| BASELINE_DURATION | 基线构建时长(秒) | 300 |
| BASELINE_FILE_PATH | 基线存储文件路径 | baseline.json |
| DEBUG | 调试模式开关 | True |


