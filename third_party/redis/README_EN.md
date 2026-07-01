# Redis Deployment Guide

English | [中文](README.md)

Redis is an in-memory database service used for data caching and temporary storage in this system, primarily providing support for the Long-Term Threat Analysis (LTTP) function in the AI-Agent module. It is used for storing intermediate calculation results, session states, and other temporary data.


## Image Startup

This service is deployed as a Docker container on the agent-side server. Official native Docker image: `redis:7-alpine`

The docker-compose configuration example for this image is shown below:

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


Startup command:

```bash
docker-compose -f docker-compose-defense.yml up -d redis
```
