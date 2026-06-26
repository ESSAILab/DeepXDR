
[English](README.md) | 中文

#  Suricata部署说明

Suricata是一个免费的、开源的网络入侵检测系统（IDS）、入侵预防系统（IPS）和网络安全监控工具。它可以对网络流量进行实时分析和检测，并提供了丰富的规则库，可用于检测各种恶意行为，例如漏洞利用、恶意软件、网络扫描等。Suricata具有高性能、多线程处理、可扩展性强等特点，适用于大规模网络环境。同时，Suricata还支持多种协议解析，包括TCP、UDP、ICMP、HTTP等，可用于对不同类型的网络流量进行深度检测和分析。

## 1. 安装Suricata

### 安装服务

对于RedHat Enterprise Linux 7 和 CentOS 7 ，可以使用 EPEL 源.

```bash
yum install epel-release
yum install -y suricata
```

### 安装规则表

规则文件安装后，默认存储位置/var/lib/suricata/rules/suricata.rules，安装完成后，需要用suricata/suricata.rules替换默认存储位置的规则文件。

```bash
sudo yum install -y PyYAML
sudo suricata-update
```

## 2. 配置suricata

编辑 Suricata 的主配置文件： /etc/suricata/suricata.yaml,

- 找到 af-packet部分，将接口设置为应用所在主机的网卡，如eth0,
- 找到address-groups，设置 HOME_NET
- 配置日志输出，找到eve-log:，配置filename: /var/log/suricata/eve.json

## 3. 启动 Suricata

首先测试配置文件语法，执行命令如下：

```bash
sudo suricata -T -c /etc/suricata/suricata.yaml -v
```

以守护进程方式启动，方式如下：

### 启动 Suricata 服务

```bash
sudo systemctl start suricata
```

### 设置开机自启

```bash
sudo systemctl enable suricata
```

### 检查服务状态

```bash
sudo systemctl status suricata
```

## 4. 验证服务生效

suricata抓取存入到/var/log/suricata/eve.json文件中，查看该文件中是否有事件数据产生即可。


## 5. 数据流转流程

Suricata 探针在整个系统中的数据流转过程如下：

```
+------------------+    网络流量监控      +------------------+
|   应用主机网卡    |  ------------------>  |  Suricata 探针   |
|    (eth0 等)     |                      |  (主机进程运行)   |
+------------------+                      +------------------+
                                                |
                                                | 检测异常
                                                v
                                         +------------------+
                                         |   eve.json       |
                                         |  (JSON 日志文件)  |
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
                         |  Baseline 裁决   |          |   AI-Agent       |
                         |  + AI-Agent 分析 |          |  (长期威胁分析)   |
                         +------------------+          +------------------+
```

**流程说明：**

1. **Suricata 捕获异常**：Suricata 探针以主机进程形式运行在应用服务器上，通过监听网卡实时捕获网络流量中的异常行为
2. **输出日志文件**：检测到的安全事件以 JSON 格式写入 `/var/log/suricata/eve.json`
3. **Filebeat 采集**：Filebeat 通过挂载宿主机目录读取 Suricata 日志文件，将事件数据发送给 Logstash
4. **Logstash 分发**：Logstash 接收事件后，同时向两个方向推送：
   - **推送到 Kafka**：安全事件进入 Kafka 队列，供基线裁决模块和 AI-Agent 消费分析
   - **推送到 Elasticsearch**：原始日志数据存入 Elasticsearch，供 AI-Agent 查询和关联分析

## 6. 注意事项

suricata探针需要与待防护应用所在主机的网卡进行绑定。


## 7. 参考资料

- [Suricata官方文档](https://suricata.readthedocs.io/en/latest/index.html)


