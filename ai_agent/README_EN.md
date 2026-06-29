# AI Agent Usage Guide

English | [中文](README.md)

This document only covers runtime configuration, Docker image builds, and container startup for the `ai_agent` service.

## Runtime Dependencies

Prepare these external services before starting the container:

- Kafka
- Redis
- ElasticSearch 8.x
- PostgreSQL
- OpenAI-compatible LLM endpoint
- DashScope API key if the MITRE RAG embedding/rerank path is enabled

Kafka `KAFKA_TOPIC` defaults to `agent`. This topic should receive high-value security events from the upstream baseline adjudication service.

## Environment Variables

Common configuration is shown below. In deployment, inject these values through `.env`, container orchestration secrets, or environment variables:

```bash
# Core services
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/security_analysis
REDIS_URL=redis://redis:6379/0
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_TOPIC=agent
KAFKA_GROUP_ID=security-analysis-group
API_PORT=8000

# ElasticSearch 8.x
ELASTICSEARCH_HOST=elasticsearch
ELASTICSEARCH_PORT=9200
ELASTICSEARCH_USE_SSL=false

# Protected operator APIs
BACKEND_API_KEY=replace-with-a-random-operator-secret

# Runtime behavior
SHORT_TTP_WINDOW_INTERVAL=1.0
MAX_EVENTS_PER_WINDOW=1000
SHORT_TTP_MAX_CONCURRENT=3
SHORT_TTP_QUEUE_MAX_SIZE=128
LONG_TTP_GENERATION_INTERVAL=1800
LONG_TTP_MAX_CONCURRENT_GENERATIONS=2
LONG_TTP_TRIGGER_SUPPRESSION_SECONDS=3600
HUMAN_FEEDBACK_TIMEOUT_SECONDS=1800
USE_MITRE_INVESTIGATION_SUBGRAPH=false

# LLM
OPENAI_API_KEY=replace-with-your-llm-api-key
OPENAI_BASE_URL=replace-with-your-openai-compatible-base-url
OPENAI_MODEL=replace-with-your-model-name
MITRE_RAG_LLM_MODEL=replace-with-your-mitre-rag-judge-model

# MITRE RAG: DashScope embedding/rerank
DASHSCOPE_API_KEY=replace-with-your-dashscope-api-key
MITRE_ATTACK_CACHE_DIR=/app/ai_agent/.cache/mitre_attack

# Logging
LOG_LEVEL=INFO
LOG_FILE=/app/logs/security_analysis.log
CORS_ALLOW_ORIGINS=http://localhost:8000
```

## Build The Image

Build from the `ai_agent` directory:

```bash
cd ai_agent
docker build -t analysis:latest .
```

To use a China-accessible PyPI mirror:

```bash
cd ai_agent
docker build \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -t analysis:latest .
```

## Start The Container

Start with an environment file:

```bash
docker run -d \
  --name analysis \
  --env-file ../.env \
  -p 8000:8000 \
  analysis:latest
```

You can also pass key variables directly:

```bash
docker run -d \
  --name analysis \
  -e DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/security_analysis \
  -e REDIS_URL=redis://redis:6379/0 \
  -e KAFKA_BOOTSTRAP_SERVERS=kafka:9092 \
  -e KAFKA_TOPIC=agent \
  -e ELASTICSEARCH_HOST=elasticsearch \
  -e BACKEND_API_KEY=replace-with-a-random-operator-secret \
  -e OPENAI_API_KEY=replace-with-your-llm-api-key \
  -e OPENAI_BASE_URL=replace-with-your-openai-compatible-base-url \
  -e OPENAI_MODEL=replace-with-your-model-name \
  -p 8000:8000 \
  analysis:latest
```

The service listens on container port `8000` by default.

## Health Check

```bash
curl http://localhost:8000/health
```

For API-key-protected endpoints, include the request header:

```bash
curl -H "X-API-Key: $BACKEND_API_KEY" \
  http://localhost:8000/longttp
```

