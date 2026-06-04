# FinSight Frontend — Multi-stage Dockerfile
# Stage 1: build  (node:20-alpine)
# Stage 2: serve  (nginx:alpine)

# ── Stage 1: Build ────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# API base URL injected at build time (e.g. http://175.178.159.112:8000)
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ARG VITE_SUPABASE_URL=
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY=
ENV VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY
# RAG Inspector 本地开发密码入口 token（敏感，默认空——生产用 Supabase 邮箱登录）
ARG VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN=
ENV VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN=$VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN
# SSE 空闲兜底完成超时（毫秒），client.ts 默认 8000
ARG VITE_SSE_IDLE_DONE_FALLBACK_MS=8000
ENV VITE_SSE_IDLE_DONE_FALLBACK_MS=$VITE_SSE_IDLE_DONE_FALLBACK_MS
# SSE 读取超时（毫秒），client.ts 默认 30000
ARG VITE_SSE_READ_TIMEOUT_MS=30000
ENV VITE_SSE_READ_TIMEOUT_MS=$VITE_SSE_READ_TIMEOUT_MS
# 对话历史最大携带条数，ChatInput.tsx 默认 12
ARG VITE_CHAT_HISTORY_MAX_MESSAGES=12
ENV VITE_CHAT_HISTORY_MAX_MESSAGES=$VITE_CHAT_HISTORY_MAX_MESSAGES

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ── Stage 2: Serve ────────────────────────────────────────────────────────
FROM nginx:alpine AS runner

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Inject custom nginx config (SSE support + SPA fallback)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
