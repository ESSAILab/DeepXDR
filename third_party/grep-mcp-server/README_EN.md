# Grep MCP Secondary Development Guide

English | [中文](README.md)

## Original Project

This project is a secondary development based on the open-source project [erniebrodeur/mcp-grep](https://github.com/erniebrodeur/mcp-grep).

For the complete feature documentation of the original project, please refer to [README_origin.md](README_origin.md).

---

## Image Startup

This service is deployed on the application-side server to provide file content search tools for agent threat analysis.

The following `docker-compose-app.yml` configuration example demonstrates how to deploy the `supergateway-grep` service:

```yaml
supergateway-grep:
  image: essaigroup/deepxdr-grep-mcp-server:v0.3.0-alpha
  container_name: app-supergateway-grep
  environment:
    MCP_GREP_MAX_RESULTS: 10
  user: root
  ports:
    - "8003:8000"
  volumes:
    - cms-shared:[your-app-workspace]
  networks:
    - logging_net
  restart: always
  deploy:
    resources:
      limits:
        memory: 1G
```

**Configuration Notes:**

- `environment.MCP_GREP_MAX_RESULTS`: Sets the maximum number of results returned per search
- `volumes`: Mounts the shared storage volume to the application working directory inside the container for the grep tool to access target files. Users must configure this to match the application working directory.

---

## Docker Image Build

```bash
# Build image
docker build -f Dockerfile.source -t essaigroup/deepxdr-grep-mcp-server:v0.3.0-alpha .

```

If the image already exists in Docker Hub, this step can be skipped.

---

---

## Key Features

MCP-Grep exposes system grep functionality as a standardized service interface through the Model Context Protocol (MCP). The core capabilities include:

- **File Content Search**: Based on the system grep binary, supports searching for matching content in specified files or directories using regular expressions
- **Common Search Options**:
  - Case-insensitive matching (`-i`)
  - Display context lines (N lines before and after the match)
  - Fixed string matching (non-regex mode)
  - Recursive directory searching
- **Natural Language Prompt Understanding**: Supports describing search requirements in natural language, lowering the barrier for LLM invocation
- **Structured Result Return**: Search results are returned in JSON format, including filename, line number, matched content, and context

---

## Secondary Development Features

### 1. Configurable Maximum Result Count

In the original implementation, the maximum number of returned `grep` search results was hard-coded to `50`. This secondary development extracts that limit into a dynamically configurable value via the environment variable `MCP_GREP_MAX_RESULTS`, allowing flexible adjustment based on actual deployment scenarios.

- **Environment Variable**: `MCP_GREP_MAX_RESULTS`
- **Default Value**: `50`
- **Description**: When the number of matched results exceeds this threshold, the system automatically truncates and returns the first N results, appending a prompt message indicating the actual total number of hits.

### 2. Communication Protocol Adaptation

The original project runs the MCP server via stdio. This secondary development introduces [supergateway](https://github.com/supergateway) as a protocol conversion layer, exposing the stdio interface as a WebSocket protocol for easier integration in containerized and microservices architectures.

- **Output Protocol**: `ws` (WebSocket)
- **Message Path**: `/message`
- **Listening Port**: `8000`

### 3. Docker Image Build

A new `Dockerfile.source` build file is added. The image is based on `python:3.11-slim` and comes with a pre-installed Node.js runtime environment to support supergateway startup.

---

## License

MIT
