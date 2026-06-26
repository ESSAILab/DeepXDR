# DeepXDR TTP Analysis Dashboard

TTP (Tactics, Techniques, and Procedures) Analysis Dashboard frontend service for real-time display of security alerts and threat intelligence.

## Features

- **Real-time Alert Display**: Short TTP (short-term attack alerts) list display
- **Threat Intelligence**: Long TTP (Advanced Persistent Threat) analysis display
- **Data Visualization**: Attack phase distribution, TTP trend statistics
- **Search & Filter**: Support TTP ID search and time range filtering
- **Real-time Updates**: WebSocket push for statistics updates
- **Human-in-the-Loop**: Support manual intervention in investigation process

## Quick Start

### 1. Environment Setup

```bash
# Install dependencies
pip install -r requirements.txt
```

### 2. Start Service

```bash
# Start Web dashboard
python run_dashboard.py
```

### 3. Access Dashboard

Open browser and visit: `http://localhost:30003`

## Configuration

### Environment Variables

| Variable | Description | Default Value |
|------|------|--------|
| `API_BASE_URL` | Backend API address | http://localhost:8000 |
| `BACKEND_API_KEY` | API authentication key | DeepXDR |
| `HOST` | Listen address | 0.0.0.0 |
| `PORT` | Listen port | 30003 |

### Configuration Example

Edit `.env` file to configure backend API address:
```bash
API_BASE_URL=http://your-backend-api:8000
BACKEND_API_KEY=your-api-key
```

## API Endpoints

### Home Page
```
GET /
```
Returns dashboard main page (HTML)

### Short TTP List
```
GET /api/short-ttps?q=&page=1&size=10&hours=24
```
| Parameter | Type | Description |
|------|------|------|
| q | string | Search keyword (fuzzy match by TTP ID, optional) |
| page | int | Page number, default 1 |
| size | int | Items per page, default 10 |
| hours | int | Time range (hours), default 24 |

### Long TTP List
```
GET /api/long-ttps?q=&page=1&size=10&hours=24
```
| Parameter | Type | Description |
|------|------|------|
| q | string | Search keyword (fuzzy match by TTP ID or content, optional) |
| page | int | Page number, default 1 |
| size | int | Items per page, default 10 |
| hours | int | Time range (hours), default 24 |

### TTP Details
```
GET /api/ttp/{ttp_id}
```
Automatically identifies Short/Long TTP and returns details

### Statistics
```
GET /api/stats?hours=24
```
| Parameter | Type | Description |
|------|------|------|
| hours | int | Time range (hours), default 24 |

Returns:
```json
{
  "short_ttp_count": 100,
  "long_ttp_count": 10,
  "total_events_processed": 500,
  "windows_yielded": 50
}
```

### Trigger Long TTP Generation
```
POST /api/proxy/trigger-long-ttp/{short_ttp_id}
```

### Trigger Human-in-the-Loop Feedback
```
POST /api/proxy/trigger-long-ttp-feedback/{short_ttp_id}
```

### Query Generation Status
```
GET /api/proxy/generation-status/{short_ttp_id}
```

### Query Feedback Status
```
GET /api/proxy/feedback/{session_id}
```

### Submit Feedback
```
POST /api/proxy/feedback/{session_id}
```
Request body:
```json
{
  "inputText": "Feedback content"
}
```

### Delete Long TTP
```
DELETE /api/proxy/longttp/{long_ttp_id}
```

### Get Event Details
```
GET /api/proxy/events/{event_id}
```

### WebSocket Real-time Push
```
WS /ws
```
Supported message types:
- `set_filter`: Set time filter parameters
- `stats_update`: Statistics update push

## Docker Deployment

### Build Image

```bash
# Basic build (local tag)
docker build -t deepxdr-web-ui .

# Build with full registry tag (required before push)
docker build -t your-username/deepxdr-web-ui:v1.0.0 .
```

### Run Container

```bash
# Basic run
docker run -p 30003:30003 \
  -e API_BASE_URL=http://backend:8000 \
  -e BACKEND_API_KEY=your-api-key \
  deepxdr-web-ui

# Background run (recommended for production)
docker run -d \
  --name web-ui \
  -p 30003:30003 \
  -e API_BASE_URL=http://backend:8000 \
  -e BACKEND_API_KEY=your-api-key \
  --restart always \
  deepxdr-web-ui
```

### Push Image to Registry

**Docker Hub**
```bash
# Login (if not already logged in)
docker login -u your-username

# Push
docker push your-username/deepxdr-web-ui:v1.0.0
```

**Private Registry (example)**
```bash
# Login to private registry (if needed)
docker login your-registry:5000

# Push
docker push your-registry:5000/project/deepxdr-web-ui:v1.0
```

## Development Guide

### Project Structure

```
web-ui/
├── run_dashboard.py      # Startup script
├── requirements.txt      # Python dependencies
├── Dockerfile            # Docker build configuration
├── .env.example          # Environment variables example
└── src/
    └── web/
        ├── dashboard.py  # FastAPI main application
        ├── static/       # Static resources (CSS/JS/images)
        └── templates/    # HTML templates
            └── dashboard.html  # Main page
```

### Tech Stack

- **Backend Framework**: FastAPI
- **Frontend Framework**: Alpine.js
- **Styling**: Tailwind CSS
- **Real-time Communication**: WebSocket
- **Icons**: Font Awesome

## Feature Details

### Search & Filter
- Support TTP ID search
- Support time range filtering (1 hour/24 hours/3 days/7 days)
- Time range filter applies to both Short TTP and Long TTP

### Real-time Updates
- WebSocket connection for real-time statistics push
- Support multiple client simultaneous connections

### Human-in-the-Loop
- Support manual intervention in investigation process
- Real-time status synchronization display

## License

This project is a defensive security tool, intended for legitimate security monitoring and analysis only.