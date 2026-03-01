# FinSight Docker 部署全记录

> 个人笔记，记录从 0 到跑通的完整过程，包括踩过的所有坑。
> 环境：腾讯云轻量应用服务器（广州），Ubuntu 22.04，Docker 26.1.3

---

## 一、部署文件清单

部署前需要准备的文件，全部在仓库根目录或对应位置：

```
FinSight/
├── Dockerfile                  # 后端镜像（Python 3.11 + ML 依赖）
├── docker-compose.yml          # 一键启动全栈
├── .dockerignore               # 排除不需要打包的文件
├── .env.server.example         # 服务器配置模板（git 追踪，无真实 key）
└── frontend/
    ├── Dockerfile              # 前端镜像（Node 20 多阶段构建 → nginx）
    ├── nginx.conf              # nginx 配置（SSE 支持、API 代理、SPA fallback）
    └── .dockerignore           # 前端构建排除项
```

`.env.server` 只在服务器上存在，永远不进 git。

---

## 二、各文件说明

### `Dockerfile`（后端）

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# 关键：先装 CPU-only torch，避免拉 3 GB CUDA 包
# BGE_M3_DEVICE=cpu，服务器不需要 GPU
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/langgraph data/memory backend/data logs
ENV HF_HOME=/app/.cache/huggingface
ENV TORCH_HOME=/app/.cache/torch
RUN mkdir -p /app/.cache/huggingface /app/.cache/torch

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-keep-alive", "300"]
```

**为什么要先装 CPU-only torch？**
默认 pip 会在 Linux 上安装带 CUDA 的 torch（915 MB）+ 一堆 nvidia 包（另外 2+ GB），
服务器磁盘 40G 只剩 10G 时会直接报 `No space left on device`。
CPU-only 版只有 ~300 MB。

---

### `frontend/Dockerfile`（前端多阶段构建）

```dockerfile
FROM node:20-alpine AS builder

WORKDIR /app

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine AS runner

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
```

**关键点**：
- `VITE_API_BASE_URL` 是 Vite 构建时变量，bake 进 JS bundle，运行时无法修改
- health check 必须用 `127.0.0.1` 而不是 `localhost`（见坑 #2）

---

### `frontend/nginx.conf`

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # API 代理：/api/* /chat/* /health /ws/* → 后端
    location ~ ^/(api|chat|health|ws)(/|$) {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # SSE（流式聊天）关键配置
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;

        # 报告生成最长 10 分钟
        proxy_read_timeout  600s;
        proxy_send_timeout  600s;
        proxy_connect_timeout 10s;
    }

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 静态资源缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    gzip on;
    gzip_types text/plain text/css application/json application/javascript
               text/xml application/xml text/javascript;
}
```

---

### `docker-compose.yml`（核心）

```yaml
version: "3.9"

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: finsight-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB:       ${POSTGRES_DB:-finsight}
      POSTGRES_USER:     ${POSTGRES_USER:-finsight}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-finsight_pass}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-finsight}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - finsight-net

  backend:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: finsight-backend
    restart: unless-stopped
    env_file:
      - .env.server
    environment:
      # 覆盖 RAG 配置：使用 postgres pgvector
      RAG_V2_BACKEND: postgres
      RAG_V2_ALLOW_MEMORY_FALLBACK: "true"
      RAG_V2_POSTGRES_DSN: postgresql+psycopg://${POSTGRES_USER:-finsight}:${POSTGRES_PASSWORD:-finsight_pass}@postgres:5432/${POSTGRES_DB:-finsight}
      LANGGRAPH_CHECKPOINT_POSTGRES_DSN: postgresql+psycopg://${POSTGRES_USER:-finsight}:${POSTGRES_PASSWORD:-finsight_pass}@postgres:5432/${POSTGRES_DB:-finsight}
    volumes:
      - backend_data:/app/data
      - backend_logs:/app/logs
      - model_cache:/app/.cache     # BGE-M3 模型缓存，避免每次重启重新下载
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 60s
    networks:
      - finsight-net

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        # 设置为服务器公网 IP，让 API 请求走 nginx 代理
        # 空字符串会触发 runtime.ts 里的 fallback → http://127.0.0.1:8000
        VITE_API_BASE_URL: ${VITE_API_BASE_URL:-http://175.178.159.112}
    container_name: finsight-frontend
    restart: unless-stopped
    ports:
      - "80:80"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1/ || exit 1"]
      interval: 10s
      timeout: 3s
      retries: 3
    depends_on:
      backend:
        condition: service_healthy
    networks:
      - finsight-net

volumes:
  postgres_data:
    name: finsight_postgres_data
  backend_data:
    name: finsight_backend_data
  backend_logs:
    name: finsight_backend_logs
  model_cache:
    name: finsight_model_cache

networks:
  finsight-net:
    name: finsight-net
    driver: bridge
```

