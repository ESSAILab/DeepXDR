English | [中文](README_CN.md)

# MongoDB Deployment Guide

MongoDB is a dedicated database service for the OpenRASP-Cloud management backend, used for storing RASP-related configuration information, host information, policy data, etc.


## Image Startup

This service provides data persistence storage support for the agent-side OpenRASP-Cloud management backend.

This service is deployed as a Docker container on the agent-side server. Official native Docker image: `mongo:4.4`

The docker-compose configuration example for this image is shown below:

```yaml
mongodb:
  image: mongo:4.4
  container_name: mongodb
  networks:
    - rasp-net
  restart: unless-stopped
```

Startup command:

```bash
docker-compose -f docker-compose-agent.yml up -d mongodb
```

## Notes

1. MongoDB 4.4 is well compatible with OpenRASP-Cloud, it is not recommended to upgrade the version arbitrarily.
