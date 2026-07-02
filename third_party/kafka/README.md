# Kafka 部署文档

[English](README_EN.md) | 中文

Kafka 是本系统的核心消息总线服务，用于在防御侧与应用侧之间传输各类安全事件数据。Falco、OpenRASP、Suricata 等探针产生的安全事件统一推送至 Kafka，由基线裁决模块和 AI-Agent 模块消费处理。


本服务采用docker部署方式，采用的镜像版本: `essaigroup/deepxdr-kafka:v0.3.0`



## 镜像启动


本服务以docker形式安装在agent侧服务器上。  

docker-compose中该镜像配置示例展示如下 ：

```yaml
kafka:
  image: essaigroup/deepxdr-kafka:v0.3.0
  container_name: kafka
  security_opt:
    - seccomp:unconfined
    - apparmor:unconfined
  ports:
    - "29092:29092"
  networks:
    - kafka-net
  environment:
    KAFKA_ENABLE_KRAFT: "yes"
    KAFKA_CFG_PROCESS_ROLES: broker,controller
    KAFKA_CFG_NODE_ID: 1
    KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
    KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093,EXTERNAL://:29092
    KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092,EXTERNAL://<agent-ip>:29092
    KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,EXTERNAL:PLAINTEXT
    KAFKA_CFG_INTER_BROKER_LISTENER_NAME: PLAINTEXT
    KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
    KAFKA_CFG_SASL_ENABLED_MECHANISMS: PLAIN
    KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL: PLAIN
    KAFKA_CLIENT_USERS: [your-username]
    KAFKA_CLIENT_PASSWORDS: [your-password]
    ALLOW_PLAINTEXT_LISTENER: "yes"
    KAFKA_CFG_LOG_DIRS: /bitnami/kafka/data
    KAFKA_CREATE_TOPICS: "agent:5:1:compact"
  volumes:
    - kafka-data:/bitnami/kafka
  healthcheck:
    test: ["CMD-SHELL", "/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list > /dev/null && echo 'ok' || exit 1"]
    interval: 5s
    timeout: 4s
    retries: 30
  restart: unless-stopped
```

监听地址说明:

- **PLAINTEXT://kafka:9092**：容器内部通信地址，其他服务（如 Falco、基线裁决）通过此地址连接 Kafka
- **EXTERNAL://agent-ip:29092**：外部暴露地址，用于宿主机或其他服务器连接 Kafka

启动方式如下：
```bash
docker-compose -f docker-compose-defense.yaml up -d kafka
```

注意：
1. **Topic 创建**：`agent` Topic 用于传输经基线裁决处理后的安全事件数据，由 AI-Agent 模块消费。
2. **端口映射**：宿主机 29092 端口映射到容器 29092，外部服务通过 agent-ip:29092 连接 Kafka。

## 数据流转流程

遥测源在整个系统中的数据流转过程如下：

```
+---------------+     系统调用监控      +------------------+
|  应用容器     |  ------------------>  |   遥测源         |
|  (dotcms等)   |                      |                  |
+---------------+                      +------------------+
                                              |
                                              | 检测异常
                                              v
                                       +------------------+
                                       | falco-alerts.json|
                                       |  (JSON日志文件)   |
                                       +------------------+
                                              |
                                              | Filebeat 采集
                                              v
                                       +------------------+
                                       |    Filebeat      |
                                       +------------------+
                                              |
                                              | 转发
                                              v
                                       +------------------+
                                       |    Logstash      |
                                       +------------------+
                                              |
                              +---------------+---------------+
                              |                               |
                              v                               v
                       +------------------+          +------------------+
                       |      Kafka       |          | Elasticsearch    |
                       |  (安全事件队列)   |          |  (日志存储)      |
                       +------------------+          +------------------+
                              |                               |
                              | 消费                          | 查询
                              v                               v
                       +------------------+          +------------------+
                       |  Baseline裁决    |          |   AI-Agent       |
                       |  + AI-Agent分析  |          |   (长期威胁分析)  |
                       +------------------+          +------------------+
```

**流程说明：**

1. **Falco 捕获异常**：Falco 探针以特权模式运行在应用主机上，通过监控系统调用实时捕获应用容器的异常行为
2. **输出日志文件**：检测到的安全事件以 JSON 格式写入 `/var/log/falco/falco-alerts.json`
3. **Filebeat 采集**：Filebeat 通过共享卷读取 Falco 日志文件，将事件数据发送给 Logstash
4. **Logstash 分发**：Logstash 接收事件后，同时向两个方向推送：
   - **推送到 Kafka**：安全事件进入 Kafka 队列，供基线裁决模块和 AI-Agent 消费分析
   - **推送到 Elasticsearch**：原始日志数据存入 Elasticsearch，供 AI-Agent 查询和关联分析
