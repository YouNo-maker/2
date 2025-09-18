# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (better layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY app ./app
COPY config ./config
COPY scripts ./scripts
COPY main.py README.md ./

# Create non-root user and data dir
RUN useradd -m -u 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

VOLUME ["/app/data"]
EXPOSE 8000

ENV HOST=0.0.0.0 \
    PORT=8000 \
    APP_CONFIG_PATH=/app/config/config.yaml

USER appuser

CMD ["python", "main.py"] 