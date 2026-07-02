# Logstash Deployment Guide

English | [中文](README.md)

This service is deployed in Docker form, using the official image `docker.elastic.co/logstash/logstash:8.19.5`.

## Logstash Image Startup

Logstash needs to be deployed as a Docker container on the application-side server.

The docker-compose configuration example for this image is shown below:

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

**Configuration Explanation**:

- `volumes`: Mounts Logstash's pipeline configuration file `logstash.conf` and main configuration file `logstash.yml`, both in read-only mode.


Start the logstash service:

```bash
docker-compose -f docker-compose-app.yml up -d logstash

```



Modify the logstash.conf configuration file. You need to configure the Kafka address in it. The ElasticSearch address is specified internally and does not need to be modified.

```yaml
vi logstash.conf
```

Modify the `<agent-ip>` content in the kafka section on line 98, replacing this IP with the actual IP address of the agent-side server where the kafka service is deployed, for example: 172.19.9.192

## Data Flow

The telemetry sources' data flow process in the entire system is as follows:

```
+---------------+     System Call Monitoring      +------------------+
|  App Container|  ---------------------->  |   Telemetry Source|
|  (dotcms etc) |                          |                  |
+---------------+                          +------------------+
                                                  |
                                                  | Detect Anomaly
                                                  v
                                           +------------------+
                                           | falco-alerts.json|
                                           |  (JSON Log File) |
                                           +------------------+
                                                  |
                                                  | Filebeat Collect
                                                  v
                                           +------------------+
                                           |    Filebeat      |
                                           +------------------+
                                                  |
                                                  | Forward
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
                           | (Security Queue) |          | (Log Storage)    |
                           +------------------+          +------------------+
                                  |                               |
                                  | Consume                       | Query
                                  v                               v
                           +------------------+          +------------------+
                           | Baseline         |          |   AI-Agent       |
                           | Adjudication     |          | (Long-Term Threat|
                           | + AI-Agent       |          |   Analysis)      |
                           |   Analysis       |          +------------------+
                           +------------------+
```

**Flow Description:**

1. **Falco Captures Anomalies**: The Falco probe runs in privileged mode on the application host, capturing anomalous behavior of application containers in real-time through system call monitoring
2. **Output Log File**: Detected security events are written in JSON format to `/var/log/falco/falco-alerts.json`
3. **Filebeat Collects**: Filebeat reads Falco log files through shared volumes and sends event data to Logstash
4. **Logstash Distributes**: After receiving events, Logstash pushes simultaneously in two directions:
   - **Push to Kafka**: Security events enter the Kafka queue for baseline adjudication module and AI-Agent to consume and analyze
   - **Push to Elasticsearch**: Raw log data is stored in Elasticsearch for AI-Agent to query and correlate analysis
