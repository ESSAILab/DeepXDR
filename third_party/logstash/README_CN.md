
[English](README.md) | 中文

# logstash 部署文档

本服务采用docker形式部署，采用的logstash镜像为docker.elastic.co/logstash/logstash:8.19.5

## logstash镜像启动

logstash需要以docker形式安装在app侧服务器上。  

docker-compose中该镜像配置示例展示如下 ：

```
  logstash:
    image: docker.elastic.co/logstash/logstash:8.19.5
    container_name: app-logstash
    user: root
    ports:
      - "5044:5044"
    volumes:
      - ./logstash/logstash.conf:/usr/share/logstash/pipeline/logstash.conf:ro
      - ./logstash/logstash.yml:/usr/share/logstash/config/logstash.yml:ro
    networks:
      - logging_net
    depends_on:
      - es-log-storage
```

**配置说明**：

- `volumes`：挂载 Logstash 的管道配置文件 `logstash.conf` 和主配置文件 `logstash.yml`，均以只读方式挂载。


启动logstash镜像服务

```bash
docker-compose -f docker-compose-app.yml up -d logstash

```



修改logstash.conf配置文件，需要配置其中kafka的地址，ElasticSearch的地址以内部地址指定，无需修改。

```yaml
vi logstash.conf
```

修改第98行kafka里面的`<agent-ip>`内容，该ip替换为部署了kafka服务的agent侧服务器对应的实际ip地址，例如：172.19.9.192

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


