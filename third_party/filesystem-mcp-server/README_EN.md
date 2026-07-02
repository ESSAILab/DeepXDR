# Filesystem MCP Server — Secondary Development

English | [中文](README.md)

## Project Description

This project is a secondary development based on the `src/filesystem` module from the open-source repository [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers).

**Original Reference Project**: https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem  
**Original Project Documentation**: [README_origin.md](README_origin.md)


## Image Deployment

This service is deployed on the application-side server to provide file operation tools for the AI-agent threat analysis intelligence.

### 1. Docker Compose Configuration Example

The following example demonstrates the image configuration in docker-compose:

```yaml
  supergateway-filesystem:
    image: essaigroup/deepxdr-filesystem-mcp-server:v0.3.0-alpha
    container_name: app-supergateway-filesystem
    user: root
    tty: true
    ports:
      - "8001:8001"
    volumes:
      - cms-shared:[your-app-workspace]
    networks:
      - logging_net
    restart: always
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 256M
```

### 2. Configuration Parameters

| Parameter | Description |
|-----------|-------------|
| `volumes` | Mounts the shared storage volume to the application workspace inside the container, serving as the target working directory accessible by the filesystem tool. Users must configure this to the corresponding application working directory based on actual business scenarios. |

### 3. Supported Tools

This MCP server provides the following tools:

- `read_text_file`
- `read_media_file`
- `read_multiple_files`
- `list_directory`
- `directory_tree`
- `search_files`
- `get_file_info`
- `list_allowed_directories`


## Image Build

Execute the following command in the project root directory:

```bash
docker build -f src/filesystem/Dockerfile.supergateway -t essaigroup/deepxdr-filesystem-mcp-server:v0.3.0-alpha .
```

If the image already exists in the Docker registry, this step may be skipped.


## Secondary Development Features

### 1. File Reading Safety Limits

Security enhancements have been applied to the `read_text_file` tool for large files and excessively long lines:

- **Line Limit**: Returns a maximum of 2000 lines by default, adjustable via the `limit` parameter, preventing memory overflow or response timeouts when reading oversized files.
- **Single-Line Truncation**: Automatically truncates lines exceeding 2000 characters and appends ` ... [truncated]`, ensuring controllable output.
- **Full-Path Coverage**: The single-line truncation policy is uniformly applied to `head`, `tail`, and standard read modes.

### 2. Docker Deployment Support

A containerized deployment solution based on SuperGateway has been added, exposing the stdio-mode MCP server as a WebSocket service for easier integration in distributed environments:

- Added `Dockerfile.supergateway` for building a composite image containing SuperGateway.
- Added `.dockerignore` to optimize the image build context.
- Pre-installed `supergateway` within the image to provide MCP services externally via the WebSocket protocol, exposing port 8001 by default.

### 3. Project Structure Simplification

Unrelated MCP server modules from the original repository (`everything`, `fetch`, `git`, `memory`, `sequentialthinking`, `time`, etc.) and associated CI/CD workflows and release scripts have been removed. Only the core `filesystem` module is retained, reducing maintenance costs and build complexity.

## License

MIT
