English | [中文](README_CN.md)

# PostgreSQL Deployment Guide

This service uses two different versions of PostgreSQL databases for different business scenarios.

---

## PostgreSQL Version 1 Image Startup



This service is a dedicated database for the demo application dotcms. Users can choose whether to deploy this service based on their own application requirements.

This service is deployed as a Docker container on the application-side server. Official native Docker image: `postgres:13`

The docker-compose configuration example for this image is shown below:

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

## PostgreSQL Version 2 Image Startup

This service provides data storage support for the Long-Term Threat Analysis (LTTP) function in the AI-Agent module.

This service is deployed as a Docker container on the agent-side server. Official native Docker image: `postgres:15-alpine`

The docker-compose configuration example for this image is shown below:

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



## Notes

1. Version 1 is optional. If you do not need to run the dotcms demo application, you can skip this service.
2. Version 2 is a core defense-side service for storing security analysis data and is recommended for mandatory deployment.
