# falco 部署说明

[English](README_EN.md) | 中文

Falco 是一款开源的云原生运行时安全工具，由 CNCF 孵化。它通过监控 Linux 系统调用和容器运行时行为，实时检测异常活动和安全威胁。在本系统中，Falco 部署在app侧服务器上，以内核级探针的方式监控应用容器的行为，将检测到的安全事件以 JSON 格式输出到日志文件，由filebeat采集，经logstash格式化后发送至 Kafka 进行后续分析。 

本系统中falco以docker形式部署，方便用户快速部署和使用，采用的falco docker版本为falcosecurity/falco:0.35.1  。


## 1. falco镜像启动

falco探针需要以docker形式安装在app侧服务器上。  官方文档参考https://v0-31.falco.org/zh/docs/installation/

docker-compose中该镜像配置示例展示如下 ：
```yaml
  falco:
    image: falcosecurity/falco:0.35.1
    container_name: falco
    privileged: true
    volumes:
      - ./falco/falco_rules.local.yaml:/etc/falco/falco_rules.local.yaml
      - ./falco/falco.yaml:/etc/falco/falco.yaml
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
```

### 配置说明

| 配置项 | 说明 |
|--------|------|
| `falco_rules.local.yaml` | 自定义规则文件挂载，定义需要监控的容器和事件 |
| `falco.yaml` | Falco 主配置文件挂载,无需修改 |

启动命令如下：  
```bash
docker-compose up -d falco

```
---  
注意：修改falco_rules.local.yaml配置文件，修改第2行items里面的内容，监控的应用容器名称，根据实际情况填写即可，如监控全量主机事件，则此处内容不填。

```bash
vi falco_rules.local.yaml
```

示例（修改后）：
```yaml
items: [app-dotcms]
```
  
日志输出到/var/log/falco/falco-alerts.json文件中，使用filebeat采集。  


---  

## 2. 数据流转流程

Falco 探针在整个系统中的数据流转过程如下：

```
+---------------+     系统调用监控      +------------------+
|  应用容器     |  ------------------>  |   Falco 探针     |
|  (dotcms等)   |                      |  (特权模式运行)   |
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