---

## 三、服务器部署步骤

### 前提条件

- Ubuntu 22.04
- Docker 已安装（`docker --version` 确认）
- 腾讯云控制台 → 轻量服务器 → 防火墙 → 开放 **80** 端口（HTTP）

### Step 1：上传项目

**方法 A：git clone（国内服务器可能被 GFW 截断）**
```bash
git clone https://github.com/kkkano/FinSight.git
```

**方法 B：本地打 tar 包 SFTP 上传（更可靠）**
```bash
# 本地（Windows/Mac）
cd FinSight
tar --exclude='.git' --exclude='node_modules' --exclude='.venv' \
    --exclude='__pycache__' --exclude='.cache' --exclude='data' \
    --exclude='logs' -czf /tmp/finsight.tar.gz .

# SCP 上传
scp /tmp/finsight.tar.gz ubuntu@175.178.159.112:~

# 服务器上解压
mkdir ~/FinSight && tar -xzf ~/finsight.tar.gz -C ~/FinSight
```

### Step 2：创建 `.env.server`

```bash
cp ~/FinSight/.env.server.example ~/FinSight/.env.server
vim ~/FinSight/.env.server
```

关键配置项（其余照着 example 填）：
```bash
POSTGRES_PASSWORD=改个强密码
GEMINI_PROXY_API_KEY=你的 key
VITE_API_BASE_URL=http://你的服务器IP   # 前端 API 基地址
```

### Step 3：一键启动

```bash
cd ~/FinSight
docker compose --env-file .env.server up -d --build
```

**第一次构建时间：**
- 后端（Python + ML deps）：15-25 分钟（主要是下 torch + FlagEmbedding）
- 前端（npm ci + vite build）：3-5 分钟

### Step 4：验证

```bash
# 查看容器状态
docker ps

# 应该全是 healthy：
# finsight-frontend   Up X minutes (healthy)   0.0.0.0:80->80/tcp
# finsight-backend    Up X minutes (healthy)   0.0.0.0:8000->8000/tcp
# finsight-postgres   Up X minutes (healthy)   0.0.0.0:5432->5432/tcp

# 测试后端健康
curl http://localhost:8000/health

# 测试前端
curl -o /dev/null -w "%{http_code}" http://localhost/
```

### Step 5：开放云防火墙

腾讯云控制台 → 轻量应用服务器 → 选实例 → 防火墙 → 添加规则：

| 端口 | 协议 | 来源 | 说明 |
|------|------|------|------|
| 80   | TCP  | 0.0.0.0/0 | 前端 HTTP |

> 5432 不要对外开放！用 SSH 隧道访问数据库：
> `ssh -L 5432:localhost:5432 ubuntu@175.178.159.112`

---

## 四、踩坑记录

### 坑 #1：磁盘爆满（`No space left on device`）

**现象**：pip install 安装到 torch 时报错
```
ERROR: Could not install packages due to an OSError: [Errno 28] No space left on device
```

**原因**：torch 默认装 CUDA 版本，915 MB whl + nvidia_cublas(594MB) + nvidia_cudnn(706MB) + 更多 CUDA 包 ≈ 3-4 GB。服务器磁盘只剩 10G，Docker build 临时层占满。

**解决**：
1. 清理 Docker build 缓存（可能释放 10+ GB）：
   ```bash
   docker builder prune -f
   ```
2. 修改 Dockerfile，先装 CPU-only torch：
   ```dockerfile
   RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
   RUN pip install --no-cache-dir -r requirements.txt
   ```

---

### 坑 #2：alpine nginx healthcheck 用 localhost 失败

**现象**：前端容器 `(unhealthy)`，但 `curl http://localhost:80` 从宿主机返回 200

**原因**：alpine busybox `wget` 把 `localhost` 解析到 `::1`（IPv6），但 nginx 默认只 `listen 80`（IPv4）。IPv6 连接拒绝。

**验证**：
```bash
docker exec finsight-frontend wget -qO- http://localhost/    # 失败
docker exec finsight-frontend wget -qO- http://127.0.0.1/   # 成功
```

**解决**：把 health check 里的 `localhost` 改成 `127.0.0.1`：
```dockerfile
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ || exit 1
```
或在 docker-compose.yml 的 frontend service 里覆盖：
```yaml
healthcheck:
  test: ["CMD-SHELL", "wget -qO- http://127.0.0.1/ || exit 1"]
```

