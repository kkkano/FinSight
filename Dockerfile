# FinSight Backend — Production Dockerfile
# Python 3.11-slim + all ML deps (bge-m3, FlagEmbedding, torch)
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
COPY requirements.txt .

# Main package index is configurable at build time. It is also used as the
# fallback index for torch dependencies that are not hosted on the PyTorch index.
ARG PIP_INDEX_URL=https://pypi.org/simple

# Pre-install CPU-only torch to avoid downloading CUDA packages (~3 GB saved on CPU-only servers)
# BGE_M3_DEVICE=cpu so we never need CUDA at runtime
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN PIP_DEFAULT_TIMEOUT=300 PIP_RETRIES=10 pip install --no-cache-dir --timeout 300 --retries 10 \
    --index-url "$TORCH_INDEX_URL" \
    --extra-index-url "$PIP_INDEX_URL" \
    torch

# Slow domestic links can stall large wheel downloads; keep the main dependency layer retryable.
RUN PIP_DEFAULT_TIMEOUT=300 PIP_RETRIES=10 pip install --no-cache-dir --timeout 300 --retries 10 --index-url "$PIP_INDEX_URL" -r requirements.txt

# Copy full project
COPY . .

# Create persistent data directories
RUN mkdir -p data/langgraph data/memory backend/data logs

# Model cache stays in a named volume (mounted at runtime)
ENV HF_HOME=/app/.cache/huggingface
ENV TORCH_HOME=/app/.cache/torch
RUN mkdir -p /app/.cache/huggingface /app/.cache/torch

# Expose backend port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-keep-alive", "300"]
