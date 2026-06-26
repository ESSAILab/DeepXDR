# OpenRASP 二次开发说明

本仓库基于 [Baidu OpenRASP](https://github.com/baidu/openrasp.git) 开源项目进行二次开发，在保留原有核心功能的基础上，针对实际应用场景进行了检测能力增强、云控后端扩展及部署方式优化。

本项目包含两个核心组件，分别承担不同的职责：

**OpenRASP Cloud 管理后台**：负责接收、存储和分析 Java Agent 上报的安全事件数据，提供 Web 管理界面用于策略配置、插件管理、告警查看及多应用统一纳管。管理后台依赖 MongoDB 存储应用与配置信息，依赖 Elasticsearch 进行日志检索与数据分析。

**OpenRASP Java Agent 遥测源**：部署在待防护的 Java 应用服务器上，通过 Java Instrumentation 技术对应用运行时的敏感函数（如文件写入、数据库查询、命令执行等）进行 Hook 检测。当检测到异常行为时，Agent 会将事件信息实时上报至管理后台，并根据策略决定是否阻断当前请求。

---

## 原始项目文档

**原始参考项目地址**：https://github.com/baidu/openrasp.git  
**原始项目英文文档**：[README_origin.md](README_origin.md)  
**原始项目中文文档**：[README_CN_origin.md](README_CN_origin.md)  

---

## OpenRASP Cloud 管理后台

部署openrasp java agent遥测源时，需要依赖openrasp cloud管理后台，以便获取其对应的`app_id`、`app_secret`、`backend_url`这三个参数。可参考以下步骤进行优先部署。


### OpenRASP Cloud镜像启动

openrasp cloud云控管理后台依赖 MongoDB 和 Elasticsearch 组件。  
docker-compose中该镜像配置示例展示如下 ：


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

#### 参数配置说明

| 配置项 | 说明 |
|-------|------|
| `volumes` | 将宿主机上的 `./resources/rasp-cloud/app.conf`(该配置文件路径根据实际情况替换) 挂载到容器内 `/app/conf/app.conf`，便于在不重新构建镜像的情况下调整配置 |


> **注意**：启动前请确保宿主机已关闭 SELinux，避免容器挂载卷时出现权限问题。

#### 插件启用

管理后台安装完成后，需要在管理后台客户端页面上传上述的plugin-v3.js插件，登录云控后台 `插件管理-选择插件-提交` 执行上传操作，上传完成后，选择操作栏的推送操作。


### OpenRASP Cloud镜像构建

执行以下命令构建 Docker 镜像：

```bash
cd rasp-cloud-docker
docker build -t essaigroup/deepxdr-rasp-cloud:v0.3.0-alpha .
```
若docker-hub中已有该镜像，则可跳过此步骤。

> **提示**：若构建过程中出现网络访问失败（如 `apk add` 无法连接 Alpine 软件源），可通过 `--build-arg` 传入代理参数：
>
> ```bash
> docker build \
>   --build-arg HTTP_PROXY=http://<proxy-ip:port> \
>   --build-arg HTTPS_PROXY=http://<proxy-ip:port> \
>   -t essaigroup/deepxdr-rasp-cloud:v0.3.0-alpha .
> ```

---

## openRASP Java Agent编译方法

在项目根目录下执行以下命令：

```bash
./build-java.sh
```

编译成功后，将在项目根目录下生成以下安装包：

- `rasp-java.tar.gz` — Linux / macOS 平台安装包

> **注意**：若编译环境使用 JDK 12 及以上版本，需确保 `pom.xml` 中的 `source` 与 `target` 版本已设置为 1.8 或更高。本仓库已对相关配置进行了适配调整。

---

## OpenRASP Java Agent 遥测源安装

openrasp java agent 遥测源安装在app侧服务器上。


遥测源具体安装方法，请参考官方文档：

[https://rasp.baidu.com/doc/install/manual/tomcat.html#auto](https://rasp.baidu.com/doc/install/manual/tomcat.html#auto)


---


## 数据流转流程

以下为 OpenRASP Java Agent 遥测源在系统中的完整数据流转示意：

```
+-------------------+     Hook 检测      +----------------------+
|    应用 App       | --------------->   |  OpenRASP Java Agent |
|                   |                    |      遥测源            |
|                   | <---------------   |                      |
|                   |    阻断 / 放行      |   捕获异常事件        |
+-------------------+                    +----------+-----------+
                                                    |
                                                    | 写入日志
                                                    v
                                         +---------------------+
                                         |  OpenRASP 异常事件   |
                                         | 日志文件 (rasp/logs) |
                                         +----------+----------+
                                                    |
                                                    | 采集
                                                    v
                                         +---------------------+
                                         |      Filebeat       |
                                         |    (读取日志文件)    |
                                         +----------+----------+
                                                    |
                                                    | 转发
                                                    v
                                         +---------------------+
                                         |      Logstash       |
                                         +----------+----------+
                                                    |
                         +--------------------------+--------------------------+
                         |                                                     |
                         | 推送                                                | 推送
                         v                                                     v
             +---------------------+                               +---------------------+
             |       Kafka         |                               |   Elasticsearch     |
             | (用于 baseline      |                               |   (用于 ai-agent    |
             |  及 ai-agent 分析)  |                               |    分析)            |
             +---------------------+                               +---------------------+
```

流程说明：

1. **异常捕获**：应用运行时，OpenRASP Agent 通过 Hook 技术拦截敏感函数调用，捕获异常行为事件。
2. **日志落盘**：Agent 将异常事件写入本地日志文件。
3. **日志采集**：Filebeat 持续监控日志目录，实时采集新增的事件日志数据。
4. **数据分发**：Filebeat 将采集到的数据转发至 Logstash，由 Logstash 进行数据解析与路由。
5. **下游推送**：Logstash 将事件数据同时推送至两个下游组件：
   - **Kafka**：为基线分析（baseline）及 AI-Agent 分析提供实时数据流。
   - **Elasticsearch**：为 AI-Agent 分析提供结构化数据存储与检索能力。

---

## 二次开发功能说明

### 1. Java Agent 检测逻辑增强

#### 1.1 文件写入事件内容提取

在 `FileOutputStreamHook` 检测点中，新增了写入文件内容的读取与提取功能。当触发文件写入事件时，系统会尝试读取目标文件内容（上限为 4 KB），并将内容随事件参数上报，便于后续安全分析。为避免与 `FileInputStreamHook` 的读文件检测产生循环触发，引入了 `ThreadLocal` 上下文标记机制，确保内容提取过程中不会重复触发读文件检测事件。

#### 1.2 事件字段名称脱敏

针对事件日志中涉及攻击行为的字段名称进行了调整，将原有字段重命名为更中性的表述，以适配不同场景下的日志规范要求：

| 原始字段名 | 调整后字段名 |
|-----------|-------------|
| `attack_params` | `raw_behavior_params` |
| `attack_type` | `raw_behavior` |
| `attack_source` | `request_source` |

上述字段重命名仅在 `event_type` 为 `record_log` 时生效，其余事件类型保持不变。

### 2. 检测插件增强

在官方 JavaScript 插件的基础上，针对文件写入（`writefile`）检测场景进行了多轮迭代优化，插件位置在openrasp/plugins/official/plugin-v3：

- **plugin-v3**：调整了 writefile 脚本文件检测逻辑，屏蔽了原始事件上报，并修复了上传脚本不报事件的问题；同时去除了 `.so` 文件写入产生的误报。



### 3. 云控后端扩展


修复了云控后端中 Base64 编码字符 `+` 号被错误转义的问题，确保涉及特殊字符的数据在传输和存储过程中的完整性。

### 4. Docker 部署支持

新增了完整的 `rasp-cloud-docker` 构建目录，提供基于 Alpine 3.18 的容器化部署方案。目录内包含 Dockerfile、前端静态资源、后端二进制文件、配置文件、GeoIP 数据库及邮件/崩溃报告模板，实现了云控管理后台的一键容器化构建与部署。

### 5. 编译适配

将 Java 编译目标版本从 1.6 调整为 1.8，解决了在高版本 JDK（如 JDK 18）环境下编译失败的问题，确保项目可在现代 Java 环境中正常构建。

---

## 许可证

本项目遵循原始开源项目的许可证协议。详见原始项目仓库中的 LICENSE 文件。
