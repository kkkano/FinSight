# FinSight Backend — Production Dockerfile
# Python 3.11-slim + all ML deps (bge-m3, FlagEmbedding, torch)
FROM python:3.11-slim

# System deps: build-essential for C extensions, libpq for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
