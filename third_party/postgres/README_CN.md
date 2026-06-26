[English](README.md) | 中文

# PostgreSQL 部署文档

本服务中使用了两个不同版本的 PostgreSQL 数据库，分别用于不同的业务场景。

---

## PostgreSQL 版本 1 镜像启动



本服务为示范应用 dotcms 专用的数据库。根据使用者应用自身情况选择该服务是否需要同步部署。

本服务以docker形式安装在app侧服务器上。  原生官方 Docker 镜像: `postgres:13`

docker-compose中该镜像配置示例展示如下 ：

```yaml
db:
  image: postgres:13
  container_name: app-db
  command: postgres -c 'max_connections=400' -c 'shared_buffers=128MB'
  environment:
    "POSTGRES_USER": 'dotcmsdbuser'
    "POSTGRES_PASSWORD": 'password'
    "POSTGRES_DB": 'dotcms'
  volumes:
    - dbdata:/var/lib/postgresql/data
  networks:
    - db_net
```

---

## PostgreSQL 版本 2 镜像启动

本服务为 AI-Agent 模块中的长期威胁分析（LTTP）功能提供数据存储支持。

本服务以docker形式安装在agent侧服务器上。原生官方 Docker 镜像: `postgres:15-alpine`

docker-compose中该镜像配置示例展示如下 ：

```yaml
postgres:
  image: postgres:15-alpine
  container_name: security-postgres
  ports:
    - "5432:5432"
  networks:
    - security-net
  environment:
    POSTGRES_DB: security_db
    POSTGRES_USER: security_user
    POSTGRES_PASSWORD: security_pass
  volumes:
    - postgres_data:/var/lib/postgresql/data
  restart: unless-stopped
```

---



## 注意事项

1. 版本 1 为可选部署，如果不需要运行 dotcms 示范应用，可以不启动该服务。
2. 版本 2 为防御端核心服务，用于存储安全分析数据，建议必须部署。
