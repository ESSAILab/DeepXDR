[English](README.md) | 中文

# Redis 部署文档

Redis 是本系统中用于数据缓存和临时存储的内存数据库服务，主要为 AI-Agent 模块中的长期威胁分析（LTTP）功能提供支持。用于存储中间计算结果、会话状态等临时数据。


## 镜像启动

本服务以docker形式安装在agent侧服务器上。  原生官方 Docker 镜像: `redis:7-alpine`

docker-compose中该镜像配置示例展示如下 ：

```yaml
redis:
  image: redis:7-alpine
  container_name: security-redis
  networks:
    - security-net
    - kafka-net
  volumes:
    - redis_data:/data
  restart: unless-stopped
```


镜像启动方式：

```bash
docker-compose -f docker-compose-defense.yml up -d redis
```

