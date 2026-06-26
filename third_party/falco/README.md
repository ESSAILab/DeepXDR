
English | [中文](README_CN.md)

# Falco Deployment Guide

Falco is an open-source cloud-native runtime security tool, incubated by CNCF. It monitors Linux system calls and container runtime behavior in real-time to detect anomalous activities and security threats. In this system, Falco is deployed on the application-side server as a kernel-level probe to monitor application container behavior. Detected security events are output in JSON format to log files, collected by filebeat, formatted by logstash, and then sent to Kafka for subsequent analysis.

In this system, Falco is deployed in Docker form for quick deployment and ease of use. The Falco Docker version used is `falcosecurity/falco:0.35.1`.


## 1. Falco Image Startup

The Falco probe needs to be installed as a Docker container on the application-side host. Official documentation reference: https://v0-31.falco.org/zh/docs/installation/

The docker-compose configuration example for this image is shown below:
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

### Configuration Description

| Configuration | Description |
|---------------|-------------|
| `falco_rules.local.yaml` | Custom rule file mount, defines containers and events to monitor |
| `falco.yaml` | Falco main configuration file mount, no modification needed |

Startup command:
```bash
docker-compose up -d falco

```
---  
Note: Modify the falco_rules.local.yaml configuration file, update the content in line 2 (the `items` field). Fill in the application container names to be monitored according to your actual environment. If you want to monitor all host events, leave this field empty.

```bash
vi falco_rules.local.yaml
```

Example (after modification):
```yaml
items: [app-dotcms]
```
  
Logs are output to the /var/log/falco/falco-alerts.json file, collected by filebeat.


---  

## 2. Data Flow

The data flow process of the Falco probe in the entire system is as follows:

```
+---------------+     System Call Monitoring      +------------------+
|  App Container|  ---------------------->  |   Falco Probe    |
|  (dotcms etc) |                          | (Privileged Mode)|
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
