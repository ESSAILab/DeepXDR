# Filesystem MCP 二次开发说明

[English](README_EN.md) | 中文

## 项目说明

本项目基于 [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) 开源仓库中的 `src/filesystem` 模块进行二次开发。

**原始参考项目地址**：https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem  
**原始项目文档**：[README_origin.md](README_origin.md)




## 镜像启动
该服务部署在app侧所在服务器上，为ai-agent威胁分析智能体提供文件操作工具。

### 1. Docker Compose 配置示例
docker-compose中该镜像配置示例展示如下 ：

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

### 2.配置参数说明

| 参数 | 说明 |
|------|------|
| `volumes` | 将共享存储卷挂载至容器内的应用工作空间，作为 filesystem 工具可访问的目标工作目录。用户须根据实际业务场景配置为对应的应用工作目录。 |

## 3.工具支持
该mcp服务支持以下工具：  
read_text_file  
read_media_file  
read_multiple_files  
list_directory  
directory_tree  
search_files  
get_file_info  
list_allowed_directories  


## 镜像构建

在项目根目录执行以下命令：

```bash
docker build -f src/filesystem/Dockerfile.supergateway -t essaigroup/deepxdr-filesystem-mcp-server:v0.3.0-alpha .
```
若docker-hub中已有该镜像，则可跳过此步骤。


## 二次开发功能说明

### 1. 文件读取安全限制

针对大文件及超长行场景，对 `read_text_file` 工具进行了安全性增强：

- **行数限制**：默认最多返回 2000 行，可通过 `limit` 参数动态调整，防止因读取超大文件导致内存溢出或响应超时。
- **单行截断**：单行内容超过 2000 字符时自动截断，并追加 ` ... [truncated]` 标记，确保输出可控。
- **全路径覆盖**：`head`、`tail` 及普通读取模式均统一应用单行截断策略。

### 2. Docker 部署支持

新增基于 SuperGateway 的容器化部署方案，将 stdio 模式的 MCP 服务器暴露为 WebSocket 服务，便于在分布式环境中集成：

- 新增 `Dockerfile.supergateway`，构建包含 SuperGateway 的复合镜像。
- 新增 `.dockerignore` 文件，优化镜像构建上下文。
- 在镜像内预装 `supergateway`，通过 WebSocket 协议对外提供 MCP 服务，默认暴露 8001 端口。

### 3. 项目结构精简

移除原始仓库中与本项目无关的其他 MCP 服务器模块（`everything`、`fetch`、`git`、`memory`、`sequentialthinking`、`time` 等）及相关 CI/CD 工作流、发布脚本，仅保留 `filesystem` 核心模块，降低维护成本与构建复杂度。

## 许可证

MIT
