# MongoDB 部署文档

[English](README_EN.md) | 中文

MongoDB 是 OpenRASP-Cloud 管理后台的专用数据库服务，用于存储 RASP 相关的配置信息、主机信息、策略数据等。


## 镜像启动

本服务为agent侧 OpenRASP-Cloud 管理后台提供数据持久化存储支持。

本服务以docker形式安装在agent侧服务器上。  原生官方 Docker 镜像: `mongo:4.4`

docker-compose中该镜像配置示例展示如下 ：

```yaml
mongodb:
  image: mongo:4.4
  container_name: mongodb
  networks:
    - rasp-net
  restart: unless-stopped
```

镜像启动方式：

```bash
docker-compose -f docker-compose-agent.yml up -d mongodb
```

## 注意事项

1. MongoDB 4.4 版本与 OpenRASP-Cloud 兼容性良好，不建议随意升级版本。

