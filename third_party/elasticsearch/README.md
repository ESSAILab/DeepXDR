English | [中文](README_CN.md)

# Elasticsearch Deployment Guide

This service uses three different versions of Elasticsearch for different business scenarios.

---

## Elasticsearch Version 1 Image Startup


This service is a dedicated search engine for the dotcms application.

This service is deployed as a Docker container on the application-side host server. Official native Docker image: `docker.elastic.co/elasticsearch/elasticsearch:7.9.1`

The docker-compose configuration example for this image is shown below:

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

## Elasticsearch Version 2 Image Startup

This image service is used for collecting and storing raw telemetry source logs on the application side, as well as storing generated TTP events.

This service is deployed as a Docker container on the application-side host server. Official native Docker image: `docker.elastic.co/elasticsearch/elasticsearch:8.19.5`

The docker-compose configuration example for this image is shown below:


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
### Special Notes
After this version of Elasticsearch starts normally, you need to execute the following script to create the corresponding probe index aliases, otherwise subsequent TTP queries will fail with an error indicating that the index alias cannot be found:

```bash
elasticsearch/setup_es_templates_new.sh
```


---

## Elasticsearch Version 3 Image Startup


This service provides data storage support for the agent-side OpenRASP-Cloud management backend.

This service is deployed as a Docker container on the agent-side server. Official native Docker image: `elasticsearch:6.8.23`

The docker-compose configuration example for this image is shown below:

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



## Notes

1. **Version 2 requires initialization script**: After starting the es-log-storage service, be sure to run `setup_es_templates_new.sh` to create index aliases, otherwise the TTP query function will not work properly.
2. The three versions of Elasticsearch run in different docker-compose files, so be aware of port conflicts.
3. Version 3 is configured with healthcheck, and RASP-Cloud will wait until Elasticsearch is healthy before starting.
