# Elasticsearch MCP Server 容器化部署指南

## 一、构建镜像

### 1. 确保在项目根目录
```bash
cd /home/wangbo/elasticsearch-mcp-server
```

### 2. 构建镜像
```bash
docker build -f Dockerfile -t elasticsearch-mcp-server .
```

### 3. 标记镜像
```bash
docker tag elasticsearch-mcp-server:latest 172.18.8.210:5000/library/elasticsearch-mcp-server:20260212
```

### 4. 推送到 Harbor
```bash
docker push 172.18.8.210:5000/library/elasticsearch-mcp-server:20260212
```

## 二、Docker Compose 配置

### 方式一：直接添加到现有 docker-compose.yml

将以下内容添加到您的主 `docker-compose.yml` 文件中：

```yaml
services:
  # --- Elasticsearch MCP Server ---
  elasticsearch-mcp-server:
    image: 172.18.8.210:5000/library/elasticsearch-mcp-server:20260212
    container_name: app-elasticsearch-mcp-server
    environment:
      - ELASTICSEARCH_HOSTS=http://172.18.8.175:9201
      - VERIFY_CERTS=false
      - DISABLE_HIGH_RISK_OPERATIONS=true
      - EQL_MAX_FIELD_LENGTH=1000
      - EQL_MAX_LIST_ITEMS=5
    user: root
    ports:
      - "8002:8000"  # 宿主机 8002 映射到容器 8000
    networks:
      - logging_net
    restart: always
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 128M
```

### 方式二：使用 docker-compose-service.yml 文件

如果您想单独管理该服务：

```bash
docker-compose -f docker-compose-service.yml up -d
```

## 三、启动服务

### 启动所有服务
```bash
docker-compose up -d
```

### 仅启动 elasticsearch-mcp-server
```bash
docker-compose up -d elasticsearch-mcp-server
```

### 查看日志
```bash
docker logs -f app-elasticsearch-mcp-server
```

### 停止服务
```bash
docker-compose stop elasticsearch-mcp-server
```

### 重启服务
```bash
docker-compose restart elasticsearch-mcp-server
```

## 四、环境变量说明

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| ELASTICSEARCH_HOSTS | http://172.18.8.175:9201 | Elasticsearch 连接地址 |
| VERIFY_CERTS | false | 是否验证 SSL 证书 |
| DISABLE_HIGH_RISK_OPERATIONS | true | 是否禁用高风险操作 |
| EQL_MAX_FIELD_LENGTH | 1000 | 字符串字段最大长度，超过将被截断 |
| EQL_MAX_LIST_ITEMS | 5 | 字符串列表最大项目数，超过将被截断 |

## 五、验证部署

### 1. 检查容器状态
```bash
docker ps | grep elasticsearch-mcp-server
```

### 2. 测试服务可用性
```bash
curl http://localhost:8002/mcp/
```

### 3. 查看容器日志
```bash
docker logs app-elasticsearch-mcp-server
```

## 六、更新部署

当代码更新后，需要重新构建和部署：

```bash
# 1. 停止并删除旧容器
docker-compose stop elasticsearch-mcp-server
docker-compose rm -f elasticsearch-mcp-server

# 2. 重新构建镜像
docker build -f Dockerfile -t elasticsearch-mcp-server .
docker tag elasticsearch-mcp-server:latest 172.18.8.210:5000/library/elasticsearch-mcp-server:20260212
docker push 172.18.8.210:5000/library/elasticsearch-mcp-server:20260212

# 3. 拉取最新镜像并启动
docker-compose pull elasticsearch-mcp-server
docker-compose up -d elasticsearch-mcp-server

# 4. 验证
# docker logs -f app-elasticsearch-mcp-server
```

## 七、常见问题

### 1. 容器无法启动
检查日志：
```bash
docker logs app-elasticsearch-mcp-server
```

### 2. 连接 Elasticsearch 失败
确保 Elasticsearch 地址可访问：
```bash
curl http://172.18.8.175:9201
```

### 3. 端口冲突
如果 8002 端口被占用，修改为其他端口：
```yaml
ports:
  - "8004:8000"  # 使用 8004 端口
```
