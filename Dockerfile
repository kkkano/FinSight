# FinSight Backend — Production Dockerfile
# Python 3.11-slim，词法/托管API模式的轻量运行依赖
FROM python:3.11-slim

# System deps: build-essential for C extensions, libpq for psycopg
ARG APT_MIRROR=
ARG APT_SECURITY_MIRROR=
RUN set -eux; \
    if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -n "$APT_SECURITY_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org/debian-security|$APT_SECURITY_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=45 -o Acquire::https::Timeout=45 update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt requirements-runtime.txt ./

# 运行镜像不安装Torch或任何本地向量推理库。
ARG PIP_INDEX_URL=https://pypi.org/simple

# Slow domestic links can stall large wheel downloads; keep the main dependency layer retryable.
RUN PIP_DEFAULT_TIMEOUT=300 PIP_RETRIES=10 pip install --no-cache-dir --timeout 300 --retries 10 --index-url "$PIP_INDEX_URL" -r requirements.txt

# Copy full project
COPY . .

# Create persistent data directories
RUN mkdir -p data/langgraph backend/data logs

# Expose backend port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=5 \
    CMD curl -f http://127.0.0.1:8000/readyz || exit 1

CMD ["python", "-m", "uvicorn", "backend.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-keep-alive", "300"]
