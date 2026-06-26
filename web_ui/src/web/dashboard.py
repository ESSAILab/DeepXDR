from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import json
import asyncio
import time
import traceback
import logging
from datetime import datetime
from typing import List
import requests
import os
from dotenv import load_dotenv

# 加载当前运行环境中的 .env 文件；容器部署时仍优先使用注入的环境变量。
load_dotenv()

logger = logging.getLogger(__name__)

# HTTP API配置
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
logger.info("Using API_BASE_URL=%s", API_BASE_URL)

app = FastAPI(title="TTP Analysis Dashboard")

# 配置静态文件服务目录
static_dir = os.path.join(os.path.dirname(__file__), "static")

# 使用自定义静态文件处理替代FastAPI的StaticFiles
from fastapi.responses import Response
import mimetypes

@app.get("/static/{file_path:path}")
async def serve_static_file(file_path: str):
    """静态文件服务"""
    try:
        # 构建完整路径
        full_path = os.path.join(static_dir, file_path)

        # 基本安全检查
        if ".." in file_path or file_path.startswith("/"):
            raise HTTPException(status_code=403, detail="Invalid path")

        # 检查文件是否存在
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            raise HTTPException(status_code=404, detail="File not found")

        # 读取文件内容
        with open(full_path, 'rb') as f:
            content = f.read()

        # 根据文件扩展名设置正确的content-type
        content_type, _ = mimetypes.guess_type(full_path)
        if not content_type:
            content_type = 'application/octet-stream'

        return Response(content=content, media_type=content_type)

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Error serving static file {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

# 配置跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_backend_headers() -> dict:
    headers = {}
    # 实时读取环境变量，避免模块加载时读取不到Docker注入的环境变量
    api_key = os.getenv("BACKEND_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    return headers

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # 忽略已断开的客户端，后续断开流程会清理连接。
                pass

manager = ConnectionManager()

def ensure_timestamp(ttp: dict) -> None:
    """确保 ttp 对象有 timestamp 字段
    
    如果 ttp 中已有 timestamp 字段，不做任何处理。
    否则按优先级尝试使用 created_at、generated_at、updated_at 字段，
    如果都没有则使用当前时间作为兜底。
    """
    if 'timestamp' in ttp:
        return

    for field in ['created_at', 'generated_at', 'updated_at']:
        if field in ttp:
            ttp['timestamp'] = ttp[field]
            return

    ttp['timestamp'] = datetime.now().isoformat()

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """从模板文件返回仪表板 HTML。"""
    try:
        template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content.replace("API_BASE_URL_PLACEHOLDER", API_BASE_URL))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard template not found")

@app.get("/api/short-ttps")
async def get_short_ttp_list(q: str = None, page: int = 1, size: int = 10, hours: int = 24):
    try:
        # 构建API请求参数
        params = f"page={page}&size={size}"
        if hours:
            params += f"&hours={hours}"
            
        # 使用同步请求避免线程问题
        response = requests.get(f"{API_BASE_URL}/short-ttp?{params}", headers=get_backend_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        ttps = data.get('items', []) if isinstance(data, dict) and 'items' in data else data.get('data', []) if isinstance(data, dict) else data
        
        # 处理数据格式，保持与原有Redis版本一致
        processed_ttps = []
        for ttp in ttps:
            try:
                ttp_id = ttp.get('id', '')
                
                # 如果搜索查询提供，按TTP ID过滤
                if q and q.lower() not in str(ttp_id).lower():
                    continue

                # 确保时间戳字段存在
                ensure_timestamp(ttp)

                ttp['type'] = 'short'
                processed_ttps.append(ttp)
                
            except Exception as e:
                print(f"Error processing short TTP data: {e}")
                continue
        
        # 按时间排序
        processed_ttps.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # 搜索过滤后的总数
        filtered_total = len(processed_ttps)
        
        # 如果提供了搜索查询，总数应该是过滤后的数量
        if q:
            total = filtered_total
        else:
            # 如果没有搜索，使用原始总数
            total = data.get('total', filtered_total) if isinstance(data, dict) else filtered_total
        
        return {"items": processed_ttps, "total": total, "page": page, "size": size}
    except Exception as e:
        print(f"Error getting short TTPs from API: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return []

@app.get("/api/long-ttps")
async def get_long_ttp_list(q: str = None, page: int = 1, size: int = 10, hours: int = None):
    """获取Long TTP列表，支持分页、搜索和时间筛选"""
    try:
        # 构建API请求参数
        params = f"page={page}&size={size}"
        if hours:
            params += f"&hours={hours}"

        # 使用同步请求避免线程问题
        response = requests.get(f"{API_BASE_URL}/longttp?{params}", headers=get_backend_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        ttps = data.get('items', []) if isinstance(data, dict) and 'items' in data else data.get('data', []) if isinstance(data, dict) else data

        # 处理数据格式，保持与原有Redis版本一致
        processed_ttps = []
        for ttp in ttps:
            try:
                ttp_id = ttp.get('id', '') or ttp.get('generation_id', '')

                # 如果搜索查询提供，按TTP ID或内容过滤
                if q:
                    search_lower = q.lower()
                    ttp_str = str(ttp_id).lower()
                    content_str = str(ttp.get('content', '')).lower()
                    if search_lower not in ttp_str and search_lower not in content_str:
                        continue

                # 确保时间戳字段存在
                ensure_timestamp(ttp)

                # 处理ID字段
                if 'generation_id' in ttp and 'id' not in ttp:
                    ttp['id'] = ttp['generation_id']

                ttp['type'] = 'long'
                processed_ttps.append(ttp)

            except Exception as e:
                print(f"Error processing long TTP data: {e}")
                continue

        # 按时间排序
        processed_ttps.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

        # 搜索过滤后的总数
        filtered_total = len(processed_ttps)

        # 如果提供了搜索查询，总数应该是过滤后的数量
        if q:
            total = filtered_total
        else:
            # 如果没有搜索，使用原始总数
            total = data.get('total', filtered_total) if isinstance(data, dict) else filtered_total

        return {"items": processed_ttps, "total": total, "page": page, "size": size}
    except Exception as e:
        print(f"Error getting long TTPs from API: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return []

@app.get("/api/proxy/events/{event_id}")
async def proxy_event_detail(event_id: str):
    """代理访问事件详情API"""
    try:
        # 使用配置的API_BASE_URL访问事件详情
        api_url = f"{API_BASE_URL}/events/{event_id}"
        response = requests.get(api_url, headers=get_backend_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error proxying event detail from {API_BASE_URL}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch event detail: {str(e)}")

@app.post("/api/proxy/trigger-long-ttp/{short_ttp_id}")
async def proxy_trigger_long_ttp(short_ttp_id: str):
    """代理触发Long TTP生成"""
    try:
        api_url = f"{API_BASE_URL}/trigger-long-ttp/{short_ttp_id}"
        response = requests.post(api_url, headers=get_backend_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error triggering long TTP: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger long TTP: {str(e)}")

@app.post("/api/proxy/trigger-long-ttp-feedback/{short_ttp_id}")
async def proxy_trigger_long_ttp_feedback(short_ttp_id: str):
    """代理触发Long TTP人工参与反馈"""
    try:
        api_url = f"{API_BASE_URL}/trigger-long-ttp-feedback/{short_ttp_id}"
        logger.debug("Calling upstream API: %s", api_url)
        # 增加超时时间到60秒，因为人工参与启动可能需要较长时间
        response = requests.post(api_url, headers=get_backend_headers(), timeout=60)
        logger.debug("Upstream response status: %s", response.status_code)
        logger.debug("Upstream response body: %s", response.text[:500])
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as e:
        print(f"[ERROR] HTTP Error from upstream: {e}")
        print(f"[ERROR] Response content: {e.response.text if e.response else 'N/A'}")
        raise HTTPException(status_code=500, detail=f"Upstream API error: {e.response.status_code} - {e.response.text[:200]}")
    except requests.Timeout:
        print(f"[ERROR] Timeout calling upstream API after 60s")
        raise HTTPException(status_code=504, detail="Upstream API timeout, please try again later")
    except Exception as e:
        print(f"[ERROR] Error triggering long TTP feedback: {e}")
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger long TTP feedback: {str(e)}")

@app.get("/api/proxy/generation-status/{short_ttp_id}")
async def proxy_generation_status(short_ttp_id: str):
    """代理查询Long TTP生成状态"""
    try:
        api_url = f"{API_BASE_URL}/gen-longttp-status/{short_ttp_id}"
        response = requests.get(api_url, headers=get_backend_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error getting generation status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get generation status: {str(e)}")

@app.get("/api/proxy/feedback/{session_id}")
async def proxy_get_feedback(session_id: str):
    """查询人工参与反馈状态"""
    try:
        api_url = f"{API_BASE_URL}/feedback/{session_id}"
        response = requests.get(api_url, headers=get_backend_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error getting feedback status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get feedback status: {str(e)}")

@app.post("/api/proxy/feedback/{session_id}")
async def proxy_post_feedback(session_id: str, request: Request):
    """提交人工参与反馈"""
    try:
        # 获取请求体
        body = await request.json()
        api_url = f"{API_BASE_URL}/feedback/{session_id}"
        response = requests.post(api_url, json=body, headers=get_backend_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error posting feedback: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to post feedback: {str(e)}")

@app.delete("/api/proxy/longttp/{long_ttp_id}")
async def proxy_delete_long_ttp(long_ttp_id: str):
    """删除 Long TTP"""
    try:
        api_url = f"{API_BASE_URL}/longttp/{long_ttp_id}"
        response = requests.delete(api_url, headers=get_backend_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error deleting long TTP: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete long TTP: {str(e)}")

@app.get("/api/stats")
async def get_stats(hours: int = 24):
    try:
        # 使用同步方式获取统计数据，避免异步线程问题
        short_ttp_count = 0
        long_ttp_count = 0
        total_events = 0
        windows_yielded = 0
        
        # 构建API请求参数
        params = "size=1"
        if hours:
            params += f"&hours={hours}"
        
        print(f"[get_stats函数] 开始获取统计，hours参数: {hours}, 请求参数: {params}")
        
        try:
            # 获取短TTP数量
            short_response = requests.get(f"{API_BASE_URL}/short-ttp?{params}", headers=get_backend_headers(), timeout=10)
            if short_response.status_code == 200:
                short_data = short_response.json()
                if isinstance(short_data, dict) and 'total' in short_data:
                    short_ttp_count = short_data['total']
                elif isinstance(short_data, dict) and 'total_items' in short_data:
                    short_ttp_count = short_data['total_items']
        except Exception as e:
            print(f"Error getting short TTP count: {e}")
        
        try:
            # 获取长TTP数量 - 复用 params 参数
            long_response = requests.get(f"{API_BASE_URL}/longttp?{params}", headers=get_backend_headers(), timeout=10)
            if long_response.status_code == 200:
                long_data = long_response.json()
                # 支持 {total: n} 或 {items: [...]} 格式
                if isinstance(long_data, dict):
                    if 'total' in long_data:
                        long_ttp_count = long_data['total']
                    elif 'items' in long_data and isinstance(long_data['items'], list):
                        long_ttp_count = len(long_data['items'])
                elif isinstance(long_data, list):
                    long_ttp_count = len(long_data)
        except Exception as e:
            print(f"Error getting long TTP count: {e}")
        
        try:
            # 获取事件数量
            events_response = requests.get(f"{API_BASE_URL}/events?{params}", headers=get_backend_headers(), timeout=10)
            if events_response.status_code == 200:
                events_data = events_response.json()
                if isinstance(events_data, dict) and 'total' in events_data:
                    total_events = events_data['total']
                elif isinstance(events_data, dict) and 'total_events' in events_data:
                    total_events = events_data['total_events']
        except Exception as e:
            print(f"Error getting events count: {e}")
        
        try:
            # 获取窗口统计
            windows_response = requests.get(f"{API_BASE_URL}/stats?{params}", headers=get_backend_headers(), timeout=10)
            if windows_response.status_code == 200:
                stats_data = windows_response.json()
                if isinstance(stats_data, dict) and 'window_stats' in stats_data:
                    windows_yielded = stats_data['window_stats'].get('closed_windows', 0)
        except Exception as e:
            print(f"Error getting window stats: {e}")
        
        result = {
            "short_ttp_count": short_ttp_count,
            "long_ttp_count": long_ttp_count,
            "total_events_processed": total_events,
            "windows_yielded": windows_yielded
        }
        print(f"[get_stats函数] 返回统计结果: {result}")
        return result
    except Exception as e:
        print(f"Error getting stats from API: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return {"short_ttp_count": 0, "long_ttp_count": 0, "total_events_processed": 0, "windows_yielded": 0}

@app.get("/api/ttp/{ttp_id}")
async def get_ttp_details(ttp_id: str):
    try:
        # 使用同步请求避免线程问题
        # 先尝试获取短TTP
        try:
            response = requests.get(f"{API_BASE_URL}/short-ttp/{ttp_id}", headers=get_backend_headers(), timeout=30)
            response.raise_for_status()
            ttp_data = response.json()
            ttp = ttp_data.get('items', ttp_data) if isinstance(ttp_data, dict) and 'items' in ttp_data else ttp_data.get('data', ttp_data) if isinstance(ttp_data, dict) else ttp_data
            ttp['type'] = 'short'
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                # 尝试获取长TTP
                response = requests.get(f"{API_BASE_URL}/longttp/{ttp_id}", headers=get_backend_headers(), timeout=30)
                response.raise_for_status()
                ttp_data = response.json()
                ttp = ttp_data.get('items', ttp_data) if isinstance(ttp_data, dict) and 'items' in ttp_data else ttp_data.get('data', ttp_data) if isinstance(ttp_data, dict) else ttp_data
                ttp['type'] = 'long'
            else:
                raise
            
        ttp['id'] = ttp_id

        # 确保时间戳字段存在
        ensure_timestamp(ttp)

        if ttp.get('type') == "long":
            # 确保相关字段存在
            short_ttps = ttp.get('short_ttps', [])
            if isinstance(short_ttps, str):
                try:
                    short_ttps = json.loads(short_ttps)
                except:
                    short_ttps = []
            ttp['short_ttps'] = short_ttps

            # 确保事件有时间戳
            if 'events' in ttp and isinstance(ttp['events'], list):
                for event in ttp['events']:
                    ensure_timestamp(event)

        return ttp
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="TTP not found")
        else:
            raise HTTPException(status_code=500, detail="Error fetching TTP details")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # 存储当前连接的筛选参数
    filter_params = {"hours": 24}  # 默认24小时
    last_stats_update = time.time()
    connection_id = f"{websocket.client.host}_{int(time.time() * 1000)}"  # 生成唯一连接ID
    print(f"[WebSocket连接] 新连接建立: {connection_id}")
    
    try:
        while True:
            # 检查是否有新消息（非阻塞）
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                if message.get("type") == "set_filter":
                    # 更新筛选参数
                    hours = message.get("hours")
                    print(f"[WebSocket筛选参数] 连接 {connection_id} 收到set_filter消息: hours={hours}, customHours={message.get('customHours')}, customUnit={message.get('customUnit')}")
                    if hours == "custom":
                        custom_hours = message.get("customHours", 24)
                        custom_unit = message.get("customUnit", "hours")
                        filter_params["hours"] = custom_hours if custom_unit == "hours" else custom_hours * 24
                    elif hours and hours != "24":
                        filter_params["hours"] = int(hours)
                    else:
                        # 当hours为"24"或空时，使用24小时
                        filter_params["hours"] = 24
                    
                    print(f"[WebSocket筛选参数] 连接 {connection_id} 更新后的filter_params: {filter_params}")
                    
                    # 当筛选参数改变时，立即发送stats更新
                    if websocket.client_state.name == "CONNECTED":
                        stats_hours = filter_params["hours"] if filter_params["hours"] is not None else 24
                        print(f"[WebSocket筛选参数] 连接 {connection_id} 立即获取统计，hours参数: {stats_hours}")
                        stats = await get_stats(hours=stats_hours)
                        print(f"[WebSocket筛选参数] 连接 {connection_id} 获取到的统计数据: {stats}")
                        await websocket.send_json({
                            "type": "stats_update",
                            "data": stats
                        })
                        print(f"[WebSocket筛选参数] 连接 {connection_id} 统计数据已发送")
                        last_stats_update = time.time()
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass
            
            # 每8秒检查一次是否需要更新stats（只有当没有收到新消息时）
            current_time = time.time()
            if current_time - last_stats_update >= 8 and websocket.client_state.name == "CONNECTED":
                # 确保filter_params["hours"]有有效值，默认为24
                stats_hours = filter_params["hours"] if filter_params["hours"] is not None else 24
                print(f"[WebSocket定时统计] 连接 {connection_id} 开始获取统计，hours参数: {stats_hours}, filter_params: {filter_params}")
                stats = await get_stats(hours=stats_hours)
                print(f"[WebSocket定时统计] 连接 {connection_id} 获取到的统计数据: {stats}")
                await websocket.send_json({
                    "type": "stats_update",
                    "data": stats
                })
                print(f"[WebSocket定时统计] 连接 {connection_id} 统计数据已发送，下次更新将在8秒后")
                last_stats_update = current_time
            
            await asyncio.sleep(0.5)  # 减少检查频率，提高响应性
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print(f"[WebSocket连接] 连接断开: {connection_id}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=30003)