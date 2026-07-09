# Elasticsearch 部署文档

[English](README_EN.md) | 中文

本服务中使用了三个不同版本的 Elasticsearch，分别用于不同的业务场景。

---

## Elasticsearch 版本 1 镜像启动


本服务为 dotcms 应用专用的搜索引擎。

本服务以docker形式安装在app侧主机服务器上。  原生官方 Docker 镜像: `docker.elastic.co/elasticsearch/elasticsearch:7.9.1`

docker-compose中该镜像配置示例展示如下 ：

```yaml
elasticsearch:
  image: docker.elastic.co/elasticsearch/elasticsearch:7.9.1
  container_name: app-elasticsearch
  environment:
    - cluster.name=elastic-cluster
    - discovery.type=single-node
    - bootstrap.memory_lock=true
    - "ES_JAVA_OPTS=-Xmx1G"
  ports:
    - 9200:9200
  volumes:
    - esdata:/usr/share/elasticsearch/data
  networks:
    - es_net
```

---

## Elasticsearch 版本 2 镜像启动

本镜像服务用于app侧各类遥测源原始日志采集和存储，以及生成的 TTP 事件存储。

本服务以docker形式安装在app侧主机服务器上。  原生官方 Docker 镜像: `docker.elastic.co/elasticsearch/elasticsearch:8.19.5`

docker-compose中该镜像配置示例展示如下 ：


```yaml
es-log-storage:
  image: docker.elastic.co/elasticsearch/elasticsearch:8.19.5
  container_name: es-log
  environment:
    - discovery.type=single-node
    - "ES_JAVA_OPTS=-Xms1g -Xmx1g"
    - xpack.security.enabled=false
  ports:
    - 9201:9200
  volumes:
    - es_log_data:/usr/share/elasticsearch/data
  networks:
    - logging_net
```
### 特别注意事项
该版本 Elasticsearch 正常启动后，需要执行以下脚本创建相应探针索引的别名，否则后续 TTP 查询时会提示查询不到索引别名而报错：

```bash
elasticsearch/setup_es_templates_new.sh
```


---

## Elasticsearch 版本 3 镜像启动


本服务为agent侧 OpenRASP-Cloud 管理后台提供数据存储支持。

本服务以docker形式安装在agent侧服务器上。  原生官方 Docker 镜像: `elasticsearch:6.8.23`

docker-compose中该镜像配置示例展示如下 ：

```yaml
elasticsearch:
  image: elasticsearch:6.8.23
  container_name: es
  ports:
    - "9201:9200"
  networks:
    - rasp-net
  environment:
    - discovery.type=single-node
  ulimits:
    memlock:
      soft: -1
      hard: -1
  volumes:
    - es-data:/usr/share/elasticsearch/data
  healthcheck:
    test: ["CMD-SHELL", "curl -s -f http://localhost:9200/_cluster/health || exit 1"]
    interval: 5s
    timeout: 3s
    retries: 30
  restart: unless-stopped
```

---



## 注意事项

1. **版本 2 必须执行初始化脚本**：启动 es-log-storage 服务后，务必运行 `setup_es_templates_new.sh` 创建索引别名，否则 TTP 查询功能无法正常工作。
2. 三个版本的 Elasticsearch 分别运行在不同的 docker-compose 文件中，注意端口冲突问题。
3. 版本 3 配置了 healthcheck，RASP-Cloud 会等待 Elasticsearch 健康后再启动。
