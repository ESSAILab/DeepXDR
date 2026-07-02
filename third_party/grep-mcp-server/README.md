# Grep MCP 二次开发说明

[English](README_EN.md) | 中文

## 原始项目

本项目基于开源项目 [erniebrodeur/mcp-grep](https://github.com/erniebrodeur/mcp-grep) 进行二次开发。

原始项目的完整功能说明请参阅 [README_origin.md](README_origin.md)。


---

## 镜像启动
该服务部署在app侧所在服务器上，为agent威胁分析提供文件内容搜索工具。


docker-compose中该镜像配置示例展示如下 ：

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

**配置说明：**

- `environment.MCP_GREP_MAX_RESULTS`: 设置单次搜索最大返回结果条数
- `volumes`: 将共享存储卷挂载至容器内应用工作目录，供 grep 工具访问目标文件，用户需将其配置为应用工作目录

---

## 镜像构建

```bash
# 构建镜像
docker build -f Dockerfile.source -t essaigroup/deepxdr-grep-mcp-server:v0.3.0-alpha .

```
若docker-hub中已有该镜像，则可跳过此步骤。

---

---

## 主要功能

MCP-Grep 通过模型上下文协议（MCP）将系统 grep 功能暴露为标准化的服务接口，核心能力包括：

- **文件内容搜索**：基于系统 grep 二进制文件，支持正则表达式在指定文件或目录中搜索匹配内容
- **常用搜索选项**：
  - 忽略大小写匹配（`-i`）
  - 显示上下文行（匹配前后 N 行）
  - 固定字符串匹配（非正则模式）
  - 递归目录搜索
- **自然语言提示理解**：支持以自然语言描述搜索需求，降低 LLM 调用门槛
- **结构化结果返回**：搜索结果以 JSON 格式返回，包含文件名、行号、匹配内容及上下文

---

## 二次开发功能说明

### 1. 可配置的最大返回结果数

在原始实现中，`grep` 搜索结果的最大返回数量被硬编码为 `50`。二次开发将该限制值抽取为可通过环境变量 `MCP_GREP_MAX_RESULTS` 动态配置，以便根据实际部署场景灵活调整。

- **环境变量**: `MCP_GREP_MAX_RESULTS`
- **默认值**: `50`
- **说明**: 当匹配结果数量超过该阈值时，系统将自动截断并返回前 N 条结果，同时附加提示信息说明实际命中总数。

### 2. 通信协议适配

原始项目以 stdio 方式运行 MCP 服务器。二次开发引入 [supergateway](https://github.com/supergateway) 作为协议转换层，将 stdio 接口暴露为 WebSocket 协议，便于在容器化及微服务架构中集成。

- **输出协议**: `ws` (WebSocket)
- **消息路径**: `/message`
- **监听端口**: `8000`

### 3. Docker 镜像构建

新增 `Dockerfile.source` 构建文件，镜像基于 `python:3.11-slim`，并预装 Node.js 运行环境以支持 supergateway 的启动。

---

## 许可证

MIT
