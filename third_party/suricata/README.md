
English | [中文](README_CN.md)

Suricata is a free and open source network intrusion detection system (IDS), intrusion prevention system (IPS), and network security monitoring tool. It can perform real-time analysis and detection of network traffic, and provides a rich rule set for detecting various malicious behaviors, such as vulnerability exploits, malware, network scanning, etc. Suricata features high performance, multi-threading processing, and strong scalability, making it suitable for large-scale network environments. Additionally, Suricata supports multiple protocol parsers, including TCP, UDP, ICMP, HTTP, etc., which can be used for in-depth detection and analysis of different types of network traffic.

## 1. Install Suricata

### Install Service

For RedHat Enterprise Linux 7 and CentOS 7, you can use the EPEL repository.

```bash
yum install epel-release
yum install -y suricata
```

### Install Ruleset

After installation, the default rule file location is /var/lib/suricata/rules/suricata.rules. After installation is complete, you need to replace the default rule file with suricata/suricata.rules.

```bash
sudo yum install -y PyYAML
sudo suricata-update
```

## 2. Configure Suricata

Edit Suricata's main configuration file: /etc/suricata/suricata.yaml,

- Locate the af-packet section and set the interface to the network card of the host running the application, e.g., eth0.
- Find address-groups, set HOME_NET
- Configure logging output, find eve-log:, configure filename: /var/log/suricata/eve.json

## 3. Start Suricata

First test the configuration file syntax by executing the following command:

```bash
sudo suricata -T -c /etc/suricata/suricata.yaml -v
```

Start as a daemon process, as follows:

### Start Suricata Service

```bash
sudo systemctl start suricata
```

### Enable Auto-start on Boot

```bash
sudo systemctl enable suricata
```

### Check Service Status

```bash
sudo systemctl status suricata
```

## 4. Verify Service is Working

Suricata captures and stores data in the /var/log/suricata/eve.json file. Just check if there is event data generated in that file.


## 5. Data Flow

The data flow process of the Suricata probe in the entire system is as follows:

```
+------------------+   Network Traffic Monitoring +------------------+
|  Host NIC        |  ----------------------->  |  Suricata Probe  |
|   (eth0 etc)     |                           | (Host Process)   |
+------------------+                           +------------------+
                                                      |
                                                      | Detect Anomaly
                                                      v
                                               +------------------+
                                               |   eve.json       |
                                               | (JSON Log File)  |
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
                               | Baseline Adjudication|      |   AI-Agent       |
                               |  + AI-Agent Analysis |      | (Long-Term Threat|
                               +------------------+          |   Analysis)      |
                                                             +------------------+
```

**Flow Description:**

1. **Suricata Captures Anomalies**: The Suricata probe runs as a host process on the application server, capturing anomalous behavior in network traffic in real-time by listening to the network card
2. **Output Log File**: Detected security events are written in JSON format to `/var/log/suricata/eve.json`
3. **Filebeat Collects**: Filebeat reads Suricata log files by mounting the host directory and sends event data to Logstash
4. **Logstash Distributes**: After receiving events, Logstash pushes simultaneously in two directions:
   - **Push to Kafka**: Security events enter the Kafka queue for baseline adjudication module and AI-Agent to consume and analyze
   - **Push to Elasticsearch**: Raw log data is stored in Elasticsearch for AI-Agent to query and correlate analysis

## 6. Notes

The Suricata probe needs to bind to the network card of the host where the protected application resides.


## 7. References

- [Suricata Official Documentation](https://suricata.readthedocs.io/en/latest/index.html)
