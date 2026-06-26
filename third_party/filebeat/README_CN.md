
[English](README.md) | 中文

# Filebeat 部署文档


Filebeat 是一个轻量级的日志采集器，本项目使用它来采集 **OpenRASP**、**Falco** 和 **Suricata** 三类安全事件日志，统一转发到 Logstash 进行处理。

本项目采用的原生官方镜像为：`docker.elastic.co/beats/filebeat:8.19.5`



## 镜像启动

filebeat需要以docker形式部署在app侧服务器上。  

docker-compose中该镜像配置示例展示如下 ：
```yaml
  filebeat:
    image: docker.elastic.co/beats/filebeat:8.19.5
    container_name: app-filebeat
    user: root
    volumes:
      - ./filebeat/filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - cms-shared:/var/log/dotcms-shared:ro 
      - falco-logs-volume:/var/log/falco:ro
      - /var/log/suricata:/var/log/suricata:ro
    networks:
      - logging_net
    depends_on:
      - logstash
```

**配置说明**：

- `volumes`：挂载三类遥测源告警日志——`cms-shared` 卷（OpenRASP 日志）、`falco-logs-volume` 卷（Falco 日志）、以及宿主机 `/var/log/suricata` 目录（Suricata 日志）,具体路径名称需与三类遥测源在docker-compose.yaml中定义的字段一致。

镜像启动方式：
```bash
docker-compose -f docker-compose-app.yml up -d filebeat
```

## 三类数据源路径说明

filebeat.yml 中配置了 3 个日志输入源，分别对应不同的安全防护组件：

### 2.1 OpenRASP 日志

```yaml
paths:
  - /var/log/dotcms-shared/tomcat-9.0.41/rasp/logs/alarm/alarm.log
fields:
  log_source: openrasp
```

**路径含义**：该路径对应 dotcms 应用容器内 OpenRASP Agent 产生的告警日志文件。

**宿主机映射关系**：在 docker-compose-app.yml 中，通过 `cms-shared` Docker 卷将 dotcms 容器的共享目录挂载到 filebeat 容器的 `/var/log/dotcms-shared` 路径，从而 filebeat 可以读取到 OpenRASP 的 alarm 告警日志。

### 2.2 Falco 日志

```yaml
paths:
  - /var/log/falco/falco-alerts.json
fields:
  log_source: falco
```

**路径含义**：该路径对应 Falco 容器产生的 JSON 格式安全事件告警日志。

**宿主机映射关系**：在 docker-compose-app.yml 中，通过 `falco-logs-volume` Docker 卷将 Falco 容器的日志目录挂载到 filebeat 容器的 `/var/log/falco` 路径，从而 filebeat 可以读取到 Falco 的安全事件日志。

### 2.3 Suricata 日志

```yaml
paths:
  - /var/log/suricata/eve.json
fields:
  log_source: suricata
```

**路径含义**：该路径对应 Suricata 在宿主机上产生的 eve.json 网络流量事件日志文件。

**宿主机映射关系**：在 docker-compose-app.yml 中，直接将宿主机的 `/var/log/suricata` 目录挂载到 filebeat 容器的 `/var/log/suricata` 路径，从而 filebeat 可以读取到 Suricata 的网络安全事件日志。



**filebeat.yml**：filebeat 主配置文件，定义了日志输入源和输出目标

## 3. 数据流转流程

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