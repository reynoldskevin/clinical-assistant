# Sidecar image for Railway. Build context is the repo root (railway up uploads
# the git root), so COPY paths are prefixed with sidecar/. Point the service at
# this file via RAILWAY_DOCKERFILE_PATH=sidecar/Dockerfile.
FROM python:3.12-slim

WORKDIR /app

COPY sidecar/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sidecar/ .

# server.py binds 0.0.0.0:$PORT when a platform port is present (Railway sets $PORT).
CMD ["python", "server.py"]
