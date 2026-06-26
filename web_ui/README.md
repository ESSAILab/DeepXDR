# DeepXDR TTP分析仪表板

TTP（Tactics, Techniques, and Procedures）分析仪表板前端服务，用于实时展示安全告警和威胁情报。

## 功能概述

- **实时告警展示**: Short TTP（短期攻击告警）列表展示
- **威胁情报**: Long TTP（高级持续性威胁）分析展示
- **数据可视化**: 攻击阶段分布、TTP趋势统计
- **搜索筛选**: 支持TTP ID搜索和时间范围筛选
- **实时更新**: WebSocket推送统计数据更新
- **人工参与**: 支持人工介入调查流程

## 快速开始

### 1. 环境准备

```bash
# 安装依赖
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 启动Web仪表板
python run_dashboard.py
```

### 3. 访问仪表板

打开浏览器访问: `http://localhost:30003`

## 配置说明

### 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `API_BASE_URL` | 后端API地址 | http://localhost:8000 |
| `BACKEND_API_KEY` | API认证密钥 | DeepXDR |
| `HOST` | 监听地址 | 0.0.0.0 |
| `PORT` | 监听端口 | 30003 |

### 配置示例

编辑 `.env` 文件配置后端API地址：
```bash
API_BASE_URL=http://your-backend-api:8000
BACKEND_API_KEY=your-api-key
```

## API接口

### 首页
```
GET /
```
返回仪表板主页面（HTML）

### Short TTP列表
```
GET /api/short-ttps?q=&page=1&size=10&hours=24
```
| 参数 | 类型 | 说明 |
|------|------|------|
| q | string | 搜索关键词（按 TTP ID 模糊匹配，可选） |
| page | int | 页码，默认1 |
| size | int | 每页数量，默认10 |
| hours | int | 时间范围（小时），默认24 |

### Long TTP列表
```
GET /api/long-ttps?q=&page=1&size=10&hours=24
```
| 参数 | 类型 | 说明 |
|------|------|------|
| q | string | 搜索关键词（按 TTP ID 或内容模糊匹配，可选） |
| page | int | 页码，默认1 |
| size | int | 每页数量，默认10 |
| hours | int | 时间范围（小时），默认24 |

### TTP详情
```
GET /api/ttp/{ttp_id}
```
自动识别 Short/Long TTP 并返回详情

### 统计数据
```
GET /api/stats?hours=24
```
| 参数 | 类型 | 说明 |
|------|------|------|
| hours | int | 时间范围（小时），默认24 |

返回：
```json
{
  "short_ttp_count": 100,
  "long_ttp_count": 10,
  "total_events_processed": 500,
  "windows_yielded": 50
}
```

### 触发Long TTP生成
```
POST /api/proxy/trigger-long-ttp/{short_ttp_id}
```

### 触发人工参与反馈
```
POST /api/proxy/trigger-long-ttp-feedback/{short_ttp_id}
```

### 查询生成状态
```
GET /api/proxy/generation-status/{short_ttp_id}
```

### 查询反馈状态
```
GET /api/proxy/feedback/{session_id}
```

### 提交反馈
```
POST /api/proxy/feedback/{session_id}
```
请求体：
```json
{
  "inputText": "反馈内容"
}
```

### 删除Long TTP
```
DELETE /api/proxy/longttp/{long_ttp_id}
```

### 获取事件详情
```
GET /api/proxy/events/{event_id}
```

### WebSocket实时推送
```
WS /ws
```
支持的消息类型：
- `set_filter`: 设置时间筛选参数
- `stats_update`: 统计数据更新推送

## Docker部署

### 构建镜像

```bash
# 基础构建（本地标签）
docker build -t deepxdr-web-ui .

# 构建并指定完整仓库标签（推送前必须）
docker build -t your-username/deepxdr-web-ui:v1.0.0 .
```

### 运行容器

```bash
# 基础运行
docker run -p 30003:30003 \
  -e API_BASE_URL=http://backend:8000 \
  -e BACKEND_API_KEY=your-api-key \
  deepxdr-web-ui

# 后台运行（生产环境推荐）
docker run -d \
  --name web-ui \
  -p 30003:30003 \
  -e API_BASE_URL=http://backend:8000 \
  -e BACKEND_API_KEY=your-api-key \
  --restart always \
  deepxdr-web-ui
```

### 推送镜像到仓库

**Docker Hub**
```bash
# 登录（如未登录）
docker login -u your-username

# 推送
docker push your-username/deepxdr-web-ui:v1.0.0
```

**私有仓库（示例）**
```bash
# 登录私有仓库（如需要）
docker login your-registry:5000

# 推送
docker push your-registry:5000/project/deepxdr-web-ui:v1.0
```

## 开发指南

### 项目结构

```
web-ui/
├── run_dashboard.py      # 启动脚本
├── requirements.txt      # Python依赖
├── Dockerfile            # Docker构建配置
├── .env.example          # 环境变量示例
└── src/
    └── web/
        ├── dashboard.py  # FastAPI应用主文件
        ├── static/       # 静态资源(CSS/JS/图片)
        └── templates/    # HTML模板
            └── dashboard.html  # 主页面
```

### 技术栈

- **后端框架**: FastAPI
- **前端框架**: Alpine.js
- **样式**: Tailwind CSS
- **实时通信**: WebSocket
- **图标**: Font Awesome


## 功能特性

### 搜索与筛选
- 支持TTP ID搜索
- 支持时间范围筛选（1小时/24小时/3天/7天）
- 时间范围筛选对Short TTP和Long TTP都生效

### 实时更新
- WebSocket连接实时推送统计数据
- 支持多客户端同时连接

### 人工参与
- 支持人工介入调查流程
- 实时状态同步显示

## 许可证

本项目为防御性安全工具，仅用于合法的安全监控和分析。