---

### 坑 #3：asyncpg greenlet 错误

**现象**：后端健康检查返回 RAG 降级：
```json
{"rag": {"status": "error", "error": "greenlet_spawn has not been called; can't call await_only() here"}}
```

**原因**：`RAG_V2_POSTGRES_DSN=postgresql+asyncpg://...` 使用 asyncpg 驱动，SQLAlchemy async 初始化在 FastAPI startup 阶段的 greenlet 上下文有冲突。

**解决**：改用 psycopg3（同步/异步都支持，且已在 requirements.txt 里）：
```
postgresql+asyncpg://...  →  postgresql+psycopg://...
```

---

### 坑 #4：VITE_API_BASE_URL 空字符串触发 fallback

**现象**：前端加载后，所有 API 请求打到 `127.0.0.1:8000`（用户自己的电脑）

**原因**：`frontend/src/config/runtime.ts` 里的逻辑：
```typescript
const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';
const raw = import.meta.env.VITE_API_BASE_URL?.trim();
if (!raw) return DEFAULT_API_BASE_URL;  // 空字符串 → fallback！
```

docker-compose.yml 传了 `VITE_API_BASE_URL: ""` → 空字符串 → fallback 到本地

**解决**：必须传服务器公网 IP：
```yaml
args:
  VITE_API_BASE_URL: "http://175.178.159.112"
```
然后重新构建前端镜像（`docker compose build frontend`）再重启容器。

---

### 坑 #5：GFW 截断 git clone

**现象**：
```
error: RPC failed; curl 56 GnuTLS recv error (-54): Error in the pull function.
fatal: early EOF
```

**原因**：腾讯云广州服务器直连 GitHub 不稳定，大仓库 clone 被截断。

**解决**：本地打 tar.gz，用 SFTP 上传（8.4 MB，0.6 秒传完）。

---

## 五、日常运维

### 查看日志
```bash
docker logs finsight-backend -f --tail 50
docker logs finsight-frontend -f --tail 20
```

### 重启服务
```bash
cd ~/FinSight
docker compose --env-file .env.server restart backend
```

### 更新代码（本地修改后重新部署）
```bash
# 本地打包上传
scp /tmp/finsight_new.tar.gz ubuntu@175.178.159.112:~

# 服务器上解压覆盖
tar -xzf ~/finsight_new.tar.gz -C ~/FinSight --overwrite

# 重建（--build 只会重建有变化的层）
cd ~/FinSight
docker compose --env-file .env.server up -d --build
```

### 重建单个服务
```bash
# 只重建前端（快，约 3-5 分钟）
docker compose --env-file .env.server build frontend
docker compose --env-file .env.server up -d --no-build frontend

# 只重建后端（慢，约 15 分钟，因为有 torch）
docker compose --env-file .env.server build backend
docker compose --env-file .env.server up -d --no-build backend
```

### 查看资源占用
```bash
docker stats --no-stream
df -h /
```

### 连接数据库（SSH 隧道）
```bash
# 本地机器上运行
ssh -L 5432:localhost:5432 ubuntu@175.178.159.112

# 另开终端，用任意 PG 客户端连 localhost:5432
# 用户名：finsight，密码：finsight_pass，数据库：finsight
```

---

## 六、最终架构图

```
外网用户
    │
    ▼ http://175.178.159.112:80
┌─────────────────────────────────────┐
│  finsight-frontend (nginx:alpine)   │
│  - 静态 SPA (React + Vite)          │
│  - /api/* /chat/* /health → proxy   │
│  - /ws/* → proxy (WebSocket)        │
└────────────────┬────────────────────┘
                 │ Docker 内网 backend:8000
                 ▼
┌─────────────────────────────────────┐
│  finsight-backend (Python 3.11)     │
│  - FastAPI + uvicorn               │
│  - BGE-M3 嵌入（CPU）              │
│  - LangGraph workflow               │
│  - RAG: pgvector hybrid search      │
└────────────────┬────────────────────┘
                 │ Docker 内网 postgres:5432
                 ▼
┌─────────────────────────────────────┐
│  finsight-postgres (pgvector:pg16)  │
│  - PostgreSQL 16                    │
│  - pgvector 0.8.x 向量索引         │
│  - LangGraph checkpoint             │
└─────────────────────────────────────┘
```

---

*最后更新：2026-03-01，部署耗时约 3 小时（含所有踩坑）*
