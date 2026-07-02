# OpenRASP Secondary Development Guide

English | [中文](README.md)

This repository is based on the [Baidu OpenRASP](https://github.com/baidu/openrasp.git) open-source project for secondary development. While retaining the original core functionality, it enhances detection capabilities, extends the cloud control backend, and optimizes deployment methods for real-world application scenarios.

This project consists of two core components, each serving different responsibilities:

**OpenRASP Cloud Management Backend**: Responsible for receiving, storing, and analyzing security event data reported by the Java Agent. It provides a Web management interface for policy configuration, plugin management, alert viewing, and unified multi-application management. The management backend depends on MongoDB for application and configuration storage, and on Elasticsearch for log retrieval and data analysis.

**OpenRASP Java Agent Telemetry Source**: Deployed on the Java application server to be protected. It uses Java Instrumentation technology to Hook and detect sensitive functions at application runtime (such as file writing, database queries, command execution, etc.). When abnormal behavior is detected, the Agent reports event information to the management backend in real time and decides whether to block the current request based on the policy.

---

## Original Project Documentation

**Original reference project**: https://github.com/baidu/openrasp.git

---

## Secondary Development Source Code Acquisition

The secondary development source code is obtained by applying patches to the openrasp open-source code. The commands are as follows:
```bash
git clone https://github.com/baidu/openrasp.git .
git apply --exclude=README.md --exclude=README_CN.md --exclude=plugins/official/plugin.js openrasp.patch
```

## OpenRASP Cloud Management Backend

When deploying the openrasp java agent telemetry source, the openrasp cloud management backend is required to obtain the corresponding `app_id`, `app_secret`, and `backend_url` parameters. You can refer to the following steps for priority deployment.


### OpenRASP Cloud Image Startup

The openrasp cloud management backend depends on MongoDB and Elasticsearch components.
A sample Docker Compose configuration is shown below:


```yaml
version: "3.8"

services:
  mongodb:
    image: mongo:4.4
    container_name: mongodb
    networks:
      - rasp-net
    restart: unless-stopped

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

  rasp-cloud:
    image: essaigroup/deepxdr-rasp-cloud:v0.3.0-alpha
    container_name: rasp-cloud
    dns_search: .
    dns: 127.0.0.11
    networks:
      - rasp-net
      - kafka-net
    ports:
      - "8086:8086"
    depends_on:
      mongodb:
        condition: service_started
      elasticsearch:
        condition: service_healthy
    volumes:
      - ./resources/rasp-cloud/app.conf:/app/conf/app.conf
    restart: unless-stopped

networks:
  rasp-net:
  kafka-net:

volumes:
  es-data:
```

#### Parameter Configuration Notes

| Configuration Item | Description |
|-------|------|
| `volumes` | Mounts the host's `./resources/rasp-cloud/app.conf` (replace the configuration file path according to the actual situation) to the container's `/app/conf/app.conf`, allowing configuration adjustments without rebuilding the image |


> **Note**: Please ensure that SELinux is disabled on the host before starting to avoid permission issues when mounting container volumes.

#### Plugin Enablement

After the management backend installation is complete, you need to upload the above plugin-v3.js plugin on the management backend client page. Log in to the cloud control backend and go to `Plugin Management -> Select Plugin -> Submit` to perform the upload operation. After the upload is complete, select the push operation in the action column.

#### OpenRASP Raw Event Support Types

This service has enhanced the openrasp raw event collection through customized modifications. The specific supported raw events are as follows:

| Event Name | Description |
|---------|------|
| `sql` | Database operations |
| `readfile` | File reading |
| `fileUpload` | File upload |
| `command` | Command line operations |


### OpenRASP Cloud Image Build

Execute the following command to build the Docker image:

```bash
cd rasp-cloud-docker
docker build -t essaigroup/deepxdr-rasp-cloud:v0.3.0-alpha .
```
If the image already exists in docker-hub, you can skip this step.

> **Tip**: If network access fails during the build process (e.g., `apk add` cannot connect to the Alpine software source), you can pass proxy parameters via `--build-arg`:
>
> ```bash
> docker build \
>   --build-arg HTTP_PROXY=http://<proxy-ip:port> \
>   --build-arg HTTPS_PROXY=http://<proxy-ip:port> \
>   -t essaigroup/deepxdr-rasp-cloud:v0.3.0-alpha .
> ```

---

## OpenRASP Java Agent Compilation Method

Execute the following command in the project root directory:

```bash
./build-java.sh
```

After successful compilation, the following installation packages will be generated in the project root directory:

- `rasp-java.tar.gz` — Linux / macOS platform installation package

> **Note**: If the compilation environment uses JDK 12 or higher, ensure that the `source` and `target` versions in `pom.xml` are set to 1.8 or higher. This repository has already made adaptation adjustments for the relevant configurations.

---

## OpenRASP Java Agent Telemetry Source Installation

The openrasp java agent telemetry source is installed on the app-side server.


For specific installation methods, please refer to the official documentation:

[https://rasp.baidu.com/doc/install/manual/tomcat.html#auto](https://rasp.baidu.com/doc/install/manual/tomcat.html#auto)


---


## Data Flow Process

The following is a complete data flow diagram of the OpenRASP Java Agent telemetry source in the system:

```
+-------------------+     Hook Detection    +----------------------+
|    App            | --------------->   |  OpenRASP Java Agent |
|                   |                    |    Telemetry Source  |
|                   | <---------------   |                      |
|                   |   Block / Allow    |   Capture Exception  |
+-------------------+                    +----------+-----------+
                                                    |
                                                    | Write Log
                                                    v
                                         +---------------------+
                                         |  OpenRASP Exception  |
                                         | Log File (rasp/logs) |
                                         +----------+----------+
                                                    |
                                                    | Collect
                                                    v
                                         +---------------------+
                                         |      Filebeat       |
                                         |   (Read Log File)   |
                                         +----------+----------+
                                                    |
                                                    | Forward
                                                    v
                                         +---------------------+
                                         |      Logstash       |
                                         +----------+----------+
                                                    |
                         +--------------------------+--------------------------+
                         |                                                     |
                         | Push                                                | Push
                         v                                                     v
             +---------------------+                               +---------------------+
             |       Kafka         |                               |   Elasticsearch     |
             | (For baseline       |                               |   (For ai-agent     |
             |  and ai-agent       |                               |    analysis)        |
             |  analysis)          |                               |                     |
             +---------------------+                               +---------------------+
```

Process Description:

1. **Exception Capture**: At application runtime, the OpenRASP Agent intercepts sensitive function calls through Hook technology to capture abnormal behavior events.
2. **Log Persistence**: The Agent writes exception events to local log files.
3. **Log Collection**: Filebeat continuously monitors the log directory and collects new event log data in real time.
4. **Data Distribution**: Filebeat forwards the collected data to Logstash, which performs data parsing and routing.
5. **Downstream Push**: Logstash simultaneously pushes event data to two downstream components:
   - **Kafka**: Provides real-time data streams for baseline analysis and AI-Agent analysis.
   - **Elasticsearch**: Provides structured data storage and retrieval capabilities for AI-Agent analysis.

---

## Secondary Development Feature Description

### 1. Java Agent Detection Logic Enhancement

#### 1.1 File Write Event Content Extraction

In the `FileOutputStreamHook` detection point, new file write content reading and extraction functionality has been added. When a file write event is triggered, the system attempts to read the target file content (up to 4 KB) and reports the content along with the event parameters for subsequent security analysis. To avoid circular triggering with `FileInputStreamHook`'s file read detection, a `ThreadLocal` context marking mechanism is introduced to ensure that the content extraction process does not repeatedly trigger file read detection events.

#### 1.2 Event Field Name Desensitization

Field names involving attack behavior in event logs have been adjusted, renaming the original fields to more neutral expressions to adapt to log specification requirements in different scenarios:

| Original Field Name | Adjusted Field Name |
|-----------|-------------|
| `attack_params` | `raw_behavior_params` |
| `attack_type` | `raw_behavior` |
| `attack_source` | `request_source` |

The above field renaming only takes effect when `event_type` is `record_log`; other event types remain unchanged.

### 2. Detection Plugin Enhancement

Based on the official JavaScript plugin, the file write (`writefile`) detection scenario has undergone multiple rounds of iterative optimization. The plugin is located at openrasp/plugins/official/plugin-v3:

- **plugin-v3**: Adjusted the writefile script file detection logic, shielded raw event reporting, and fixed the issue where uploaded scripts did not report events; at the same time, removed false positives caused by `.so` file writes.



### 3. Cloud Control Backend Extension


Fixed the issue where the Base64 encoded character `+` was incorrectly escaped in the cloud control backend, ensuring the integrity of data involving special characters during transmission and storage.

### 4. Docker Deployment Support

Added a complete `rasp-cloud-docker` build directory, providing a containerized deployment solution based on Alpine 3.18. The directory contains Dockerfile, frontend static resources, backend binary files, configuration files, GeoIP database, and email/crash report templates, enabling one-click containerized build and deployment of the cloud control management backend.

### 5. Compilation Adaptation

Adjusted the Java compilation target version from 1.6 to 1.8, resolving compilation failures in high-version JDK environments (such as JDK 18) and ensuring the project can be built normally in modern Java environments.

---

## License

This project follows the license agreement of the original open-source project. See the LICENSE file in the original project repository for details.
